"""Optional comparison; install datasette==0.65.2 separately. No network/server."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queryproof as q
from datasette.app import Datasette

async def main():
    root = Path(__file__).resolve().parents[1]
    output = {'datasette_version': '0.65.2', 'scope': 'Default Datasette without plugins; no overall-superiority claim.'}
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp)/'snapshot.sqlite'
        q.snapshot(db, csvs=[('sales', root/'examples/sales.csv'), ('labels', root/'examples/labels.csv')])
        before = q.filehash(db)
        ds = Datasette([str(db)])
        output['queries'] = []
        for name in ['inflated', 'correct']:
            sql = (root/'examples'/f'{name}.sql').read_text()
            response = await ds.client.get('/snapshot.json', params={'sql': sql})
            data = response.json()
            proof = q.create(db, sql, joins=[('sales','customer','labels','customer')], include_rows=True)
            assert data['rows'] == proof['result']['rows']
            assert q.verify(db, proof)
            output['queries'].append({'case':name, 'datasette_status':response.status_code, 'datasette_rows':data['rows'], 'datasette_keys':list(data), 'queryproof_rows':proof['result']['rows'], 'queryproof_join':proof['join_checks'], 'queryproof_verified':True})
        response = await ds.client.get('/snapshot.json', params={'sql':'DELETE FROM sales'})
        assert response.status_code == 400
        assert q.filehash(db) == before
        output['datasette_delete'] = response.json()
        if len(sys.argv) > 1:
            engine = Path(sys.argv[1])/'engine.py'
            spec = importlib.util.spec_from_file_location('join_engine', engine)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            report = module.inspect({'left':(root/'examples/sales.csv').read_text(), 'right':(root/'examples/labels.csv').read_text(), 'left_keys':['customer'], 'right_keys':['customer'], 'expect':'one:one'})
            exact = report['policies'][0]
            assert exact['inner'] == 5 and exact['many_many_groups'] == 1 and not exact['contract_pass']
            output['join_key_lab'] = {'engine_sha256':hashlib.sha256(engine.read_bytes()).hexdigest(), 'exact':exact, 'policies':[x['policy'] for x in report['policies']]}
    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
