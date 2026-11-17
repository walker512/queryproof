"""Original synthetic SQLite tables; no business/private data."""
import copy,json,os,shutil,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import queryproof_witness as w
ROOT=Path(__file__).resolve().parents[1]
def rows(table='items',project=None):return {'schema':1,'table':table,'mode':'rows','project':project or ['label'],'filters':[],'order':[],'limit':100,'offset':0}
def count(table='items'):
    d=rows(table);d.update(mode='count',project=[],limit=None,offset=None);return d
def pred(column,op,kind=None,value=None):return {'column':column,'op':op,'literal':{'type':kind,'value':value} if kind else None}
class WitnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.db=self.p/'source.sqlite';self.n=0
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE items(label TEXT, value, note TEXT COLLATE NOCASE)')
            c.executemany('INSERT INTO items VALUES(?,?,?)',[('duplicate',1,'A'),('duplicate',1.0,'a'),('',None,''),('blob',b'\x00\xff',None),('text','1','B')])
    def run_it(self,s=None,csvs=()):
        self.n+=1;f=self.p/('spec'+str(self.n)+'.json');f.write_bytes(w.canon(s or rows()));out=self.p/('out'+str(self.n));r=w.create(out,f,None if csvs else self.db,csvs);return out,w.parse((out/'witness.json').read_bytes(),w.MAX_OUTPUT),r
    def test_duplicate_values_separate_source_rows(self):
        out,e,r=self.run_it();self.assertEqual(e['result_rows'][0],e['result_rows'][1]);self.assertNotEqual(e['witnesses'][0]['locator'],e['witnesses'][1]['locator']);self.assertEqual(len(e['witnesses'][0]['source_values']),3);self.assertTrue(w.verify(out)['verified'])
    def test_typed_filters_no_affinity(self):
        for typ,val in (('integer',1),('real',float(1).hex()),('text','1'),('blob','AP8=')):
            s=rows(project=['value']);s['filters']=[pred('value','eq',typ,val)];_,e,_=self.run_it(s);self.assertEqual(len(e['witnesses']),1);self.assertEqual(e['result_rows'][0][0]['type'],typ)
    def test_no_declared_text_affinity(self):
        s=rows();s['filters']=[pred('label','eq','integer',1)];_,e,_=self.run_it(s);self.assertEqual(e['matched_rows'],0)
    def test_explicit_binary_not_nocase(self):
        s=rows(project=['note']);s['filters']=[pred('note','eq','text','A')];_,e,_=self.run_it(s);self.assertEqual(e['result_rows'],[[w.typed('A')]])
    def test_null_empty_and_diagnostics(self):
        s=rows();s['filters']=[pred('value','is_null')];_,e,_=self.run_it(s);self.assertEqual(e['result_rows'],[[w.typed('')]]);self.assertEqual(e['captured_source_null_empty_diagnostics'][1]['sql_null'],1);self.assertEqual(e['captured_source_null_empty_diagnostics'][0]['empty_text'],1)
        s['filters']=[pred('value','not_null')];_,e,_=self.run_it(s);self.assertEqual(e['matched_rows'],4)
    def test_pagination_coverage_deterministic_ties(self):
        s=rows();s.update(limit=1,offset=1);s['order']=[{'column':'label','direction':'asc','nulls':'last'}];out,e,_=self.run_it(s);self.assertEqual((e['matched_rows'],e['included_source_rows'],e['matching_rows_not_included']),(5,1,4));self.assertEqual((e['source_range_start'],e['source_range_end_exclusive']),(1,2));w.verify(out)
        s['offset']=999;_,e,_=self.run_it(s);self.assertEqual(e['source_range_start'],5);self.assertEqual(e['source_range_end_exclusive'],5);self.assertEqual(e['result_rows'],[])
    def test_storage_type_order_and_null_placement(self):
        s=rows(project=['value']);s['order']=[{'column':'value','direction':'desc','nulls':'last'}];_,e,_=self.run_it(s);self.assertEqual([r[0]['type'] for r in e['result_rows']],['integer','real','text','blob','null'])
    def test_count_complete_set_and_zero(self):
        out,e,_=self.run_it(count());self.assertEqual(e['result_rows'],[[w.typed(5)]]);self.assertEqual(len(e['witnesses']),5);self.assertEqual(e['matching_rows_not_included'],0);w.verify(out)
        s=count();s['filters']=[pred('label','eq','text','absent')];_,e,_=self.run_it(s);self.assertEqual(e['result_rows'],[[w.typed(0)]]);self.assertEqual(e['witnesses'],[])
    def test_composite_without_rowid(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE keyed(a TEXT,b INTEGER,value TEXT,PRIMARY KEY(a,b)) WITHOUT ROWID');c.executemany('INSERT INTO keyed VALUES(?,?,?)',[('b',1,'same'),('a',2,'same'),('a',1,'same')])
        out,e,_=self.run_it(rows('keyed',['value']));self.assertEqual(e['source_schema']['locator'],{'kind':'primary_key','columns':['a','b']});self.assertEqual([x['locator']['values'] for x in e['witnesses']],[[w.typed('a'),w.typed(1)],[w.typed('a'),w.typed(2)],[w.typed('b'),w.typed(1)]]);w.verify(out)
    def test_rowid_alias_shadowing(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE partial("RoWiD" TEXT,value INTEGER)');c.execute("INSERT INTO partial VALUES('not-locator',9)");c.execute('CREATE TABLE full(rowid,_rowid_,oid)');c.execute('INSERT INTO full VALUES(1,2,3)')
        _,e,_=self.run_it(rows('partial',['RoWiD']));self.assertEqual(e['source_schema']['locator']['alias'],'_rowid_');self.assertEqual(e['witnesses'][0]['locator']['values'],[w.typed(1)])
        with self.assertRaises(ValueError):self.run_it(rows('full',['rowid']))
    def test_view_virtual_generated_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE VIEW v AS SELECT * FROM items');c.execute('CREATE TABLE generated(x INT,y INT GENERATED ALWAYS AS (x+1))');c.execute('CREATE VIRTUAL TABLE virtual USING fts5(value)')
        for table,col in (('v','label'),('generated','x'),('virtual','value'),('virtual_data','id')):
            with self.assertRaises(ValueError):self.run_it(rows(table,[col]))
    def test_identifier_quotes_and_html_inert(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('CREATE TABLE "odd\"\"table" ("<script>" TEXT)');c.execute('INSERT INTO "odd\"\"table" VALUES(?)',('<img src=x onerror=alert(1)>',))
        out,e,_=self.run_it(rows('odd"table',['<script>']));h=(out/'report.html').read_text();self.assertIn('&lt;script&gt;',h);self.assertNotIn('<img',h);self.assertIn("default-src 'none'",h);w.verify(out)
    def test_nonfinite_data_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('INSERT INTO items VALUES(?,?,?)',('infinite',float('inf'),None))
        with self.assertRaises(ValueError):self.run_it()
    def test_count_limit_rows_page_does_not_truncate_silently(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('CREATE TABLE many(x)');c.executemany('INSERT INTO many VALUES(?)',((i,) for i in range(10001)))
        with self.assertRaises(ValueError):self.run_it(count('many'))
        s=rows('many',['x']);s['limit']=2;_,e,_=self.run_it(s);self.assertEqual(e['matched_rows'],10001);self.assertEqual(e['matching_rows_not_included'],9999)
    def test_evidence_size_limit_and_no_published_output(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('CREATE TABLE big(v)');c.executemany('INSERT INTO big VALUES(?)',[(b'x'*900000,)]*5)
        with self.assertRaises(ValueError):self.run_it(rows('big',['v']))
        self.assertFalse((self.p/'out1').exists())
    def test_live_committed_wal(self):
        c=sqlite3.connect(self.db);self.addCleanup(c.close);c.execute('PRAGMA journal_mode=WAL');c.execute("INSERT INTO items VALUES('committed',2,'wal')");c.commit();self.assertTrue(Path(str(self.db)+'-wal').exists());out,e,_=self.run_it();self.assertEqual(e['matched_rows'],6);self.assertTrue(any(x[0]==w.typed('committed') for x in e['result_rows']));w.verify(out)
    def test_csv_real_empty_text_not_null(self):
        f=self.p/'source.csv';f.write_text('name,value\nA,\nA,2\n');out,e,_=self.run_it(rows('csv',['name','value']),[('csv',str(f))]);self.assertEqual(e['result_rows'][0][1],w.typed(''));self.assertEqual(e['source_schema']['locator']['kind'],'rowid');w.verify(out)
    def test_each_file_tamper_and_sidecar(self):
        out,_,_=self.run_it()
        for f in out.iterdir():
            b=f.read_bytes();f.write_bytes(b+b' ')
            with self.assertRaises(ValueError):w.verify(out)
            f.write_bytes(b)
        (out/'snapshot.sqlite-wal').write_bytes(b'')
        with self.assertRaises(ValueError):w.verify(out)
    def test_rehash_witness_still_recomputed(self):
        out,_,_=self.run_it();p=out/'witness.json';d=w.parse(p.read_bytes(),w.MAX_OUTPUT);d['witnesses'][0]['source_values'][0]=w.typed('wrong');p.write_bytes(w.canon(d));r=w.parse((out/'receipt.json').read_bytes());r['witness_sha256']=w.sha(p.read_bytes());r['receipt_sha256']=w.sha(w.canon({k:v for k,v in r.items() if k!='receipt_sha256'}));(out/'receipt.json').write_bytes(w.canon(r))
        with self.assertRaises(ValueError):w.verify(out)
    def test_environment_build_mismatch(self):
        out,_,_=self.run_it();r=w.parse((out/'receipt.json').read_bytes());r['environment']['sqlite_source_id']='different';r['receipt_sha256']=w.sha(w.canon({k:v for k,v in r.items() if k!='receipt_sha256'}));(out/'receipt.json').write_bytes(w.canon(r))
        with self.assertRaises(ValueError):w.verify(out)
    def test_special_files_and_existing_output(self):
        spec=self.p/'s.json';spec.write_bytes(w.canon(rows()))
        (self.p/'out').mkdir()
        with self.assertRaises(ValueError):w.create(self.p/'out',spec,self.db)
    def test_symlink_input_rejected(self):
        spec=self.p/'s.json';spec.write_bytes(w.canon(rows()));link=self.p/'link'
        try:link.symlink_to(self.db)
        except (OSError,NotImplementedError):self.skipTest('Symlink unavailable on this platform')
        with self.assertRaises(ValueError):w.create(self.p/'out',spec,link)
    @unittest.skipUnless(hasattr(os,'mkfifo'),'FIFO unavailable on this platform')
    def test_fifo_input_rejected(self):
        f=self.p/'fifo';os.mkfifo(f)
        with self.assertRaises(ValueError):w.create(self.p/'out',f,self.db)
    def test_atomic_failure_no_partial_publication(self):
        spec=self.p/'s.json';spec.write_bytes(w.canon(rows()))
        with patch.object(w,'products',side_effect=ValueError('synthetic serialization failure')):
            with self.assertRaises(ValueError):w.create(self.p/'out',spec,self.db)
        self.assertFalse((self.p/'out').exists())
    def test_sqlite_version_too_old_controlled(self):
        with patch.object(sqlite3,'sqlite_version_info',(3,36,0)):
            with self.assertRaises(ValueError):self.run_it()
    def test_invalid_text_data_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute("INSERT INTO items VALUES(CAST(X'ff' AS TEXT),1,'invalid utf8')")
        with self.assertRaises(sqlite3.Error):self.run_it()
    def test_multiple_predicates_and_integer_endpoints(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.executemany('INSERT INTO items VALUES(?,?,?)',[('minimum',-2**63,None),('maximum',2**63-1,None)])
        for value in (-2**63,2**63-1):
            s=rows(project=['value']);s['filters']=[pred('value','ge','integer',value),pred('value','le','integer',value)];out,e,_=self.run_it(s);self.assertEqual(e['result_rows'],[[w.typed(value)]]);w.verify(out)
    def test_all_output_preflight_before_publication(self):
        f=self.p/'s.json';f.write_bytes(w.canon(rows()))
        with patch.object(w,'render',return_value=b'x'*(w.MAX_OUTPUT+1)):
            with self.assertRaises(ValueError):w.create(self.p/'out',f,self.db)
        self.assertFalse((self.p/'out').exists())
    def test_malformed_csv_cli_controlled(self):
        f=self.p/'broken.csv';f.write_text('label,value\n"unfinished,1\n');sp=self.p/'s.json';sp.write_bytes(w.canon(rows()))
        p=subprocess.run([sys.executable,'-m','queryproof_witness','run','--csv','items='+str(f),'--spec',str(sp),'--out',str(self.p/'broken-out')],cwd=ROOT,capture_output=True)
        self.assertEqual(p.returncode,2);self.assertNotIn(b'Traceback',p.stderr);self.assertFalse((self.p/'broken-out').exists())
    def test_cli_actual(self):
        f=self.p/'spec.json';f.write_bytes(w.canon(rows()));base=[sys.executable,'-m','queryproof_witness'];p=subprocess.run(base+['run','--db',str(self.db),'--spec',str(f),'--out',str(self.p/'cli')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0,p.stderr);p=subprocess.run(base+['verify',str(self.p/'cli')],cwd=ROOT,capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

class SpecTests(unittest.TestCase):
    def test_type_and_scope_rejection(self):
        for change in ({'mode':'join'},{'limit':True},{'offset':-1},{'project':[]},{'schema':True}):
            d=rows();d.update(change)
            with self.assertRaises(ValueError):w.spec(w.canon(d))
        for literal in ({'type':'integer','value':True},{'type':'integer','value':2**63},{'type':'real','value':'1.0'},{'type':'real','value':'inf'},{'type':'real','value':'nan'},{'type':'blob','value':'Zg=== '},{'type':'null','value':None}):
            with self.assertRaises(ValueError):w.literal(literal)
        d=count();d['limit']=2
        with self.assertRaises(ValueError):w.spec(w.canon(d))
    def test_strict_json_and_limits(self):
        for b in (b'{"x":1,"x":2}',b'[NaN]',b'[1.5]',b'["\\ud800"]',b'['*30+b'1'+b']'*30,b'x'*(w.MAX_SPEC+1)):
            with self.assertRaises(ValueError):w.parse(b)
    def test_real_zero_blob_text_encoding(self):
        for f in (0.0,-0.0,1.5,sys.float_info.max):self.assertEqual(w.literal(w.typed(f)).hex(),f.hex())
        for b in (b'',b'\x00\xff'):self.assertEqual(w.literal(w.typed(b)),b)
if __name__=='__main__':unittest.main()
