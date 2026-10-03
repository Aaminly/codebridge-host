import tempfile,unittest
from pathlib import Path
from host_paths import HostPaths

class PathChecks(unittest.TestCase):
 def test_other_home_and_existing_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp)/'Other User';paths=HostPaths.for_user(home)
   self.assertEqual(paths.base,home/'Library/Application Support/CodexMobile')
   self.assertEqual(paths.state,home/'.codex/.codex-global-state.json')
   paths.base.mkdir(parents=True);old=paths.base/'device.token';old.write_text('existing')
   paths.prepare();self.assertEqual(old.read_text(),'existing')
   self.assertEqual(paths.host.stat().st_mode&0o777,0o700)
   self.assertEqual(paths.state.exists(),False)
 def test_denied_directory(self):
  with tempfile.TemporaryDirectory() as tmp:
   paths=HostPaths.for_user(Path(tmp));paths.base.parent.mkdir(parents=True)
   paths.base.write_text('not directory')
   with self.assertRaises(OSError):paths.prepare()
if __name__=='__main__':unittest.main()
