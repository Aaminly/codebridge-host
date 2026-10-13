"""Transparent stdio adapter only for the owner's selected, signed desktop app."""
import asyncio,fcntl,json,os,subprocess,sys
from pathlib import Path
from websockets.asyncio.client import unix_connect
from host_paths import PATHS
from desktop_integration import read,app_cli

def parent_app():
 pid=os.getppid()
 for _ in range(8):
  result=subprocess.run(['/bin/ps','-p',str(pid),'-o','ppid=','-o','comm='],capture_output=True,text=True)
  fields=result.stdout.strip().split(None,1)
  if len(fields)!=2:return None
  pid=int(fields[0]);parts=Path(fields[1]).parts
  for i,part in enumerate(parts):
   if part.endswith('.app'):return Path(*parts[:i+1]).resolve()
  if pid<=1:return None
 return None

async def available(socket):
 try:
  async with unix_connect(str(socket),uri='ws://localhost/rpc',open_timeout=1):return True
 except (OSError,TimeoutError):return False

async def proxy(args):
 value=read();parent=parent_app()
 if not value:raise ValueError('码桥桌面共享入口尚未配置')
 # Other OpenAI apps keep their own bundled CLI and never join the selected server.
 cli=app_cli(parent) if parent and str(parent)!=value['app'] else Path(value['cli'])
 if not value.get('enabled') or parent is None or str(parent)!=value['app'] or 'app-server' not in args or any(x in args for x in ('proxy','daemon','generate-ts','generate-json-schema')):
  os.execv(str(cli),[str(cli),*args])
 if app_cli(parent)!=cli:raise ValueError('Codex 原生程序已改变，请重新确认共享入口')
 base=PATHS.base;base.mkdir(parents=True,exist_ok=True,mode=0o700);base.chmod(0o700);socket=base/'desktop.sock'
 with (base/'startup.lock').open('a') as lock:
  os.chmod(base/'startup.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
  if not await available(socket):
   clean=list(args)
   if '--stdio' in clean:clean.remove('--stdio')
   if '--listen' in clean:
    i=clean.index('--listen');del clean[i:i+2]
   log=os.open(base/'server.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
   try:server=subprocess.Popen([str(cli),*clean,'--listen','unix://'+str(socket)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
   finally:os.close(log)
   for _ in range(100):
    if await available(socket):break
    if server.poll() is not None:raise RuntimeError('Codex 桌面服务启动失败')
    await asyncio.sleep(.1)
   else:raise RuntimeError('Codex 桌面共享入口未就绪')
  fcntl.flock(lock,fcntl.LOCK_UN)
 async with unix_connect(str(socket),uri='ws://localhost/rpc',max_size=32*1024*1024) as ws:
  async def outbound():
   while True:
    line=await asyncio.to_thread(sys.stdin.buffer.readline)
    if not line:return
    raw=line.decode().rstrip('\n')
    await ws.send(raw)
    try:initialized=json.loads(raw).get('method')=='initialized'
    except (ValueError,AttributeError):initialized=False
    if initialized:
     marker=base/'desktop-owner.json';temporary=marker.with_suffix('.tmp')
     with temporary.open('w') as out:
      temporary.chmod(0o600);json.dump({'pid':os.getpid(),'parentPid':os.getppid(),'app':str(parent)},out)
     temporary.replace(marker)
  async def inbound():
   async for message in ws:sys.stdout.write(message+'\n');sys.stdout.flush()
  jobs=[asyncio.create_task(outbound()),asyncio.create_task(inbound())]
  try:
   done,_=await asyncio.wait(jobs,return_when=asyncio.FIRST_COMPLETED)
   for job in done:job.result()
  finally:
   for job in jobs:job.cancel()
   await asyncio.gather(*jobs,return_exceptions=True)
