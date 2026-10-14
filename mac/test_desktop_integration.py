import json,plistlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from host import HostState

class DesktopSetupChecks(unittest.TestCase):
 def test_setup_works_before_relay_authorization_and_never_closes_codex(self):
  self.check_setup("Codex.app")

 def test_setup_recognizes_official_chatgpt_named_codex(self):
  self.check_setup("ChatGPT.app")

 def test_unrelated_system_chatgpt_does_not_block_user_codex(self):
  self.check_setup("Codex.app",unrelated_system_chatgpt=True)

 def check_setup(self,name,unrelated_system_chatgpt=False):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp)
   if unrelated_system_chatgpt:
    unrelated=home/'SystemApplications/ChatGPT.app/Contents';unrelated.mkdir(parents=True)
    (unrelated/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.openai.chat'}))
   app=home/'Applications'/name;cli=app/'Contents/Resources/codex';cli.parent.mkdir(parents=True);cli.write_text('native CLI');cli.chmod(0o755)
   (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.openai.codex'}))
   executable=home/'Applications/CodeBridge Host.app/Contents/MacOS/CodeBridge Host';executable.parent.mkdir(parents=True);executable.write_text('host');executable.chmod(0o755)
   paths=SimpleNamespace(home=home,host=home/'Library/Application Support/CodexMobile/host-v2')
   commands=[]
   def run(args,**kwargs):
    commands.append(args)
    active=any(cmd[:2]==['/bin/launchctl','setenv'] for cmd in commands)
    return SimpleNamespace(returncode=0,stdout=str(executable.resolve()) if args[:2]==['/bin/launchctl','getenv'] and active else '',stderr='TeamIdentifier=2DC432GLL2\n')
   with patch('desktop_integration.Path',side_effect=lambda value:home/'SystemApplications' if value=='/Applications' else Path(value)),patch('host.PATHS',paths),patch('desktop_integration.PATHS',paths),patch('sys.frozen',True,create=True),patch('sys.executable',str(executable)),patch('subprocess.run',side_effect=run):
    try:
     state=HostState();result=state.action('/api/desktop/enable',{});state.action('/api/desktop/open',{})
    except ValueError:self.fail('First installation cannot configure the real desktop before relay pairing')
   self.assertEqual(result['status'],'configured')
   self.assertEqual(json.loads((paths.host/'desktop.json').read_text())['cli'],str(cli.resolve()))
   self.assertIn(['/usr/bin/open','-a',str(app.resolve()),'--env','CODEX_CLI_PATH='+str(executable.resolve())],commands)
   self.assertFalse(any(args[0]=='/bin/launchctl' for args in commands))
   self.assertFalse(any(any(word in ('pkill','kill','restart','quit') for word in args) for args in commands))

if __name__=='__main__':unittest.main()
