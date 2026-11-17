import copy
from contextlib import closing
import json
import os
import stat
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import queryproof_groups as g
import queryproof_witness as w

ROOT=Path(__file__).resolve().parents[1]

def spec():
    return {'schema':1,'table':'items','group_by':['category'],'filters':[],
            'aggregates':[{'as':'rows','op':'count_all','column':None},
                          {'as':'present','op':'count','column':'amount'},
                          {'as':'total','op':'sum_integer','column':'amount'}]}

class GroupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'source.sqlite';self.n=0
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('CREATE TABLE items(category COLLATE NOCASE,amount,note)')
            c.executemany('INSERT INTO items VALUES(?,?,?)',[('A',2,'same'),('A',2,'same'),('A',None,''),('a',-1,None),(None,None,None)])
    def run_it(self,s=None):
        self.n+=1;p=self.root/f'spec{self.n}.json';p.write_bytes(w.canon(s or spec()));out=self.root/f'out{self.n}'
        result=g.create(out,p,self.db)
        return out,w.parse((out/'groups.json').read_bytes(),w.MAX_OUTPUT),result
    def test_counts_sums_duplicates_and_null_exclusions(self):
        out,e,_=self.run_it();self.assertEqual(e['matched_rows'],5);self.assertEqual(e['matching_rows_not_included'],0)
        self.assertEqual(e['duplicate_value_rows_beyond_first'],1)
        a=next(x for x in e['groups'] if x['key']==[w.typed('A')]);self.assertEqual([x['value'] for x in a['aggregates']],[w.typed(3),w.typed(2),w.typed(4)])
        self.assertEqual(a['aggregates'][2]['included_ordinals'],[0,1]);self.assertEqual(a['aggregates'][2]['null_excluded_ordinals'],[2])
        self.assertNotEqual(e['witnesses'][0]['locator'],e['witnesses'][1]['locator']);self.assertTrue(g.verify(out)['verified'])
    def test_null_sum_is_not_zero(self):
        _,e,_=self.run_it();n=next(x for x in e['groups'] if x['key']==[w.typed(None)])
        self.assertEqual([x['value'] for x in n['aggregates']],[w.typed(1),w.typed(0),w.typed(None)])
    def test_empty_grouped_and_global(self):
        s=spec();s['filters']=[{'column':'note','op':'eq','literal':w.typed('absent')}]
        _,e,_=self.run_it(s);self.assertEqual(e['groups'],[])
        s['group_by']=[];_,e,_=self.run_it(s);self.assertEqual(len(e['groups']),1)
        self.assertEqual([a['value'] for a in e['groups'][0]['aggregates']],[w.typed(0),w.typed(0),w.typed(None)])
    def test_storage_types_and_zero_keys(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items')
            c.executemany('INSERT INTO items VALUES(?,?,NULL)',[(1,1),(1.0,2),('1',3),(b'1',4),(None,5),(0.0,6),(-0.0,7),(0,8)])
        _,e,_=self.run_it();self.assertEqual(len(e['groups']),7)
        z=next(x for x in e['groups'] if x['key']==[w.typed(0.0)])
        self.assertEqual(z['aggregates'][2]['value'],w.typed(13))
    def test_multiple_group_columns(self):
        s=spec();s['group_by']=['category','note'];_,e,_=self.run_it(s)
        self.assertEqual(len(e['groups']),4)
    def test_binary_overrides_declared_nocase(self):
        _,e,_=self.run_it();self.assertEqual(len(e['groups']),3)
    def test_strict_integer_sum_rejects_real_text_blob(self):
        for v in (1.0,'1',b'1'):
            with self.subTest(value=v),closing(sqlite3.connect(self.db)) as c,c:
                c.execute('DELETE FROM items');c.execute('INSERT INTO items VALUES(?,?,NULL)',('A',v))
            with self.assertRaises(ValueError):self.run_it()
            self.assertFalse((self.root/f'out{self.n}').exists())
    def test_count_column_all_storage_types(self):
        s=spec();s['aggregates']=s['aggregates'][:2]
        with closing(sqlite3.connect(self.db)) as c,c:
            c.executemany('INSERT INTO items VALUES(?,?,NULL)',[('A',1.0),('A','1'),('A',b'1')])
        _,e,_=self.run_it(s);a=next(x for x in e['groups'] if x['key']==[w.typed('A')]);self.assertEqual(a['aggregates'][1]['value'],w.typed(5))
    def test_sum_overflow_rejected(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,NULL)',[('A',2**63-1),('A',1)])
        with self.assertRaises(ValueError):self.run_it()
    def test_sqlite_intermediate_overflow_is_rejected_not_hidden(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,NULL)',[('A',2**63-1),('A',1),('A',-1)])
        with self.assertRaises(sqlite3.Error):self.run_it()
    def test_integer_endpoints(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,NULL)',[('A',2**63-1),('B',-2**63)])
        out,e,_=self.run_it();self.assertEqual({x['aggregates'][2]['value']['value'] for x in e['groups']},{2**63-1,-2**63});g.verify(out)
    def test_typed_filters_and_null_predicates(self):
        s=spec();s['filters']=[{'column':'category','op':'eq','literal':w.typed('A')},{'column':'amount','op':'not_null','literal':None}]
        _,e,_=self.run_it(s);self.assertEqual(e['matched_rows'],2);self.assertEqual(len(e['groups']),1)
    def test_without_rowid_composite_source_identity(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('CREATE TABLE keyed(a TEXT,b INT,amount,PRIMARY KEY(a,b)) WITHOUT ROWID');c.executemany('INSERT INTO keyed VALUES(?,?,?)',[('x',2,1),('x',1,1)])
        s=spec();s['table']='keyed';s['group_by']=['a'];out,e,_=self.run_it(s)
        self.assertEqual(e['witnesses'][0]['locator']['values'],[w.typed('x'),w.typed(1)]);self.assertEqual(e['groups'][0]['aggregates'][2]['value'],w.typed(2));g.verify(out)
    def test_quoted_identifiers_and_inert_report(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('CREATE TABLE "odd\"\""("<g>" TEXT,v)');c.execute('INSERT INTO "odd\"\"" VALUES(?,?)',('<script>alert(1)</script>',2))
        s=spec();s['table']='odd"';s['group_by']=['<g>'];s['aggregates']=[{'as':'<total>','op':'sum_integer','column':'v'}]
        out,e,_=self.run_it(s);report=(out/'report.html').read_text();self.assertNotIn('<script>',report);self.assertIn('&lt;script&gt;',report);g.verify(out)
    def test_csv_count_preserves_empty_text(self):
        p=self.root/'source.csv';p.write_text('category,amount\nA,\nA,2\n');s=spec();s['aggregates']=s['aggregates'][:2];sp=self.root/'s.json';sp.write_bytes(w.canon(s));out=self.root/'csv'
        g.create(out,sp,csvs=[('items',str(p))]);e=w.parse((out/'groups.json').read_bytes(),w.MAX_OUTPUT);self.assertEqual(e['groups'][0]['aggregates'][1]['value'],w.typed(2));g.verify(out)
        sp.write_bytes(w.canon(spec()))
        with self.assertRaises(ValueError):g.create(self.root/'csv-sum',sp,csvs=[('items',str(p))])
    def test_live_committed_wal(self):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('PRAGMA journal_mode=WAL');c.execute('INSERT INTO items VALUES("wal",3,NULL)');c.commit()
            out,e,_=self.run_it();self.assertEqual(e['matched_rows'],6);self.assertFalse((out/'snapshot.sqlite-wal').exists());g.verify(out)
    def test_unknown_columns_views_and_generated_rejected(self):
        with closing(sqlite3.connect(self.db)) as c,c:c.execute('CREATE VIEW v AS SELECT * FROM items')
        for edit in ({'group_by':['missing']},{'table':'v'},{'aggregates':[{'as':'n','op':'count','column':'missing'}]}):
            s=spec();s.update(edit)
            with self.assertRaises(ValueError):self.run_it(s)
    def test_spec_bounds_unknown_fields_and_duplicates(self):
        for patch_spec in ({'schema':True},{'group_by':['category','category']},{'group_by':['x']*9},{'aggregates':[]},{'extra':0},{'aggregates':[{'as':'category','op':'count_all','column':None}]},{'aggregates':[{'as':'n','op':'avg','column':'amount'}]},{'aggregates':[{'as':'n','op':'count_all','column':'amount'}]}):
            s=spec();s.update(patch_spec)
            with self.assertRaises(ValueError):g.spec(w.canon(s))
    def test_source_and_group_bounds_no_silent_truncation(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,NULL)',[(i,1) for i in range(1001)])
        with self.assertRaises(ValueError):self.run_it()
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,NULL)',[(1,1)]*10001)
        with self.assertRaises(ValueError):self.run_it()
    def test_every_file_tamper_extra_and_rehash(self):
        out,_,_=self.run_it()
        for p in out.iterdir():
            raw=p.read_bytes();p.write_bytes(raw+b' ')
            with self.subTest(file=p.name),self.assertRaises((ValueError,sqlite3.Error)):g.verify(out)
            p.write_bytes(raw)
        (out/'snapshot.sqlite-wal').write_bytes(b'')
        with self.assertRaises(ValueError):g.verify(out)
        (out/'snapshot.sqlite-wal').unlink()
        p=out/'groups.json';obj=w.parse(p.read_bytes(),w.MAX_OUTPUT);obj['groups'][0]['aggregates'][0]['value']=w.typed(999);p.write_bytes(w.canon(obj))
        r=w.parse((out/'receipt.json').read_bytes());r['groups_sha256']=w.sha(p.read_bytes());r['receipt_sha256']=w.sha(w.canon({k:v for k,v in r.items() if k!='receipt_sha256'}));(out/'receipt.json').write_bytes(w.canon(r))
        with self.assertRaises(ValueError):g.verify(out)
    def test_environment_binding(self):
        out,_,_=self.run_it();r=w.parse((out/'receipt.json').read_bytes());r['environment']['sqlite_source_id']='fake';r['receipt_sha256']=w.sha(w.canon({k:v for k,v in r.items() if k!='receipt_sha256'}));(out/'receipt.json').write_bytes(w.canon(r))
        with self.assertRaises(ValueError):g.verify(out)
    def test_output_preflight_and_existing_directory(self):
        s=self.root/'s.json';s.write_bytes(w.canon(spec()));out=self.root/'out'
        with patch.object(g,'products',side_effect=ValueError('serialization error')):
            with self.assertRaises(ValueError):g.create(out,s,self.db)
        self.assertFalse(out.exists());out.mkdir()
        with self.assertRaises(ValueError):g.create(out,s,self.db)
    def test_raced_output_preserved(self):
        s=self.root/'s.json';s.write_bytes(w.canon(spec()));out=self.root/'out';original=g.verify
        def race(tmp):
            result=original(tmp);out.mkdir();(out/'keep').write_text('unchanged');return result
        with patch.object(g,'verify',side_effect=race):
            with self.assertRaises(FileExistsError):g.create(out,s,self.db)
        self.assertEqual((out/'keep').read_text(),'unchanged')
    def test_publish_does_not_replace_reserved_directory(self):
        src=self.root/'src';src.mkdir();(src/'x').write_text('x');dest=self.root/'dest'
        with patch.object(w.os,'replace',side_effect=AssertionError('must not rename directory')):w.publish_directory(src,dest)
        self.assertEqual((dest/'x').read_text(),'x')
    @unittest.skipUnless(os.name == 'posix', 'POSIX permission semantics only')
    def test_private_directory_survives_publication(self):
        src=self.root/'src';src.mkdir(mode=0o700);(src/'secret').write_text('synthetic')
        old=os.umask(0o022)
        try:w.publish_directory(src,self.root/'private')
        finally:os.umask(old)
        self.assertEqual(stat.S_IMODE((self.root/'private').stat().st_mode),0o700)

    def test_actual_cli(self):
        s=self.root/'s.json';s.write_bytes(w.canon(spec()));out=self.root/'cli'
        for args in (['run','--db',str(self.db),'--spec',str(s),'--out',str(out)],['verify',str(out)]):
            r=subprocess.run([sys.executable,'-m','queryproof_groups',*args],cwd=ROOT,capture_output=True);self.assertEqual(r.returncode,0,r.stderr)
    def test_seeded_independent_group_oracle(self):
        rng=random.Random(20261117)
        keys=[None,0,0.0,1,1.0,'a','A','',b'a']
        for iteration in range(30):
            rows=[(rng.choice(keys),rng.choice([None,-2,0,7]),rng.choice(['a','b'])) for _ in range(rng.randint(0,30))]
            with closing(sqlite3.connect(self.db)) as c,c:
                c.execute('DELETE FROM items');c.executemany('INSERT INTO items VALUES(?,?,?)',rows)
            s=spec();s['group_by']=['category','note']
            _,e,_=self.run_it(s)
            oracle={}
            for key,amount,note in rows:
                identity=(type(key).__name__,key,note)
                oracle.setdefault(identity,[]).append(amount)
            actual={}
            types={'null':'NoneType','integer':'int','real':'float','text':'str','blob':'bytes'}
            for group in e['groups']:
                k=group['key'][0];value=None if k['type']=='null' else w.literal(k)
                identity=(types[k['type']],value,group['key'][1]['value'])
                actual[identity]=[a['value']['value'] for a in group['aggregates']]
            expected={k:[len(v),sum(x is not None for x in v),sum(x for x in v if x is not None) if any(x is not None for x in v) else None] for k,v in oracle.items()}
            self.assertEqual(actual,expected,iteration)

if __name__=='__main__':unittest.main()
