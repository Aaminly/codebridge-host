"""Background bridge with owner-authorized desktop startup and web management."""
import argparse,asyncio,fcntl,json,os,plistlib,signal,socket,subprocess,sys,threading
from pathlib import Path
from desktop_discovery import discover,probe,choose
from host_paths import PATHS
from local_console import start_console
HOST_VERSION="0.1.2"

class HostState:
 def __init__(self,expected_thread=None):
  self.expected_thread=expected_thread;self.endpoint=None;self.lock=threading.Lock();self.runtime=None;self.offers={};self.stop=None;self.restart=None;self.managed=False;self.configured=False
  self.snapshot={'connected':False,'reason':'正在检测桌面','relayReady':False,'devices':[],'pairings':[]}
 def configure(self,config):
  from device_store import DeviceStore
  from pairing import Pairings
  from v2_host import Runtime
  self.configured=True
  try:
   store=DeviceStore();identity=store.identity()
   self.runtime=Runtime(self,store,Pairings(identity['hostId'],identity['publicKey'],config['origin'],store),config['origin'])
  except (OSError,ValueError,KeyError):
   self.snapshot['connectionError']='安全连接身份或配置无法读取，尚未连接；请重新启用组件并完成系统授权'
 async def refresh(self):
  previous=self.endpoint
  results=await asyncio.gather(*(probe(e) for e in discover(PATHS.home)))
  try:
   selected=choose(results,self.expected_thread);self.endpoint=selected.endpoint
   value={'connected':True,'reason':'','version':selected.version,'loadedThreads':len(selected.loaded_thread_ids)}
  except ValueError:
   self.endpoint=None;value={'connected':False,'reason':'未发现可确认的桌面实例' if len(results)<2 else '存在多个桌面实例，尚未确认当前会话归属'}
  if self.runtime and previous is not None and self.endpoint!=previous:
   for peer in list(self.runtime.peers.values()):
    peer.cancel()
    if self.runtime.socket:await peer.close(1013,'Desktop disconnected')
   self.runtime.peers.clear()
  with self.lock:self.snapshot.update(value)
 def status(self):
  with self.lock:value=dict(self.snapshot)
  if self.runtime:
   value['pairings']=self.runtime.pairings.status();value['devices']=[{'id':d['id'],'name':d['name']} for d in self.runtime.identity['devices'].values()]
   for p in value['pairings']:
    if p['state']=='offered' and p['id'] in self.offers:p['qr']=self.offers[p['id']]
  value['hostVersion']=HOST_VERSION
  value['serviceManaged']=self.managed
  value['relayConfigured']=self.configured
  try:
   from desktop_integration import read
   value['desktopConfigured']=read().get('enabled',False)
  except (OSError,ValueError):value['desktopError']='桌面共享入口配置无法读取，请重新确认设置'
  value['autostart']=(PATHS.home/'Library/LaunchAgents/dev.codebridge.host-v2.plist').exists()
  return value
 def action(self,path,body):
  if path=='/api/desktop/enable':
   if self.endpoint is not None:return {'status':'connected','message':'桌面共享入口已连接，无需更改启动方式。'}
   from desktop_integration import enable
   result=enable();self.snapshot.pop('desktopError',None);return result
  if path=='/api/desktop/open':
   from desktop_integration import open_desktop
   return open_desktop()
  if path=='/api/install':
   from desktop_integration import enable,open_desktop
   enable();opened=open_desktop();autostart(True)
   if self.restart and not self.managed:self.restart()
   return {'status':'installed','message':'后台服务已注册，登录时自动启动；'+opened['message']}
  if path=='/api/autostart':
   if type(body.get('enabled')) is not bool:raise ValueError('Invalid login preference')
   autostart(body['enabled'])
   if self.restart and body['enabled'] and not self.managed:self.restart()
   return {'enabled':body['enabled']}
  if path=='/api/uninstall':
   if self.stop is None:raise ValueError('Host not running')
   self.stop();return {'stopping':True}
  if not self.runtime:raise ValueError('连接服务尚未就绪，未建立手机授权')
  import base64,io,qrcode
  async def action():
   if path=='/api/pairings':
    offer=await self.runtime.begin();output=io.BytesIO();qrcode.make(json.dumps(offer,separators=(',',':'))).save(output,format='PNG');self.offers={k:v for k,v in self.offers.items() if k in self.runtime.pairings.pending};self.offers[offer['pairingId']]='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode();return {'created':True}
   parts=path.split('/');return await getattr(self.runtime,parts[-1])(parts[-2])
  return asyncio.run_coroutine_threadsafe(action(),self.runtime.loop).result(timeout=15)

