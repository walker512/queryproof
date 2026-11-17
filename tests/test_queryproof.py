import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import queryproof as q


class QueryProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root/'data.sqlite'
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript("CREATE TABLE sales(id TEXT, amount REAL); INSERT INTO sales VALUES ('a',10),('a',20),('b',30),(NULL,NULL); CREATE TABLE tags(id TEXT); INSERT INTO tags VALUES ('a'),('a'),('b'),(NULL);")
    def test_roundtrip(self):
        receipt = q.create(self.db, 'SELECT sum(amount) AS total FROM sales', keys=[('sales','id')], joins=[('sales','id','tags','id')])
        self.assertTrue(q.verify(self.db, receipt))
        self.assertNotIn('rows', receipt['result'])
        self.assertEqual(receipt['key_checks'][0]['duplicate_nonnull_rows'],1)
        self.assertEqual(receipt['join_checks'][0]['predicted_inner_rows'],5)
        self.assertEqual(receipt['join_checks'][0]['many_to_many_keys'],1)
    def test_tampered_receipt(self):
        r = q.create(self.db, 'SELECT 1')
        r['sql'] = 'SELECT 2'
        with self.assertRaisesRegex(ValueError,'Receipt'): q.verify(self.db,r)
    def test_tampered_snapshot(self):
        r=q.create(self.db,'SELECT 1')
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('INSERT INTO tags VALUES (9)'); c.commit()
        with self.assertRaisesRegex(ValueError,'Snapshot'): q.verify(self.db,r)
    def test_resigned_wrong_result(self):
        r=q.create(self.db,'SELECT 1')
        r['result']['row_count']=100
        r['receipt_sha256']=q.digest({k:v for k,v in r.items() if k!='receipt_sha256'})
        with self.assertRaisesRegex(ValueError,'Recomputed'): q.verify(self.db,r)
    def test_sql_security(self):
        before=q.filehash(self.db)
        attacks=['DELETE FROM sales', 'DROP TABLE sales', "ATTACH DATABASE '/tmp/qp-exfil' AS x", 'PRAGMA user_version=9', "SELECT load_extension('x')", "SELECT readfile('/etc/passwd')", 'SELECT random()', "SELECT datetime('now')", 'VACUUM', 'BEGIN', 'SELECT 1; SELECT 2']
        for sql in attacks:
            with self.subTest(sql=sql), self.assertRaises((ValueError,sqlite3.Error)): q.execute(self.db,sql)
        self.assertEqual(before,q.filehash(self.db))
    def test_timeout(self):
        with self.assertRaises(sqlite3.Error): q.execute(self.db,'WITH RECURSIVE t(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM t) SELECT sum(x) FROM t',seconds=.01)
    def test_row_limit(self):
        with self.assertRaisesRegex(ValueError,'10000'): q.execute(self.db,'WITH RECURSIVE t(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM t WHERE x<10001) SELECT x FROM t')
    def test_size_limit(self):
        self.assertEqual(q.execute(self.db,"SELECT printf('%2000000s','x')")['rows'], [[None]])
    def test_blob(self):
        r=q.create(self.db,"SELECT x'ff00'",include_rows=True)
        self.assertEqual(r['result']['rows'],[[{'blob_base64':'/wA='}]])
        self.assertTrue(q.verify(self.db,r))
    def test_unknown_columns(self):
        with self.assertRaises(ValueError): q.keycheck(self.db,'sales','missing')
        with self.assertRaises(ValueError): q.joincheck(self.db,'sales','missing','tags','id')
    def test_html_injection(self):
        r=q.create(self.db,"SELECT '<script>alert(1)</script>'",include_rows=True)
        page=q.report(r)
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)
    def test_csv(self):
        source=self.root/'source.csv'
        source.write_text('id,note\n001,"line1\nline2"\n2,\n',encoding='utf-8')
        dest=self.root/'csv.sqlite'
        q.snapshot(dest,csvs=[('weird"name',source)])
        r=q.execute(dest,'SELECT * FROM "weird""name" ORDER BY id')
        self.assertEqual(r['rows'],[['001','line1\nline2'],['2','']])
    def test_bad_csv(self):
        for content in ['a,A\n1,2\n','a,b\n1\n','a,b\n"bad,b\n']:
            source=self.root/'bad.csv'; source.write_text(content)
            dest=self.root/'bad.sqlite'
            with self.assertRaises((ValueError,q.csv.Error)): q.snapshot(dest,csvs=[('data',source)])
            self.assertFalse(dest.exists())
    def test_snapshot_readonly_original(self):
        before=q.filehash(self.db)
        dest=self.root/'snapshot.sqlite'
        q.snapshot(dest,database=self.db)
        self.assertEqual(q.execute(dest,'SELECT * FROM sales'),q.execute(self.db,'SELECT * FROM sales'))
        self.assertEqual(before,q.filehash(self.db))
        with self.assertRaises(ValueError): q.snapshot(dest,database=self.db)
    def test_cli(self):
        sql=self.root/'query.sql';sql.write_text('SELECT sum(amount) FROM sales')
        out=self.root/'evidence'
        self.assertEqual(q.main(['run','--db',str(self.db),'--sql',str(sql),'--out',str(out)]),0)
        self.assertEqual(q.main(['verify',str(out)]),0)
        self.assertEqual(q.main(['run','--db',str(self.db),'--sql',str(sql),'--out',str(out)]),1)
        if os.name != 'nt':
            self.assertEqual(out.stat().st_mode & 0o777,0o700)
    def test_join_alias_collision(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.executescript('CREATE TABLE l(id); CREATE TABLE r(id); INSERT INTO l VALUES (1),(1); INSERT INTO r VALUES (1),(1);')
        check = q.joincheck(self.db, 'l', 'id', 'r', 'id')
        self.assertEqual(check['predicted_inner_rows'], 4)
        self.assertEqual(check['many_to_many_keys'], 1)
    def test_profile_sqlite_prefix(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('CREATE TABLE sqliteX(id)')
        self.assertIn('sqliteX', [x['table'] for x in q.profile(self.db)])
    def test_malformed_receipt(self):
        for body in [[], None, 'text', 42]:
            (self.root/'receipt.json').write_text(json.dumps(body))
            self.assertEqual(q.main(['verify', str(self.root)]), 1)
    def test_more_readonly_boundaries(self):
        before = q.filehash(self.db)
        for sql in ["SELECT * FROM pragma_table_info('sales')", 'PRAGMA writable_schema=ON',
                    "SELECT writefile('/tmp/queryproof-no-write', 'x')", 'CREATE TEMP TABLE t(x)',
                    'WITH x AS (SELECT 1) DELETE FROM sales RETURNING *', 'REINDEX',
                    'SELECT current_timestamp', 'SELECT sqlite_version()']:
            with self.subTest(sql=sql), self.assertRaises((ValueError, sqlite3.Error)):
                q.execute(self.db, sql)
        self.assertEqual(before, q.filehash(self.db))
    def test_formula_text_is_inert_html(self):
        r = q.create(self.db, "SELECT '=HYPERLINK(\"https://example.com\")', '<img src=x onerror=alert(1)>'", include_rows=True)
        page = q.report(r)
        self.assertNotIn('<img', page)
        self.assertIn('&lt;img', page)
        self.assertIn("default-src 'none'", page)

    def bundle(self):
        r = q.create(self.db, 'SELECT sum(amount) FROM sales', include_rows=True)
        (self.root/'receipt.json').write_text(json.dumps(r))
        q.snapshot(self.root/'snapshot.sqlite', database=self.db)
        # Backup may change SQLite bytes; bind to the actual saved snapshot.
        r['snapshot_sha256'] = q.filehash(self.root/'snapshot.sqlite')
        self.save_receipt(r)
        return r
    def save_receipt(self, receipt):
        receipt['receipt_sha256'] = q.digest({k:v for k,v in receipt.items() if k != 'receipt_sha256'})
        (self.root/'receipt.json').write_text(json.dumps(receipt))
    def test_structured_valid(self):
        self.bundle()
        self.assertEqual(q.diagnose(self.root)['code'], 'VERIFIED')
    def test_missing_receipt(self):
        self.assertEqual(q.diagnose(self.root)['code'], 'RECEIPT_MISSING')
    def test_missing_sql(self):
        r=self.bundle(); del r['sql']; self.save_receipt(r)
        self.assertEqual(q.diagnose(self.root)['code'], 'SQL_MISSING')
    def test_missing_snapshot(self):
        self.bundle(); (self.root/'snapshot.sqlite').unlink()
        self.assertEqual(q.diagnose(self.root)['code'], 'SNAPSHOT_MISSING')
    def test_sqlite_version_guidance(self):
        r=self.bundle(); r['sqlite_version']='test-other'; r['environment']['sqlite_version']='test-other'; self.save_receipt(r)
        outcome=q.diagnose(self.root)
        self.assertEqual(outcome['code'], 'SQLITE_VERSION')
        self.assertIn('Changing Python alone', outcome['remedy'])
        self.assertNotIn('SELECT sum(amount) FROM sales', json.dumps(outcome))
    def test_sqlite_build_guidance(self):
        r=self.bundle(); r['environment']['sqlite_source_id']='test-other'; self.save_receipt(r)
        self.assertEqual(q.diagnose(self.root)['code'], 'SQLITE_BUILD')
    def test_python_metadata_informational(self):
        r=self.bundle(); r['environment']['python_version']='test-other'; self.save_receipt(r)
        outcome=q.diagnose(self.root)
        self.assertEqual(outcome['code'], 'VERIFIED')
        self.assertEqual(outcome['environment_notes'], ['python_version differs (informational)'])
    def test_sidecar_fails_closed(self):
        self.bundle(); (self.root/'snapshot.sqlite-wal').write_bytes(b'')
        self.assertEqual(q.diagnose(self.root)['code'], 'SNAPSHOT_SIDECAR')
    def test_difference_section(self):
        r=self.bundle(); r['result']['row_count']=100; self.save_receipt(r)
        outcome=q.diagnose(self.root)
        self.assertEqual(outcome['code'], 'EVIDENCE_DIFFERS')
        self.assertEqual(outcome['details']['sections'], ['result'])
    def test_bad_environment(self):
        r=self.bundle(); r['environment']=[]; self.save_receipt(r)
        self.assertEqual(q.diagnose(self.root)['code'], 'RECEIPT_FORMAT')
    def test_tool_version(self):
        r=self.bundle(); r['version']='test-other'; r['environment']['queryproof_version']='test-other'; self.save_receipt(r)
        self.assertEqual(q.diagnose(self.root)['code'], 'TOOL_VERSION')

    def test_missing_build_metadata_fails_closed(self):
        for field in [None, 'sqlite_source_id', 'sqlite_compile_options']:
            r=self.bundle()
            if field is None: r['environment']={}
            else: del r['environment'][field]
            self.save_receipt(r)
            self.assertEqual(q.diagnose(self.root)['code'], 'RECEIPT_FORMAT')
            (self.root/'snapshot.sqlite').unlink()
    def test_environment_cannot_add_sensitive_fields(self):
        r=self.bundle(); r['environment']['query']='PRIVATE SQL'; self.save_receipt(r)
        outcome=q.diagnose(self.root)
        self.assertEqual(outcome['code'], 'RECEIPT_FORMAT')
        self.assertNotIn('PRIVATE SQL', json.dumps(outcome))
    def test_inconsistent_environment_versions(self):
        r=self.bundle(); r['environment']['sqlite_version']='inconsistent'; self.save_receipt(r)
        self.assertEqual(q.diagnose(self.root)['code'], 'RECEIPT_FORMAT')

    def test_wal_snapshot(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute("INSERT INTO tags VALUES ('wal')")
            con.commit()
            dest=self.root/'wal.sqlite'; q.snapshot(dest,database=self.db)
            self.assertEqual(q.execute(dest,"SELECT count(*) FROM tags WHERE id='wal'")['rows'],[[1]])

if __name__=='__main__': unittest.main()
