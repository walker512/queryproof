"""Bounded single-table row/count witnesses. Not arbitrary SQL lineage. MIT walker512."""
import argparse,base64,csv,hashlib,html,json,math,os,re,sqlite3,stat,sys,tempfile,time
from contextlib import closing
from pathlib import Path
import queryproof as legacy
VERSION='0.3.0'
MAX_SPEC=1024*1024
MAX_EVIDENCE=4*1024*1024
MAX_OUTPUT=16*1024*1024
FILES={'snapshot.sqlite','spec.json','queries.json','witness.json','receipt.json','report.html'}
class Invalid(ValueError):pass
def canon(d):return legacy.canonical(d)
def sha(b):return hashlib.sha256(b).hexdigest()
def exact(d,keys):
    if type(d) is not dict or set(d)!=set(keys):raise Invalid('Exact schema fields required.')
def integer(x,lo,hi):
    if type(x) is not int or not lo<=x<=hi:raise Invalid('Bounded integer required; booleans are not integers.')
def text(x,limit=200):
    if type(x) is not str or not x or len(x)>limit or '\0' in x:raise Invalid('Bounded text required.')
    try:x.encode('utf8')
    except UnicodeError:raise Invalid('Invalid Unicode.') from None
    return x

def regular(path,limit):
    p=Path(path)
    if not stat.S_ISREG(p.lstat().st_mode) or p.stat().st_size>limit:raise Invalid('Bounded regular non-symlink file required.')
    return p

def read(path,limit):
    p=regular(path,limit);fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0))
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size>limit:raise Invalid('File type/size changed.')
        with os.fdopen(fd,'rb') as f:fd=None;b=f.read(limit+1)
    finally:
        if fd is not None:os.close(fd)
    if len(b)>limit:raise Invalid('File exceeds bound.')
    return b

def parse(b,limit=MAX_SPEC):
    if len(b)>limit:raise Invalid('JSON exceeds bound.')
    def pairs(ps):
        d={}
        for k,v in ps:
            if k in d:raise Invalid('Duplicate JSON key.')
            k.encode('utf8');d[k]=v
        return d
    def bad(x):raise Invalid('Floating JSON values unsupported; real literals use hex strings.')
    try:
        d=json.loads(b.decode('utf8'),object_pairs_hook=pairs,parse_float=bad,parse_constant=bad);stack=[(d,0)]
        while stack:
            x,n=stack.pop()
            if n>16:raise Invalid('JSON depth exceeded.')
            if type(x) is dict:stack.extend((v,n+1) for v in x.values())
            elif type(x) is list:stack.extend((v,n+1) for v in x)
            elif type(x) is str:x.encode('utf8')
        return d
    except (ValueError,UnicodeError,RecursionError):raise Invalid('Invalid strict JSON.') from None

def typed(v):
    if v is None:return {'type':'null','value':None}
    if type(v) is int:return {'type':'integer','value':v}
    if type(v) is float:
        if not math.isfinite(v):raise Invalid('Nonfinite SQLite real not supported.')
        return {'type':'real','value':v.hex()}
    if type(v) is str:
        v.encode('utf8');return {'type':'text','value':v}
    if type(v) is bytes:return {'type':'blob','value':base64.b64encode(v).decode('ascii')}
    raise Invalid('Unsupported SQLite storage value.')

def literal(d):
    exact(d,('type','value'));t=d['type'];v=d['value']
    if t=='integer':integer(v,-2**63,2**63-1);return v
    if t=='text':
        if type(v) is not str or len(v)>65536:raise Invalid('Text literal too large.')
        v.encode('utf8');return v
    if t=='blob':
        if type(v) is not str or len(v)>65536:raise Invalid('Blob literal too large.')
        try:b=base64.b64decode(v,validate=True)
        except ValueError:raise Invalid('Invalid blob base64.') from None
        if base64.b64encode(b).decode()!=v:raise Invalid('Canonical base64 required.')
        return b
    if t=='real':
        if type(v) is not str or len(v)>64:raise Invalid('Real literal requires canonical float.hex string.')
        try:f=float.fromhex(v)
        except (ValueError,OverflowError):raise Invalid('Invalid real literal.') from None
        if not math.isfinite(f) or f.hex()!=v:raise Invalid('Finite canonical float.hex literal required.')
        return f
    raise Invalid('Non-NULL predicates need explicit integer/real/text/blob literals.')

