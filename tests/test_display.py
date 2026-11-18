"""Original synthetic SQLite display checks; no browser or external requests."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import queryproof as q
import queryproof_check as c
import queryproof_witness as w


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        csv = self.root / 'input.csv'
        csv.write_text('name,value\nAlice,42\n<script>bad</script>,7\n', encoding='utf8')
        sql = self.root / 'query.sql'
        sql.write_text('SELECT name,value FROM items ORDER BY value', encoding='utf8')
        self.bundle = self.root / 'bundle'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(q.main(['run','--csv','items='+str(csv),'--sql',str(sql),
                                     '--include-rows','--out',str(self.bundle)]), 0)
        self.html = self.bundle / 'report.html'
        self.original = self.html.read_bytes()

    def test_old_generated_bundle_exact_and_no_mutation(self):
        before = {p.name:p.read_bytes() for p in self.bundle.iterdir()}
        result = c.check(self.bundle, strict_display=True)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['display_verified'])
        self.assertFalse(result['semantic_correctness_verified'])
        self.assertFalse(result['authorship_verified'])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.bundle.iterdir()})

    def test_tampered_numeric_script_link_and_csp(self):
        mutations = [self.original.replace(b'<td>42</td>', b'<td>99</td>', 1),
                     self.original+b'<script>fetch("https://example.invalid/")</script>',
                     self.original+b'<img src="https://example.invalid/private">',
                     self.original+b'<a href="https://example.invalid/">source</a>',
                     self.original.replace(b"default-src 'none'", b'default-src *'),
                     b'', self.original+b'\n', self.original.replace(b'\n',b'\r\n')]
        for changed in mutations:
            with self.subTest(length=len(changed)):
                self.assertNotEqual(changed,self.original)
                self.html.write_bytes(changed)
                self.assertTrue(c.check(self.bundle)['ok'])
                self.assertIn('NOT verified',c.check(self.bundle)['scope'])
                result = c.check(self.bundle, strict_display=True)
                self.assertFalse(result['ok']); self.assertEqual(result['code'],'DISPLAY_MISMATCH')
                self.assertNotIn('private',json.dumps(result))

    def test_escaped_source_is_data_not_script(self):
        self.assertIn(b'&lt;script&gt;bad&lt;/script&gt;',self.original)
        self.assertNotIn(b'<script>bad</script>',self.original)
        self.assertTrue(c.check(self.bundle,strict_display=True)['ok'])

    def test_unknown_version_and_format_fail_closed(self):
        p = self.bundle/'receipt.json'; original=json.loads(p.read_text())
        for field,value in [('version','99'),('format','queryproof/99')]:
            r=dict(original); r[field]=value
            if field=='version':
                r['environment']=dict(r['environment'],queryproof_version=value)
            r['receipt_sha256']=q.digest({k:v for k,v in r.items() if k!='receipt_sha256'})
            p.write_text(json.dumps(r),encoding='utf8')
            self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])

    def test_html_missing_directory_and_extra_members(self):
        self.html.unlink()
        self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])
        self.html.mkdir()
        self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])
        self.html.rmdir();self.html.write_bytes(self.original)
        (self.bundle/'extra').write_text('private')
        self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])

    @unittest.skipUnless(os.name=='posix','POSIX symlink/FIFO checks')
    def test_html_symlink_and_fifo_rejected_without_blocking(self):
        self.html.unlink(); self.html.symlink_to(self.root/'outside')
        self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])
        self.html.unlink();os.mkfifo(self.html)
        result=subprocess.run([sys.executable,'-m','queryproof_check',str(self.bundle),
                               '--strict-display','--json'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,1);self.assertFalse(json.loads(result.stdout)['ok'])

    def test_resource_bounds(self):
        with self.html.open('wb') as f:f.truncate(w.MAX_OUTPUT+1)
        self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])
        self.html.write_bytes(self.original)
        with patch.object(q,'report',return_value='x'*(w.MAX_OUTPUT+1)):
            self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])

    def test_actual_cli_and_no_raw_contents(self):
        command=[sys.executable,'-m','queryproof_check',str(self.bundle),'--strict-display','--json']
        good=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertTrue(json.loads(good.stdout)['display_verified'])
        self.html.write_text('PRIVATE_SENTINEL',encoding='utf8')
        bad=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(bad.returncode,1);self.assertEqual(bad.stderr,'')
        self.assertNotIn('PRIVATE_SENTINEL',bad.stdout);self.assertNotIn(str(self.root),bad.stdout)

    def test_strict_policy_type_and_private_renderer_error(self):
        self.assertFalse(c.check(self.bundle,strict_display=1)['ok'])
        with patch.object(q,'report',side_effect=ValueError('PRIVATE_SENTINEL')):
            result=c.check(self.bundle,strict_display=True)
            self.assertFalse(result['ok']);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(result))

    def test_data_failure_precedes_render(self):
        with (self.bundle/'snapshot.sqlite').open('ab') as f:f.write(b'changed')
        with patch.object(q,'report',side_effect=AssertionError('must not render')) as render:
            self.assertFalse(c.check(self.bundle,strict_display=True)['ok'])
            render.assert_not_called()

    def test_nested_numeric_type_changes_rejected_even_with_matching_html(self):
        # Real SQL contains integer, real, and signed zero; no DB changes.
        receipt_path=self.bundle/'receipt.json'
        original=q.create(self.bundle/'snapshot.sqlite',
                          'SELECT 1 AS n, 1.0 AS r, -0.0 AS z FROM items ORDER BY value',
                          keys=[('items','name')],
                          joins=[('items','name','items','name')],include_rows=True)
        changes=[(('result','rows',0,0),True),
                 (('result','rows',0,0),1.0),
                 (('result','rows',0,1),1),
                 (('result','rows',0,2),0.0),
                 (('result','row_count'),2.0),
                 (('profile',0,'rows'),2.0),
                 (('profile',0,'columns',0,'nulls'),False),
                 (('key_checks',0,'rows'),2.0),
                 (('key_checks',0,'nulls'),False),
                 (('join_checks',0,'many_to_many_keys'),False),
                 (('limits','query_seconds'),2.0)]
        for path,value in changes:
            with self.subTest(path=path,value=value):
                receipt=json.loads(json.dumps(original))
                node=receipt
                for key in path[:-1]:node=node[key]
                node[path[-1]]=value
                receipt['receipt_sha256']=q.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
                receipt_path.write_bytes(q.canonical(receipt))
                self.html.write_bytes(q.report(json.loads((self.bundle/'receipt.json').read_bytes())).encode('utf8'))
                self.assertTrue(c.check(self.bundle)['ok']) # old behavior unchanged
                result=c.check(self.bundle,strict_display=True)
                self.assertFalse(result['ok'])
                self.assertEqual(result['code'],'TYPED_EVIDENCE_MISMATCH')
                run=subprocess.run([sys.executable,'-m','queryproof_check',str(self.bundle),
                                    '--strict-display','--json'],capture_output=True,text=True)
                self.assertEqual(run.returncode,1,run.stdout)
                self.assertEqual(json.loads(run.stdout)['code'],'TYPED_EVIDENCE_MISMATCH')
        # Real int/real/signed-zero values themselves are supported.
        receipt_path.write_bytes(q.canonical(original))
        self.html.write_bytes(q.report(json.loads(receipt_path.read_bytes())).encode('utf8'))
        self.assertTrue(c.check(self.bundle,strict_display=True)['ok'])

    def test_recorded_environment_remains_informational(self):
        path=self.bundle/'receipt.json';receipt=json.loads(path.read_text())
        receipt['environment']['os']='synthetic other OS'
        receipt['receipt_sha256']=q.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        path.write_bytes(q.canonical(receipt))
        self.html.write_bytes(q.report(json.loads((self.bundle/'receipt.json').read_bytes())).encode('utf8'))
        self.assertTrue(c.check(self.bundle,strict_display=True)['ok'])