async def disable_component(state,stop):
 from desktop_integration import disable
 try:
  await asyncio.to_thread(disable);await asyncio.to_thread(autostart,False)
 except (OSError,ValueError,subprocess.SubprocessError):
  state.snapshot['componentError']='组件未能停用，后台仍在运行；请检查登录服务权限后重试。'
  return False
 state.snapshot.pop('componentError',None);stop.set();return True

async def run(expected_thread=None,open_browser=True,managed=False):
 PATHS.prepare();upgrading=False
 if open_browser and not managed:
  try:
   existing=control('status')
   if existing.get('hostVersion')!=HOST_VERSION:
    control('stop');upgrading=True
    for _ in range(100):
     if not (PATHS.host/'control.sock').exists():break
     await asyncio.sleep(.2)
    else:raise RuntimeError('原后台服务尚未退出，未启动第二个实例')
  except (FileNotFoundError,ConnectionRefusedError):pass
 with (PATHS.host/'run.lock').open('a') as lock:
  os.chmod(PATHS.host/'run.lock',0o600)
  for attempt in range(100 if managed or upgrading or not open_browser else 1):
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    if managed or upgrading or not open_browser:await asyncio.sleep(.2)
  else:
   if managed:raise TimeoutError('原连接组件尚未交接后台服务')
   existing=control('open' if open_browser else 'status')
   if open_browser:
    import webbrowser
    webbrowser.open(existing['url'])
   return
  control_path=PATHS.host/'control.sock';control_path.unlink(missing_ok=True)
  state=HostState(expected_thread);state.managed=managed
  if managed:
   try:
    from desktop_integration import read,open_desktop
    if read().get('enabled'):await asyncio.to_thread(open_desktop)
   except (OSError,ValueError,subprocess.SubprocessError) as error:state.snapshot['desktopError']=str(error)
  await state.refresh();console=start_console(state,handoff=PATHS.host/'console-handoff.json');stop=asyncio.Event();relay_job=None
  config_path=PATHS.host/'relay.json'
  if not config_path.exists():config_path=Path(__file__).with_name('release_relay.json')
  if config_path.exists():
   try:state.configure(json.loads(config_path.read_text()))
   except (OSError,ValueError):state.configured=True;state.snapshot['connectionError']='连接服务配置无法读取，尚未连接'
   if state.runtime:relay_job=asyncio.create_task(state.runtime.run())
  async def command(reader,writer):
   try:
    raw=await asyncio.wait_for(reader.readline(),3)
    if len(raw)>100:raise ValueError()
    operation=raw.decode().strip()
    if operation=='stop':stop.set();result={'stopped':True}
    elif operation=='status':result=state.status()
    elif operation=='handoff':
     if not state.managed:state.restart()
     result={'scheduled':not state.managed}
    elif operation=='open':
     # Each launch gets a fresh single-use bootstrap; old authenticated sessions remain valid.
     import secrets,time
     with console.lock:console.capability=secrets.token_urlsafe(32);console.bootstrap_expires=time.monotonic()+60
     result={'url':console.origin+'/#bootstrap='+console.capability}
    else:result={'error':'Unknown control command'}
    writer.write(json.dumps(result).encode()+b'\n');await writer.drain()
   except (ValueError,TimeoutError,OSError):pass
   finally:writer.close();await writer.wait_closed()
  server=await asyncio.start_unix_server(command,path=str(control_path),limit=128);control_path.chmod(0o600)
  loop=asyncio.get_running_loop()
  def disable_and_stop():
   async def disable():
    await asyncio.sleep(.25);await disable_component(state,stop)
   loop.call_soon_threadsafe(lambda:asyncio.create_task(disable()))
  def handoff():
   async def finish():
    await asyncio.sleep(.5);console.save_handoff(PATHS.host/'console-handoff.json');stop.set()
   loop.call_soon_threadsafe(lambda:asyncio.create_task(finish()))
  state.restart=handoff
  state.stop=disable_and_stop
  if not managed and (PATHS.home/'Library/LaunchAgents/dev.codebridge.host-v2.plist').exists():
   try:
    await asyncio.to_thread(autostart,True);handoff()
   except (OSError,ValueError,subprocess.SubprocessError) as error:state.snapshot['desktopError']='登录自动连接服务未能恢复：'+str(error)
  for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
  if open_browser:
   import webbrowser
   webbrowser.open(console.url)
  async def refresh():
   while not stop.is_set():
    try:await asyncio.wait_for(stop.wait(),5)
    except TimeoutError:await state.refresh()
  worker=asyncio.create_task(refresh())
  try:await stop.wait()
  finally:
   worker.cancel()
   if relay_job:relay_job.cancel()
   await asyncio.gather(*([worker,relay_job] if relay_job else [worker]),return_exceptions=True)
   server.close();await server.wait_closed();console.shutdown();control_path.unlink(missing_ok=True)
   if managed:subprocess.run(['/bin/launchctl','bootout',f'gui/{os.getuid()}/dev.codebridge.host-v2'],capture_output=True)