def spec(raw):
    s=parse(raw);exact(s,('schema','table','mode','project','filters','order','limit','offset'));integer(s['schema'],1,1);text(s['table'])
    if s['mode'] not in ('rows','count'):raise Invalid('Only rows or COUNT(*) supported.')
    if type(s['project']) is not list or len(s['project'])>128 or any(type(x) is not str for x in s['project']) or len(set(s['project']))!=len(s['project']):raise Invalid('Unique projection names required.')
    if type(s['filters']) is not list or len(s['filters'])>32:raise Invalid('At most 32 AND predicates.')
    for f in s['filters']:
        exact(f,('column','op','literal'));text(f['column'])
        if f['op'] in ('is_null','not_null'):
            if f['literal'] is not None:raise Invalid('NULL predicates cannot carry a literal.')
        elif f['op'] in ('eq','ne','lt','le','gt','ge'):literal(f['literal'])
        else:raise Invalid('Unsupported predicate.')
    if type(s['order']) is not list or len(s['order'])>16:raise Invalid('At most 16 ordering terms.')
    seen=set()
    for o in s['order']:
        exact(o,('column','direction','nulls'));text(o['column'])
        if o['column'] in seen or o['direction'] not in ('asc','desc') or o['nulls'] not in ('first','last'):raise Invalid('Invalid or duplicate ordering term.')
        seen.add(o['column'])
    if s['mode']=='count':
        if s['project'] or s['order'] or s['limit'] is not None or s['offset'] is not None:raise Invalid('COUNT(*) uses the complete matching set, no projection/order/page.')
    else:
        if not s['project']:raise Invalid('Rows need explicit projection.')
        integer(s['limit'],1,10000);integer(s['offset'],0,10**9)
    return s

def schema(con,table):
    if sqlite3.sqlite_version_info<(3,37,0):raise Invalid('Witness mode requires SQLite 3.37+ introspection.')
    entries=con.execute('PRAGMA main.table_list').fetchall();matches=[x for x in entries if x[0]=='main' and x[1]==table]
    if len(matches)!=1 or matches[0][2]!='table' or table.startswith('sqlite_'):raise Invalid('Select an exact ordinary user table, not view/virtual/shadow.')
    cols=con.execute('PRAGMA main.table_xinfo('+legacy.qi(table)+')').fetchall()
    if not 1<=len(cols)<=128 or any(r[6]!=0 for r in cols):raise Invalid('Only ordinary non-generated visible columns supported.')
    names=[r[1] for r in cols]
    if len(set(names))!=len(names):raise Invalid('Ambiguous column names.')
    for n in names:text(n)
    if matches[0][4]:
        keys=sorted((r for r in cols if r[5]>0),key=lambda r:r[5])
        if not keys or [r[5] for r in keys]!=list(range(1,len(keys)+1)) or any(r[3]!=1 for r in keys):raise Invalid('WITHOUT ROWID requires introspected non-null primary key.')
        locator={'kind':'primary_key','columns':[r[1] for r in keys]}
    else:
        hidden=[a for a in ('rowid','_rowid_','oid') if a not in {n.lower() for n in names}]
        if not hidden:raise Invalid('All rowid aliases are shadowed; no locator inferred.')
        locator={'kind':'rowid','alias':hidden[0]}
    return {'table':table,'columns':names,'locator':locator,'without_rowid':bool(matches[0][4])}

