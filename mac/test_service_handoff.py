"""Two real processes and loopback HTTP; substitutes only OS registration/vendor launch."""
import http.client,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from urllib.parse import urlsplit
from host_paths import HostPaths
from unittest.mock import patch
import host
class HandoffChecks(unittest.TestCase):
 def test_setup_transfers_to_background_without_losing_web_session(self):
  with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
   home=Path(tmp);driver=home/'driver.py'
   driver.write_text('''import asyncio,sys
from pathlib import Path
import host,desktop_integration
from host_paths import HostPaths
host.PATHS=HostPaths.for_user(Path(sys.argv[1]));desktop_integration.PATHS=host.PATHS
host.autostart=lambda enabled:None
desktop_integration.enable=lambda:None
desktop_integration.open_desktop=lambda:{'message':'isolated vendor boundary'}
host.subprocess.run=lambda *a,**kw:None
asyncio.run(host.run(open_browser=False,managed=sys.argv[2]=='managed'))
''')
   env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent)};jobs=[]
   def wait_for(check):
    for _ in range(100):
     try:
      value=check()
      if value:return value
     except (OSError,ValueError):pass
     time.sleep(.05)
    self.fail('Background handoff did not become ready')
   with patch('host.PATHS',HostPaths.for_user(home)):
    try:
     first=subprocess.Popen([sys.executable,str(driver),str(home),'foreground'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);jobs.append(first)
     url=wait_for(lambda:host.control('open').get('url'));parts=urlsplit(url)
     def request(method,path,body=None,cookie='',csrf=''):
      client=http.client.HTTPConnection(parts.hostname,parts.port,timeout=1)
      client.request(method,path,None if body is None else json.dumps(body),{'Origin':'http://'+parts.netloc,'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf})
      response=client.getresponse();data=json.loads(response.read());headers=dict(response.getheaders());status=response.status;client.close();return status,headers,data
     status,headers,data=request('POST','/api/bootstrap',{'capability':parts.fragment.split('=')[1]});self.assertEqual(status,200)
     cookie=headers['Set-Cookie'].split(';')[0];csrf=data['csrf']
     second=subprocess.Popen([sys.executable,str(driver),str(home),'managed'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);jobs.append(second)
     self.assertEqual(request('POST','/api/install',{},cookie,csrf)[0],200)
     first.wait(timeout=10)
     wait_for(lambda:request('GET','/api/status',cookie=cookie)[0]==200)
     self.assertIsNone(second.poll())
     self.assertEqual(request('POST','/api/pairings',{},cookie,'wrong')[0],403)
     self.assertEqual(host.control('status')['hostVersion'],'0.1.2')
    finally:
     for job in jobs:
      if job.poll() is None:job.terminate()
     for job in jobs:job.wait(timeout=10)
 def test_legacy_upgrade_restores_background_registration(self):
  with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
   home=Path(tmp);driver=home/'upgrade.py'
   driver.write_text("""import asyncio,sys,subprocess,time,webbrowser
from pathlib import Path
import host,desktop_integration
from host_paths import HostPaths
home=Path(sys.argv[1]);mode=sys.argv[2];host.PATHS=HostPaths.for_user(home);desktop_integration.PATHS=host.PATHS
webbrowser.open=lambda url:None
if mode=='legacy':
 host.HOST_VERSION='0.1.0'
 original=host.HostState.status
 def status(self):
  value=original(self);value.pop('hostVersion',None);return value
 host.HostState.status=status
children=[]
def autostart(enabled):
 if enabled:
  child=subprocess.Popen([sys.executable,__file__,str(home),'managed'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);children.append(child);(home/'managed-pid').write_text(str(child.pid))
  (home/'registered').write_text('yes')
host.autostart=autostart
host.subprocess.run=lambda *args,**kw:None
asyncio.run(host.run(open_browser=mode=='upgrade',managed=mode=='managed'))
""")
   env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent)};jobs=[];background=None
   with patch('host.PATHS',HostPaths.for_user(home)):
    try:
     old=subprocess.Popen([sys.executable,str(driver),str(home),'legacy'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);jobs.append(old)
     for _ in range(100):
      try:host.control('status');break
      except OSError:time.sleep(.05)
     agent=home/'Library/LaunchAgents/dev.codebridge.host-v2.plist';agent.parent.mkdir(parents=True);agent.write_text('old registry preference')
     retained=home/'Library/Application Support/CodexMobile/draft.txt';retained.write_text('retained draft')
     error=open(home/'upgrade-error','w');upgrade=subprocess.Popen([sys.executable,str(driver),str(home),'upgrade'],env=env,stdout=subprocess.DEVNULL,stderr=error);jobs.append(upgrade)
     upgrade.wait(timeout=15);error.close();self.assertEqual(upgrade.returncode,0,(home/'upgrade-error').read_text());old.wait(timeout=10)
     for _ in range(100):
      try:
       status=host.control('status')
       if status.get('serviceManaged'):break
      except OSError:pass
      time.sleep(.05)
     self.assertTrue(status['serviceManaged']);self.assertEqual(status['hostVersion'],'0.1.2')
     self.assertTrue((home/'registered').exists());self.assertEqual(retained.read_text(),'retained draft')
    finally:
     if (home/'managed-pid').exists():
      import signal
      try:os.kill(int((home/'managed-pid').read_text()),signal.SIGTERM)
      except ProcessLookupError:pass
     for job in jobs:
      if job.poll() is None:job.terminate()
     for job in jobs:job.wait(timeout=10)
if __name__=='__main__':unittest.main()
