import plistlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import host
class ServiceInstallChecks(unittest.TestCase):
 def test_install_is_idempotent_and_registers_managed_background_service(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);exe=home/'Applications/CodeBridge Host.app/Contents/MacOS/CodeBridge Host';exe.parent.mkdir(parents=True);exe.write_text('host')
   paths=SimpleNamespace(home=home,host=home/'Library/Application Support/CodexMobile/host-v2')
   commands=[]
   def run(args,**kwargs):
    commands.append(args)
    return SimpleNamespace(returncode=0 if args[1]!='print' or any(x[1]=='bootstrap' for x in commands) else 113,stdout='',stderr='')
   with patch('host.PATHS',paths),patch('sys.frozen',True,create=True),patch('sys.executable',str(exe)),patch('subprocess.run',side_effect=run):
    host.autostart(True);host.autostart(True)
   plist=plistlib.loads((home/'Library/LaunchAgents/dev.codebridge.host-v2.plist').read_bytes())
   self.assertIn('--managed',plist['ProgramArguments'])
   self.assertTrue(plist['KeepAlive']['UnsuccessfulExit'])
   self.assertEqual(sum(x[1]=='bootstrap' for x in commands),1)
 def test_failed_registration_does_not_leave_success_preference(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);exe=home/'Applications/host';exe.parent.mkdir(parents=True);exe.write_text('host')
   with patch('host.PATHS',SimpleNamespace(home=home,host=home/'host')),patch('sys.frozen',True,create=True),patch('sys.executable',str(exe)),patch('subprocess.run',side_effect=OSError('failed')):
    with self.assertRaises(OSError):host.autostart(True)
   self.assertFalse((home/'Library/LaunchAgents/dev.codebridge.host-v2.plist').exists())
 def test_setup_starts_shared_desktop_then_hands_off_without_closing_codex(self):
  state=host.HostState();calls=[];state.restart=lambda:calls.append('handoff')
  with patch('desktop_integration.enable',side_effect=lambda:calls.append('enable')),patch('host.autostart',side_effect=lambda x:calls.append('service')),patch('desktop_integration.open_desktop',return_value={'message':'started'}):
   self.assertEqual(state.action('/api/install',{})['status'],'installed')
  self.assertEqual(calls,['enable','service','handoff'])
 def test_failed_desktop_open_never_starts_handoff_or_job(self):
  state=host.HostState()
  with patch('desktop_integration.enable'),patch('host.autostart') as service,patch('desktop_integration.open_desktop',side_effect=OSError('vendor launch failed')),patch.object(state,'restart') as handoff:
   with self.assertRaises(OSError):state.action('/api/install',{})
   service.assert_not_called();handoff.assert_not_called()
 def test_existing_job_is_started_without_killing_running_instance(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);exe=home/'Applications/host';exe.parent.mkdir(parents=True);exe.write_text('host')
   commands=[]
   def run(args,**kwargs):commands.append(args);return SimpleNamespace(returncode=0,stdout='',stderr='')
   with patch('host.PATHS',SimpleNamespace(home=home,host=home/'host')),patch('sys.frozen',True,create=True),patch('sys.executable',str(exe)),patch('subprocess.run',side_effect=run):host.autostart(True)
   self.assertTrue(any(args[1]=='kickstart' for args in commands));self.assertFalse(any('-k' in args for args in commands))
if __name__=='__main__':unittest.main()