def control(operation):
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
  client.settimeout(5);client.connect(str(PATHS.host/'control.sock'));client.sendall(operation.encode()+b'\n')
  data=b''
  while not data.endswith(b'\n'):
   piece=client.recv(4096)
   if not piece:raise OSError('Host control disconnected')
   data+=piece
   if len(data)>16384:raise ValueError('Invalid control response')
  return json.loads(data)

async def open_management():
 import webbrowser
 PATHS.prepare();existing=None
 try:existing=control('status')
 except (FileNotFoundError,ConnectionRefusedError):pass
 if existing and existing.get('hostVersion')!=HOST_VERSION:
  control('stop');existing=None
  for _ in range(100):
   if not (PATHS.host/'control.sock').exists():break
   await asyncio.sleep(.2)
  else:raise RuntimeError('原连接组件未退出，未启动第二个服务')
 if existing is None:
  log=PATHS.host/'service.log'
  with log.open('ab') as out:
   log.chmod(0o600)
   command=[sys.executable,'run','--no-browser'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),'run','--no-browser']
   child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True)
  for _ in range(100):
   try:
    value=control('status')
    if value.get('hostVersion')==HOST_VERSION:break
   except (FileNotFoundError,ConnectionRefusedError):pass
   if child.poll() is not None and child.returncode!=0:raise RuntimeError('后台服务启动失败，请查看组件运行目录中的 service.log')
   await asyncio.sleep(.2)
  else:raise RuntimeError('后台服务未在限定时间内就绪')
 webbrowser.open(control('open')['url'])

def autostart(enabled):
 agent=PATHS.home/'Library/LaunchAgents/dev.codebridge.host-v2.plist';domain=f'gui/{os.getuid()}'
 service=domain+'/dev.codebridge.host-v2'
 if not enabled:
  # Disable future starts; the existing connection remains until explicitly stopped.
  if agent.exists():agent.unlink()
  subprocess.run(['/bin/launchctl','disable',service],check=True,capture_output=True)
  return
 if not getattr(sys,'frozen',False):raise ValueError('Autostart requires the packaged component')
 executable=Path(sys.executable).resolve()
 if not executable.is_file():raise ValueError('Component executable unavailable')
 payload={'Label':'dev.codebridge.host-v2','ProgramArguments':[str(executable),'run','--no-browser','--managed'],'RunAtLoad':True,'KeepAlive':{'UnsuccessfulExit':True},'ThrottleInterval':15}
 data=plistlib.dumps(payload);previous=agent.read_bytes() if agent.exists() else None
 agent.parent.mkdir(parents=True,exist_ok=True)
 loaded=subprocess.run(['/bin/launchctl','print',service],capture_output=True)
 if loaded.returncode not in (0,113):raise OSError('Cannot inspect background service')
 if loaded.returncode==0 and previous is not None and previous!=data:
  if b'--managed' not in previous:
   subprocess.run(['/bin/launchctl','bootout',service],check=True,capture_output=True);loaded.returncode=113
  else:raise ValueError('后台服务路径已改变，请先停用原组件，再从新安装位置打开')
 with agent.open('wb') as out:agent.chmod(0o600);out.write(data)
 try:
  subprocess.run(['/bin/launchctl','enable',service],check=True,capture_output=True)
  if loaded.returncode:subprocess.run(['/bin/launchctl','bootstrap',domain,str(agent)],check=True,capture_output=True)
  else:subprocess.run(['/bin/launchctl','kickstart',service],check=True,capture_output=True)
 except Exception:
  if previous is None:agent.unlink(missing_ok=True)
  else:agent.write_bytes(previous)
  raise

def main():
 if len(sys.argv)>1 and sys.argv[1] not in ('open','run','status','stop','uninstall','enable-autostart','disable-autostart','--help','-h'):
  from desktop_connector import proxy
  asyncio.run(proxy(sys.argv[1:]));return
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',nargs='?',default='open',choices=['open','run','status','stop','uninstall','enable-autostart','disable-autostart'])
 parser.add_argument('--managed',action='store_true');parser.add_argument('--thread-id');parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
 if args.command=='open':asyncio.run(open_management())
 elif args.command=='run':asyncio.run(run(args.thread_id,not args.no_browser,args.managed))
 elif args.command in ('status','stop'):print(json.dumps(control(args.command),ensure_ascii=False))
 elif args.command=='uninstall':
  from desktop_integration import disable
  disable()
  autostart(False)
  if (PATHS.host/'control.sock').is_socket():control('stop')
  # Credentials, chats, original bridge and application files are deliberately retained.
 elif args.command.endswith('autostart'):
  enabled=args.command=='enable-autostart';autostart(enabled)
  if enabled and (PATHS.host/'control.sock').exists():control('handoff')
if __name__=='__main__':main()
