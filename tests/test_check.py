"""Real synthetic three-format handoff tests; no network or browser."""
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
import queryproof_witness as w
import queryproof_groups as g
import queryproof_check as c


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        csv = self.p/'input.csv'; csv.write_text('label,value\na,1\na,2\nb,3\n')
        sql = self.p/'query.sql'; sql.write_text('SELECT label, CAST(value AS REAL)/2 FROM items ORDER BY label,value')
        self.bundles = {mode:self.p/mode for mode in ('query','witness','groups')}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(q.main(['run','--csv','items='+str(csv),'--sql',str(sql),'--include-rows','--out',str(self.bundles['query'])]),0)
        spec=self.p/'spec.json'
        spec.write_bytes(w.canon({'schema':1,'table':'items','mode':'rows','project':['label'],'filters':[],'order':[],'limit':100,'offset':0}))
        w.create(self.bundles['witness'],spec,csvs=[('items',csv)])
        spec.write_bytes(w.canon({'schema':1,'table':'items','group_by':['label'],'aggregates':[{'as':'n','op':'count_all','column':None}],'filters':[]}))
        g.create(self.bundles['groups'],spec,csvs=[('items',csv)])

    def test_real_three_formats(self):
        for mode, folder in self.bundles.items():
            result=c.check(folder)
            self.assertTrue(result['ok'],result);self.assertEqual(result['mode'],mode)
            self.assertFalse(result['semantic_correctness_verified']);self.assertFalse(result['authorship_verified'])
            strict=c.check(folder,strict_display=True)
            self.assertTrue(strict['ok'],strict);self.assertTrue(strict['display_verified'])

    def test_real_cli_json_and_exit(self):
        for mode,folder in self.bundles.items():
            run=subprocess.run([sys.executable,'-m','queryproof_check',str(folder),'--json'],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(json.loads(run.stdout)['ok'])
        run=subprocess.run([sys.executable,'-m','queryproof_check',str(self.p/'missing'),'--json'],capture_output=True,text=True)
        self.assertEqual(run.returncode,1);self.assertFalse(json.loads(run.stdout)['ok'])

    def test_tampered_snapshot_each_mode(self):
        for folder in self.bundles.values():
            with (folder/'snapshot.sqlite').open('ab') as f:f.write(b'changed')
            self.assertFalse(c.check(folder)['ok'])

    def test_mixed_layout_rejected(self):
        for folder in self.bundles.values():
            (folder/'foreign.json').write_text('{}')
            self.assertEqual(c.check(folder)['stage'],'layout')

    def test_no_fallback_when_format_relabelled(self):
        folder=self.bundles['query']; path=folder/'receipt.json'
        r=json.loads(path.read_text());r['format']='queryproof-witness/1';path.write_text(json.dumps(r))
        with patch.object(q,'verify',side_effect=AssertionError('must not fallback')):
            self.assertFalse(c.check(folder)['ok'])

    def test_unknown_format_no_verifier_called_or_echoed(self):
        folder=self.bundles['query'];(folder/'receipt.json').write_text('{"format":"PRIVATE-secret"}')
        with patch.object(q,'verify',side_effect=AssertionError),patch.object(w,'verify',side_effect=AssertionError),patch.object(g,'verify',side_effect=AssertionError):
            result=c.check(folder)
        self.assertEqual(result['code'],'UNSUPPORTED_FORMAT');self.assertNotIn('PRIVATE',json.dumps(result))

    def test_duplicate_key_rejected(self):
        folder=self.bundles['query'];path=folder/'receipt.json'
        raw=path.read_text();path.write_text('{"format":"queryproof/1",'+raw[1:])
        self.assertFalse(c.check(folder)['ok'])

    def test_malformed_and_oversize_receipts(self):
        path=self.bundles['query']/'receipt.json'
        for raw in (b'[]',b'null',b'not json',b'\xff',b'['*2000,b' '* (w.MAX_OUTPUT+1)):
            path.write_bytes(raw);self.assertFalse(c.check(path.parent)['ok'])

    @unittest.skipUnless(os.name=='posix','POSIX symlink support')
    def test_symlink_receipt_directory_and_snapshot_rejected(self):
        for mode,folder in self.bundles.items():
            name={'query':'receipt.json','witness':'snapshot.sqlite','groups':'report.html'}[mode]
            original=folder/name;target=self.p/(mode+'.saved');original.rename(target);original.symlink_to(target)
            self.assertFalse(c.check(folder)['ok'])
        link=self.p/'linked';link.symlink_to(self.bundles['query'],target_is_directory=True)
        self.assertFalse(c.check(link)['ok'])

    def test_legacy_html_scope_is_not_overclaimed(self):
        folder=self.bundles['query'];(folder/'report.html').write_text('untrusted display')
        result=c.check(folder);self.assertTrue(result['ok']);self.assertIn('NOT verified',result['scope'])

    def test_witness_group_html_tamper_fails(self):
        for mode in ('witness','groups'):
            folder=self.bundles[mode];(folder/'report.html').write_text('untrusted display')
            self.assertFalse(c.check(folder)['ok'])

    def test_private_exception_not_echoed(self):
        with patch.object(q,'verify',side_effect=ValueError('PRIVATE SQL data')):
            result=c.check(self.bundles['query'])
        self.assertFalse(result['ok']);self.assertNotIn('PRIVATE',json.dumps(result))

    def test_check_does_not_modify_bundle(self):
        for folder in self.bundles.values():
            before={p.name:p.read_bytes() for p in folder.iterdir()}
            self.assertTrue(c.check(folder)['ok'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})

    def test_malformed_nested_legacy_real_cli_json(self):
        folder=self.bundles['query'];path=folder/'receipt.json';original=json.loads(path.read_text())
        mutations=[
            ('key_checks',[{'table':123,'key':'PRIVATE-column'}]),
            ('key_checks',[{'table':'items','key':[]}]),
            ('key_checks',[None]),('key_checks',{}),
            ('join_checks',[{'left':['items',123],'right':['items','PRIVATE-column']}]),
            ('join_checks',[{'left':'PRIVATE-column','right':['items','label']}]),
            ('join_checks',[{'left':['items'],'right':['items','label']}]),
            ('join_checks',[None]),('join_checks',{}),
            ('sources',None),('profile',{}),('result',[]),('environment',[]),
        ]
        for field,value in mutations:
            with self.subTest(field=field,value=value):
                receipt=dict(original);receipt[field]=value
                receipt['receipt_sha256']=q.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
                path.write_text(json.dumps(receipt))
                run=subprocess.run([sys.executable,'-m','queryproof_check',str(folder),'--json'],capture_output=True,text=True)
                self.assertEqual(run.returncode,1)
                result=json.loads(run.stdout);self.assertFalse(result['ok']);self.assertEqual(result['code'],'INVALID_BUNDLE')
                self.assertEqual(run.stderr,'');self.assertNotIn('PRIVATE',run.stdout);self.assertNotIn(str(self.p),run.stdout)

    def test_unexpected_verifier_exception_fails_closed(self):
        for mode, module in (('query',q),('witness',w),('groups',g)):
            with patch.object(module,'verify',side_effect=RuntimeError('PRIVATE path')):
                result=c.check(self.bundles[mode])
                self.assertEqual(result['code'],'CHECK_FAILED');self.assertFalse(result['ok'])
                self.assertNotIn('PRIVATE',json.dumps(result))

    def test_control_interrupt_not_swallowed(self):
        with patch.object(q,'verify',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):c.check(self.bundles['query'])
