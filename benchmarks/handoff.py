"""Reproducible handoff fault exercise; Datasette 0.65.2, no network.
Not a human usability study. Faults and comparisons are explicit below.
"""
import asyncio
import copy
import importlib.metadata
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queryproof as q
from datasette.app import Datasette


async def manual_review(folder):
    """Automate a disclosed manual recipe, not a Datasette built-in verifier.
    Recipient inspects saved response/manifest, checks version, reruns exact SQL,
    compares ordered columns/rows. Deliberately no independent DB digest supplied:
    the comparison concerns a standard JSON + database export handoff.
    """
    response = json.loads((folder/'response.json').read_text())
    expected = json.loads((folder/'environment.json').read_text())
    sql = response.get('query', {}).get('sql')
    if not sql:
        return {'status':'SQL_MISSING', 'detected': True, 'step':'Inspect response.query.sql'}
    if expected['sqlite_version'] != sqlite3.sqlite_version:
        return {'status':'SQLITE_VERSION', 'detected': True, 'step':'Compare separately recorded SQLite version with receiver runtime'}
    ds = Datasette([str(folder/'snapshot.sqlite')])
    actual = (await ds.client.get('/snapshot.json',params={'sql':sql})).json()
    matches = all(actual.get(key)==response.get(key) for key in ('rows','columns'))
    return {'status':'RESULT_MATCH' if matches else 'RESULT_DIFFERS', 'detected':not matches,
            'step':'Rerun SQL via Datasette and compare ordered rows/columns; does not establish snapshot identity'}


async def main():
    root=Path(__file__).resolve().parents[1]
    sql=(root/'examples/correct.sql').read_text()
    output={'datasette_version':importlib.metadata.version('datasette'), 'queryproof_version':q.VERSION,
            'environment':q.environment(), 'fixture':'same sales/labels CSVs and correct.sql; fictional',
            'baseline':'Datasette default JSON response + SQLite file + separately recorded SQLite version; manual recipe automated for reproducibility, not a built-in Datasette verifier',
            'not_measured':['human completion time','user error rate','all Datasette plugins','cross-version compatibility'], 'cases':[]}
    with tempfile.TemporaryDirectory() as tmp:
        rootdir=Path(tmp); base=rootdir/'base';base.mkdir()
        q.snapshot(base/'snapshot.sqlite',csvs=[('sales',root/'examples/sales.csv'),('labels',root/'examples/labels.csv')])
        # Auxiliary metadata makes same-answer stale snapshot detection observable.
        with closing(sqlite3.connect(base/'snapshot.sqlite')) as con:
            con.executescript("CREATE TABLE revision(value TEXT); INSERT INTO revision VALUES ('current');")
        receipt=q.create(base/'snapshot.sqlite',sql,include_rows=True)
        ds=Datasette([str(base/'snapshot.sqlite')])
        response=(await ds.client.get('/snapshot.json',params={'sql':sql})).json()
        assert response['rows']==receipt['result']['rows']==[[60.0]]
        (base/'receipt.json').write_text(json.dumps(receipt))
        (base/'response.json').write_text(json.dumps(response))
        (base/'environment.json').write_text(json.dumps({'sqlite_version':sqlite3.sqlite_version}))
        cases=['intact','altered_answer','old_database_same_answer','old_database_changed_answer','missing_sql','sqlite_version_mismatch']
        for case in cases:
            folder=rootdir/case; shutil.copytree(base,folder)
            r=copy.deepcopy(receipt); d=copy.deepcopy(response)
            if case=='altered_answer':
                r['result']['rows']=[[999]];d['rows']=[[999]]
            elif case.startswith('old_database'):
                with closing(sqlite3.connect(folder/'snapshot.sqlite')) as con:
                    con.execute("UPDATE revision SET value='old'")
                    if case=='old_database_changed_answer': con.execute("UPDATE sales SET amount='0' WHERE customer='b'")
                    con.commit()
            elif case=='missing_sql':
                del r['sql'];del d['query']['sql']
            elif case=='sqlite_version_mismatch':
                # Controlled metadata fault, NOT execution on another SQLite runtime.
                r['sqlite_version']='0.0.0-test-fixture'
                r['environment']['sqlite_version']='0.0.0-test-fixture'
                r['receipt_sha256']=q.digest({k:v for k,v in r.items() if k!='receipt_sha256'})
                (folder/'environment.json').write_text(json.dumps({'sqlite_version':'0.0.0-test-fixture'}))
            (folder/'receipt.json').write_text(json.dumps(r))
            (folder/'response.json').write_text(json.dumps(d))
            qp=q.diagnose(folder); manual=await manual_review(folder)
            expected={'intact':'VERIFIED','altered_answer':'RECEIPT_CHECKSUM','old_database_same_answer':'SNAPSHOT_CHECKSUM','old_database_changed_answer':'SNAPSHOT_CHECKSUM','missing_sql':'SQL_MISSING','sqlite_version_mismatch':'SQLITE_VERSION'}[case]
            assert qp['code']==expected,(case,qp)
            assert manual['status']=={'intact':'RESULT_MATCH','altered_answer':'RESULT_DIFFERS','old_database_same_answer':'RESULT_MATCH','old_database_changed_answer':'RESULT_DIFFERS','missing_sql':'SQL_MISSING','sqlite_version_mismatch':'SQLITE_VERSION'}[case]
            output['cases'].append({'case':case,'queryproof':qp,'datasette_manual_recipe':manual})
        # Fair control: manual export augmented with a separately recorded SHA-256
        # closes the old-database-same-answer gap. No exclusive capability claim.
        changed=rootdir/'old_database_same_answer'/'snapshot.sqlite'
        output['manual_digest_control']={'provided_digest_matches_changed_database':q.filehash(changed)==q.filehash(base/'snapshot.sqlite'), 'conclusion':'Adding and checking a producer database hash also detects this identity mismatch. QueryProof packages that check; it does not invent hashing.'}
    print(json.dumps(output,indent=2))

if __name__=='__main__': asyncio.run(main())
