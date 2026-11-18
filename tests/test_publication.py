"""Synthetic output publication regressions, no browser or network needed."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import queryproof as q
import queryproof_witness as w
import queryproof_groups as g

ROOT=Path(__file__).resolve().parents[1]

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.p=Path(self.t.name)
        self.csv=self.p/'data.csv';self.csv.write_text('label,value\na,1\nb,2\n')
        self.sql=self.p/'q.sql';self.sql.write_text('SELECT * FROM items ORDER BY label')

    def legacy(self,out):
        return q.main(['run','--csv','items='+str(self.csv),'--sql',str(self.sql),'--out',str(out)])

    def test_legacy_concurrent_empty_destination_never_replaced(self):
        out=self.p/'out';identity=[];original=q.verify
        def verify(*args,**kwargs):
            result=original(*args,**kwargs)
            out.mkdir();identity.append(out.stat().st_ino)
            return result
        with patch.object(q,'verify',verify):self.assertEqual(self.legacy(out),1)
        self.assertEqual(out.stat().st_ino,identity[0]);self.assertEqual(list(out.iterdir()),[])

    def test_legacy_existing_dangling_symlink_untouched(self):
        if os.name!='posix':self.skipTest('POSIX symlink')
        out=self.p/'out';out.symlink_to(self.p/'missing')
        self.assertEqual(self.legacy(out),1);self.assertTrue(out.is_symlink())

    def test_concurrent_publish_only_one_writer(self):
        source=self.p/'source';source.mkdir();(source/'evidence').write_text('synthetic')
        out=self.p/'out'
        def publish(_):
            try:q.publish_directory(source,out);return True
            except FileExistsError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(publish,range(24)))
        self.assertEqual(sum(results),1);self.assertEqual((out/'evidence').read_text(),'synthetic')

    @unittest.skipUnless(os.name=='posix','POSIX modes')
    def test_all_three_modes_create_files_private(self):
        for mask in (0,0o022):
            previous=os.umask(mask)
            try:
                legacy=self.p/f'legacy{mask}';self.assertEqual(self.legacy(legacy),0)
                spec=self.p/f'w{mask}.json';spec.write_bytes(w.canon({'schema':1,'table':'items','mode':'rows','project':['label'],'filters':[],'order':[],'limit':100,'offset':0}))
                witness=self.p/f'witness{mask}';w.create(witness,spec,csvs=[('items',self.csv)])
                grouped=self.p/f'grouped{mask}'
                gspec=self.p/f'g{mask}.json';gspec.write_bytes(w.canon({'schema':1,'table':'items','group_by':['label'],'aggregates':[{'as':'n','op':'count_all','column':None}],'filters':[]}))
                g.create(grouped,gspec,csvs=[('items',self.csv)])
                for folder in (legacy,witness,grouped):
                    self.assertEqual(folder.stat().st_mode&0o777,0o700)
                    for file in folder.iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600,file.name)
                probe=self.p/f'probe{mask}';probe.write_text('x')
                self.assertEqual(probe.stat().st_mode&0o777,0o666 & ~mask)
            finally:os.umask(previous)

    def test_private_write_exclusive_before_first_byte(self):
        original=os.fdopen;target=self.p/'receipt'
        def fdopen(fd,*a,**kw):
            if os.name=='posix':self.assertEqual(os.fstat(fd).st_mode&0o777,0o600)
            self.assertEqual(os.fstat(fd).st_size,0)
            return original(fd,*a,**kw)
        with patch.object(q.os,'fdopen',fdopen):q.private_write(target,b'private')
        with self.assertRaises(FileExistsError):q.private_write(target,b'overwrite')
        self.assertEqual(target.read_bytes(),b'private')

    def test_partial_publication_not_reused_and_verify_rejects(self):
        good=self.p/'good';self.assertEqual(self.legacy(good),0)
        out=self.p/'partial';original=q.private_write;counter=0
        def write(*args):
            nonlocal counter
            counter+=1
            if counter==2:raise OSError('synthetic disk failure')
            return original(*args)
        with patch.object(q,'private_write',write):
            with self.assertRaises(OSError):q.publish_directory(good,out)
        self.assertFalse(q.diagnose(out)['ok'])
        with self.assertRaises(FileExistsError):q.publish_directory(good,out)
        self.assertEqual(len(list(out.iterdir())),1)
