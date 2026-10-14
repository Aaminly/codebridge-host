import json,plistlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import package_host

class PackageChecks(unittest.TestCase):
 def test_default_package_contains_production_relay_and_version(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'mac';root.mkdir();(root/'web').mkdir()
   destination=Path(tmp)/'qa/host-build'
   commands=[];components=[]
   def build(args,**kwargs):
    commands.append(args)
    if args[0]=='/usr/bin/pkgbuild' and '--component-plist' in args:components.extend(plistlib.loads(Path(args[args.index('--component-plist')+1]).read_bytes()))
    if 'PyInstaller' in args:
     info=destination/'dist/CodeBridge Host.app/Contents/Info.plist';info.parent.mkdir(parents=True)
     info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'dev.codebridge.host'}))
     binary=info.parent/'MacOS/CodeBridge Host';binary.parent.mkdir();binary.write_text('test bundled service')
   with patch.object(package_host,'__file__',str(root/'package_host.py')),patch('sys.argv',['package_host.py']),patch.object(package_host.subprocess,'run',side_effect=build):package_host.main()
   config=destination/'release_relay.json'
   self.assertTrue(config.is_file(),'A normal Mac package has no production pairing service')
   self.assertEqual(json.loads(config.read_text()),{'origin':'https://aly-codex-mobile.pages.dev'})
   info=plistlib.loads((destination/'dist/CodeBridge Host.app/Contents/Info.plist').read_bytes())
   self.assertEqual(info['CFBundleShortVersionString'],'0.1.2')
   self.assertTrue(any(args[0]=='/usr/bin/pkgbuild' and '/Applications' in args for args in commands))
   self.assertEqual(len(components),1)
   self.assertEqual(components[0]['RootRelativeBundlePath'],'CodeBridge Host.app')
   self.assertFalse(components[0]['BundleIsRelocatable'])

if __name__=='__main__':unittest.main()