def queries(s,meta):
    columns=meta['columns'];wanted=s['project']+[f['column'] for f in s['filters']]+[o['column'] for o in s['order']]
    if any(x not in columns for x in wanted):raise Invalid('Spec refers to unknown exact column.')
    q=lambda x:'t.'+legacy.qi(x)
    where=[];params=[]
    for f in s['filters']:
        expr='(+'+q(f['column'])+') COLLATE BINARY'
        if f['op'] in ('is_null','not_null'):where.append(expr+(' IS NULL' if f['op']=='is_null' else ' IS NOT NULL'))
        else:
            where.append('(typeof('+q(f['column'])+') = ? AND '+expr+' '+{'eq':'=','ne':'<>','lt':'<','le':'<=','gt':'>','ge':'>='}[f['op']]+' ?)');params.extend([f['literal']['type'],literal(f['literal'])])
    base=' FROM '+legacy.qi(s['table'])+' AS t'+(' WHERE '+' AND '.join(where) if where else '')
    loc=meta['locator'];keys=[loc['alias']] if loc['kind']=='rowid' else loc['columns']
    def ordering(col,direction='asc',nulls='first'):
        x=q(col);return [f'CASE WHEN {x} IS NULL THEN '+('0 ELSE 1' if nulls=='first' else '1 ELSE 0')+' END ASC',f"CASE typeof({x}) WHEN 'null' THEN 0 WHEN 'integer' THEN 1 WHEN 'real' THEN 2 WHEN 'text' THEN 3 WHEN 'blob' THEN 4 END ASC",'(+ '+x+') COLLATE BINARY '+direction.upper()]
    order=[]
    if s['mode']=='rows':
        for o in s['order']:order+=ordering(o['column'],o['direction'],o['nulls'])
    for k in keys:order+=ordering(k)
    ordered=' ORDER BY '+', '.join(order)
    page=' LIMIT ? OFFSET ?' if s['mode']=='rows' else ''
    tail=[s['limit'],s['offset']] if s['mode']=='rows' else []
    witness='SELECT '+', '.join(q(k) for k in keys+columns)+base+ordered+page
    result='SELECT '+(', '.join(q(k) for k in s['project']) if s['mode']=='rows' else 'COUNT(*) AS "count"')+base+(ordered+page if s['mode']=='rows' else '')
    count='SELECT COUNT(*)'+base
    return {'result_sql':result,'witness_sql':witness,'matched_count_sql':count,'filter_parameters':[typed(v) for v in params],'page_parameters':[typed(v) for v in tail],'sort_semantics':'Explicit NULL placement; storage classes integer,real,text,blob ascending; within-class requested value direction with BINARY text; locator ascending tie-break. Locator is snapshot-local only.'},params,tail,keys

def compute(path,s):
    with closing(legacy.connect(path)) as con:
        con.execute('BEGIN');deadline=time.monotonic()+2;con.set_progress_handler(lambda:int(time.monotonic()>deadline),1000);meta=schema(con,s['table']);qs,params,tail,keys=queries(s,meta)
        def authorize(action,a,b,db,trigger):
            if action==sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_READ and a==s['table'] and (db=='main' or (db is None and b=='')):return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_FUNCTION and (b or '').lower() in ('count','typeof'):return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        con.set_authorizer(authorize)
        matched=con.execute(qs['matched_count_sql'],params).fetchone()[0]
        if s['mode']=='count' and matched>10000:raise Invalid('COUNT witness set exceeds 10000 rows; narrow the filter.')
        witness=[];size=0
        for ordinal,row in enumerate(con.execute(qs['witness_sql'],params+tail)):
            if ordinal>=10000:raise Invalid('Witness row bound exceeded.')
            locvals=[typed(v) for v in row[:len(keys)]];values=[typed(v) for v in row[len(keys):]]
            item={'ordinal':ordinal,'locator':{'kind':meta['locator']['kind'],'columns':keys,'values':locvals},'source_values':values}
            size+=len(canon(item))
            if size>MAX_EVIDENCE:raise Invalid('Complete source witness exceeds 4 MiB; no truncation allowed.')
            witness.append(item)
        results=[]
        for row in con.execute(qs['result_sql'],params+tail if s['mode']=='rows' else params):
            results.append([typed(v) for v in row])
            if len(results)>10000:raise Invalid('Result row bound exceeded.')
        if s['mode']=='rows':
            positions=[meta['columns'].index(x) for x in s['project']]
            derived=[[w['source_values'][i] for i in positions] for w in witness]
            if canon(results)!=canon(derived):raise Invalid('SQL projection differs from witness-derived result.')
            start=min(s['offset'],matched);stop=start+len(results)
        else:
            if results!=[[typed(len(witness))]] or len(witness)!=matched:raise Invalid('COUNT result differs from complete witness set.')
            start=0;stop=matched
        # Diagnostics are explicitly for the captured source set, not all database tables.
        diagnostics=[{'column':c,'sql_null':sum(w['source_values'][i]['type']=='null' for w in witness),'empty_text':sum(w['source_values'][i]=={'type':'text','value':''} for w in witness)} for i,c in enumerate(meta['columns'])]
    evidence={'schema':1,'mode':s['mode'],'source_schema':meta,'result_columns':s['project'] if s['mode']=='rows' else ['count'],'result_rows':results,'matched_rows':matched,'included_source_rows':len(witness),'source_range_start':start,'source_range_end_exclusive':stop,'matching_rows_not_included':matched-len(witness),'witnesses':witness,'captured_source_null_empty_diagnostics':diagnostics,'diagnostic_scope':'Only included witness rows; not the legacy whole-snapshot profile/key/join diagnostics.','semantic_correctness_verified':False,'snapshot_local_locators':True}
    if len(canon(evidence))>MAX_EVIDENCE:raise Invalid('Evidence including typed results exceeds 4 MiB.')
    return qs,evidence

