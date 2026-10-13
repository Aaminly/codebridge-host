# Removing idempotency or reporting success before desktop registration must fail here.
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import project_creation as p
class CreationChecks(unittest.TestCase):
 def test_waits_for_desktop_and_never_resubmits(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp).resolve();folder=base/'folder';folder.mkdir();state=base/'desktop.json';state.write_text('{"local-projects":{}}')
   with patch('desktop_integration.read',return_value={'enabled':True,'app':'/Applications/Codex.app'}),patch.object(p,'STATE',state),patch.object(p,'OPERATIONS',base/'operations.json'),patch.object(p,'TRUST_POLICY',base/'policy.json'),patch('subprocess.run') as launch:
    launch.return_value.returncode=0
    first=p.create({'path':str(folder),'requestId':'test-operation-1'})
    self.assertEqual(first['status'],'pending')
    self.assertIn('确认文件夹',first['message'])
    with patch('project_creation.time.time',return_value=first['createdAt']+121):
     self.assertEqual(p.status({'requestId':'test-operation-1'})['status'],'unconfirmed')
    self.assertEqual(p.create({'path':str(folder),'requestId':'test-operation-1'})['status'],'pending')
    duplicate=p.create({'path':str(folder),'requestId':'test-operation-3'})
    self.assertEqual(duplicate['requestId'],'test-operation-3')
    self.assertEqual(launch.call_args.args[0][2],'/Applications/Codex.app')
    self.assertEqual(launch.call_count,1)
    state.write_text(json.dumps({'local-projects':{'real-desktop-id':{'id':'real-desktop-id','name':'folder','rootPaths':[str(folder)]}}}))
    self.assertEqual(p.status({'requestId':'test-operation-1'})['project']['id'],'real-desktop-id')
    self.assertEqual(p.status({'requestId':'test-operation-1'})['status'],'ready')
    self.assertEqual(p.create({'path':str(folder),'requestId':'test-operation-4'})['status'],'ready')
    self.assertEqual(launch.call_count,1)
    with self.assertRaises(ValueError):p.create({'path':str(base),'requestId':'test-operation-1'})
 def test_trust_requires_saved_owner_policy(self):
  with tempfile.TemporaryDirectory() as tmp:
   policy=Path(tmp)/'policy.json'
   with patch.object(p,'TRUST_POLICY',policy),patch.object(p,'_trust_selected_folder') as trust:
    p.trust_selected_folder(Path(tmp));trust.assert_not_called()
    policy.write_text('{"trustSelectedFolders": true}')
    p.trust_selected_folder(Path(tmp));trust.assert_called_once_with(Path(tmp))
 def test_trust_failure_does_not_dispatch_or_save_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp).resolve();operations=folder/'operations.json'
   with patch.object(p,'OPERATIONS',operations),patch.object(p,'trust_selected_folder',side_effect=RuntimeError('trust failed')),patch('subprocess.run') as launch:
    with self.assertRaises(RuntimeError):p.create({'path':str(folder),'requestId':'test-trust-failure'})
    launch.assert_not_called();self.assertFalse(operations.exists())
 def test_rejects_files_and_relative_paths(self):
  with self.assertRaises(ValueError):p.folders({'path':'relative'})
  with self.assertRaises(ValueError):p.create({'path':'/etc/hosts','requestId':'test-operation-2'})
if __name__=='__main__':unittest.main()