def environment():
    e=legacy.environment();e['witness_version']=VERSION;return e

def render(receipt,evidence,qs):
    esc=lambda v:html.escape(str(v),quote=True)
    body='<h1>Single-table source witnesses</h1><p>PRIVATE: full database snapshot, complete source rows and filters. Internal recomputation is not business truth or authorship.</p>'
    body+='<p>Matched '+esc(evidence['matched_rows'])+'; captured '+esc(evidence['included_source_rows'])+'; not included '+esc(evidence['matching_rows_not_included'])+'.</p>'
    for title,obj in (('Generated queries and typed parameters',qs),('Exact result and snapshot-local source witnesses',evidence),('Receipt',receipt)):
        body+='<h2>'+title+'</h2><pre>'+esc(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2))+'</pre>'
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>QueryProof witnesses</title><style>body{max-width:1100px;margin:2rem auto;padding:1rem;font:16px system-ui;background:#10202a;color:#def}pre{white-space:pre-wrap;overflow-wrap:anywhere}p{padding:1rem;border:1px solid #b85}</style>'+body+'</html>').encode('utf8')

def products(snapshot_hash,sraw,sources,qs,evidence,recorded=None):
    qr=canon(qs);wr=canon(evidence);env=recorded or environment()
    r={'format':'queryproof-witness/1','version':VERSION,'snapshot_sha256':snapshot_hash,'spec_sha256':sha(sraw),'queries_sha256':sha(qr),'witness_sha256':sha(wr),'sources':sources,'environment':env,'limits':{'snapshot_bytes':legacy.MAX_FILE,'witness_rows':10000,'evidence_bytes':MAX_EVIDENCE,'query_seconds':2},'scope':'One ordinary table; recomputation only, not authenticated source truth, arbitrary SQL lineage or cross-snapshot row identity.'}
    r['receipt_sha256']=sha(canon(r));rr=canon(r)
    files={'spec.json':sraw,'queries.json':qr,'witness.json':wr,'receipt.json':rr,'report.html':render(r,evidence,qs)}
    if any(len(b)>MAX_OUTPUT for b in files.values()):raise Invalid('Generated output exceeds bound.')
    return files

def create(out,spec_path,database=None,csvs=()):
    if bool(database)==bool(csvs):raise Invalid('Choose SQLite or CSV input, not both.')
    dest=Path(out)
    if dest.exists() or dest.is_symlink():raise Invalid('Destination must not exist.')
    sr=read(spec_path,MAX_SPEC);s=spec(sr)
    if database:regular(database,legacy.MAX_FILE)
    for n,p in csvs:text(n);regular(p,legacy.MAX_FILE)
    if len(csvs)>32:raise Invalid('At most 32 CSV tables.')
    # Same-filesystem publication; the original input is never modified.
    with tempfile.TemporaryDirectory(prefix='.queryproof-witness-',dir=dest.parent) as td:
        tmp=Path(td);db=tmp/'snapshot.sqlite';sources=legacy.snapshot(db,database,csvs)
        # Normalize only our private backup, never the user's live WAL database.
        with closing(sqlite3.connect(db,timeout=2)) as own:
            own.execute('PRAGMA trusted_schema=OFF')
            if own.execute('PRAGMA journal_mode=DELETE').fetchone()[0]!='delete':raise Invalid('Private snapshot journal normalization failed.')
        qs,evidence=compute(db,s);files=products(sha(read(db,legacy.MAX_FILE)),sr,sources,qs,evidence)
        for n,b in files.items():(tmp/n).write_bytes(b)
        verify(tmp)
        # Reserve an absent destination to refuse even a newly appeared empty directory.
        dest.mkdir(exist_ok=False)
        try:os.replace(tmp,dest)
        except Exception:
            try:dest.rmdir()
            except OSError:pass
            raise
    return {'created':True,'mode':s['mode'],'matched_rows':evidence['matched_rows'],'included_source_rows':evidence['included_source_rows'],'matching_rows_not_included':evidence['matching_rows_not_included'],'semantic_correctness_verified':False}

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or set(p.name for p in root.iterdir())!=FILES:raise Invalid('Exact bundle files required; no WAL/journal/extra files allowed.')
    data={n:read(root/n,legacy.MAX_FILE if n=='snapshot.sqlite' else MAX_SPEC if n=='spec.json' else MAX_OUTPUT) for n in FILES}
    r=parse(data['receipt.json'],MAX_OUTPUT);exact(r,('format','version','snapshot_sha256','spec_sha256','queries_sha256','witness_sha256','sources','environment','limits','scope','receipt_sha256'))
    if r['format']!='queryproof-witness/1' or r['version']!=VERSION or r['receipt_sha256']!=sha(canon({k:v for k,v in r.items() if k!='receipt_sha256'})):raise Invalid('Receipt schema/hash mismatch.')
    if r['snapshot_sha256']!=sha(data['snapshot.sqlite']) or r['spec_sha256']!=sha(data['spec.json']):raise Invalid('Snapshot/spec checksum mismatch.')
    recorded=r['environment'];current=environment();exact(recorded,current)
    if any(recorded[k]!=current[k] for k in ('sqlite_version','sqlite_source_id','sqlite_compile_options','queryproof_version','witness_version')):raise Invalid('SQLite build or tool version differs; use recorded environment.')
    for k in current:
        if k!='sqlite_compile_options' and (type(recorded[k]) is not str or not recorded[k]):raise Invalid('Invalid environment record.')
    if type(r['sources']) is not list or not 1<=len(r['sources'])<=32:raise Invalid('Invalid source description count.')
    kinds=[x.get('kind') if type(x) is dict else None for x in r['sources']]
    if kinds!=['sqlite'] and (any(k!='csv' for k in kinds) or len({str(x.get('table')) for x in r['sources']})!=len(kinds)):raise Invalid('Source descriptions must be one SQLite or distinct CSV tables.')
    for source in r['sources']:
        if type(source) is not dict:raise Invalid('Invalid source description.')
        if source.get('kind')=='sqlite':
            exact(source,('kind','note'))
            if source['note']!='Snapshot is a consistent SQLite backup, including committed WAL data.':raise Invalid('Unsupported source note.')
        elif source.get('kind')=='csv':
            exact(source,('kind','table','sha256','rows','semantics'));text(source['table']);integer(source['rows'],0,100000)
            if type(source['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',source['sha256']) or source['semantics']!='All cells TEXT; empty string is not SQL NULL.':raise Invalid('Invalid CSV description.')
        else:raise Invalid('Unknown source description.')
    with tempfile.TemporaryDirectory(prefix='queryproof-witness-verify-') as td:
        db=Path(td)/'snapshot.sqlite';db.write_bytes(data['snapshot.sqlite']);qs,evidence=compute(db,spec(data['spec.json']))
    rebuilt=products(r['snapshot_sha256'],data['spec.json'],r['sources'],qs,evidence,recorded)
    if any(data[n]!=b for n,b in rebuilt.items()):raise Invalid('Regenerated witness/query/report differs.')
    return {'verified':True,'matched_rows':evidence['matched_rows'],'included_source_rows':evidence['included_source_rows'],'semantic_correctness_verified':False}

def main(argv=None):
    p=argparse.ArgumentParser(description='Single-table typed source witnesses, not arbitrary SQL lineage.')
    sub=p.add_subparsers(dest='cmd',required=True);a=sub.add_parser('run');g=a.add_mutually_exclusive_group(required=True);g.add_argument('--db');g.add_argument('--csv',action='append',metavar='TABLE=PATH');a.add_argument('--spec',required=True);a.add_argument('--out',required=True);a=sub.add_parser('verify');a.add_argument('directory');a=p.parse_args(argv)
    try:
        if a.cmd=='verify':r=verify(a.directory)
        else:
            csvs=[]
            for item in a.csv or []:
                if '=' not in item:raise Invalid('CSV requires TABLE=PATH.')
                csvs.append(item.split('=',1))
            r=create(a.out,a.spec,a.db,csvs)
        print(json.dumps(r));return 0
    except (ValueError,OSError,sqlite3.Error,csv.Error,UnicodeError,TypeError,KeyError,RecursionError):
        print('Witness operation failed. Check exact supported schema/spec, stable local input, bounds, SQLite build and output. No SQL, values or private paths echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
