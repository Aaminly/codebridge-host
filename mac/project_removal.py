"""Durable empty-project removal, executed only while the desktop is closed."""
import asyncio,json,re,sqlite3,threading,time,sys
from pathlib import Path
from host_paths import PATHS
from project_registration import atomic_write,desktop_running
STATE=PATHS.state
BASE=PATHS.base
QUEUE=BASE/'project-removals.json'
CLI='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
_lock=threading.Lock()
def read_queue():return json.loads(QUEUE.read_text()) if QUEUE.exists() else {}
def save_queue(q):atomic_write(QUEUE,json.dumps(q,ensure_ascii=False).encode())
def validate(state,pid):
 p=state.get('local-projects',{}).get(pid)
 if p is None:raise ValueError('项目已不存在，请刷新列表')
 if any(v.get('projectId')==pid for v in state.get('thread-project-assignments',{}).values()):raise ValueError('仅支持移除空项目，请先处理项目中的聊天（包括归档聊天）')
 mappings=state.get('app-server-project-id-by-legacy-project-id-by-host',{})
 sid=mappings.get('local:'+str(Path.home()/'.codex'),{}).get(pid)
 if not isinstance(sid,str) or not sid:raise ValueError('无法确认真实服务项目 ID，未执行移除')
 with sqlite3.connect('file:'+str(Path.home()/'.codex/state_5.sqlite')+'?mode=ro',uri=True) as db:
  if db.execute('select 1 from threads where project_id=? limit 1',(sid,)).fetchone():raise ValueError('项目包含聊天（包括归档聊天），未执行移除')
  for root in p.get('rootPaths',[]):
   if db.execute("select 1 from threads where (project_id is null or project_id='') and (cwd=? or substr(cwd,1,?)=?) limit 1",(root,len(root.rstrip('/')+'/'),root.rstrip('/')+'/')).fetchone():raise ValueError('项目目录存在未分配聊天，不能作为空项目移除')
 return p,sid

def request(params):
 pid=params.get('projectId');key=params.get('requestId')
 if not isinstance(pid,str) or not pid or len(pid)>100:raise ValueError('项目标识无效')
 if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9-]{8,80}',key):raise ValueError('移除请求标识无效')
 with _lock:
  q=read_queue()
  if key in q:
   if q[key]['projectId']!=pid:raise ValueError('不能更换同一请求的项目')
   return q[key]
  existing=next((v for v in q.values() if v['projectId']==pid and v['status'] in ('pending','verifying')),None)
  if existing:return existing
  p,sid=validate(json.loads(STATE.read_text()),pid)
  op={'requestId':key,'projectId':pid,'serverId':sid,'name':p['name'],'status':'pending','message':'等待 Mac 上 Codex 正常退出后移除；文件夹保留','createdAt':time.time()}
  q[key]=op;save_queue(q);return op

def statuses(params=None):
 with _lock:return {'operations':list(read_queue().values())}

async def delete_server(sid):
 proc=await asyncio.create_subprocess_exec(CLI,'app-server',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
 async def rpc(i,method,params):
  proc.stdin.write((json.dumps({'id':i,'method':method,'params':params})+'\n').encode());await proc.stdin.drain()
  while True:
   line=await asyncio.wait_for(proc.stdout.readline(),20)
   if not line:raise RuntimeError('项目服务意外退出')
   response=json.loads(line)
   if response.get('id')==i:return response
 try:
  r=await rpc(1,'initialize',{'clientInfo':{'name':'mobile-project-removal','version':'1'},'capabilities':{'experimentalApi':True}})
  if 'error' in r:raise RuntimeError('项目服务初始化失败')
  r=await rpc(2,'project/read',{'projectId':sid})
  if 'error' in r:
   if 'project not found:' not in r['error'].get('message',''):raise RuntimeError('无法确认项目存在状态')
   return
  r=await rpc(3,'project/delete',{'projectId':sid})
  if 'error' in r:raise RuntimeError('真实项目删除失败')
  r=await rpc(4,'project/read',{'projectId':sid})
  if 'error' not in r or 'project not found:' not in r['error'].get('message',''):raise RuntimeError('真实项目删除未确认')
 finally:
  if proc.returncode is None:proc.terminate()
  await proc.wait()

def clear_registration(state,pid):
 # Preserve all chats and files; validation rejects even archived assignments.
 result=json.loads(json.dumps(state))
 result.get('local-projects',{}).pop(pid,None)
 for key in ('project-order','pinned-project-ids'):result[key]=[v for v in result.get(key,[]) if v!=pid]
 for key in ('project-appearances','project-files','sidebar-project-thread-orders'):result.get(key,{}).pop(pid,None)
 for mapping in result.get('app-server-project-id-by-legacy-project-id-by-host',{}).values():mapping.pop(pid,None)
 if isinstance(result.get('selected-project'),dict) and result['selected-project'].get('projectId')==pid:result.pop('selected-project',None)
 return result

async def process_once(running=desktop_running,delete=delete_server):
 if running():return
 with _lock:q=read_queue()
 for key,op in q.items():
  if op['status'] not in ('pending','verifying'):continue
  try:
   if running():return
   original=STATE.read_bytes();state=json.loads(original)
   if op['status']=='verifying' and op['projectId'] not in state.get('local-projects',{}):
    if running():op.update(status='ready',message='项目已移除，文件夹保留')
    continue
   p,sid=validate(state,op['projectId'])
   if sid!=op['serverId']:raise ValueError('项目映射已变化，移除停止')
   backup=STATE.with_name(STATE.name+'.remove-backup-'+key)
   if not backup.exists():atomic_write(backup,original)
   await delete(sid)
   if running() or STATE.read_bytes()!=original:raise RuntimeError('桌面重新启动或登记发生变化，未覆盖登记；请检查 Mac 项目状态')
   atomic_write(STATE,json.dumps(clear_registration(state,op['projectId']),ensure_ascii=False).encode())
   op.update(status='verifying',message='已移除，等待 Codex 再次启动确认')
  except (OSError,ValueError,RuntimeError,TimeoutError,sqlite3.Error) as e:op.update(status='error',message=str(e))
  with _lock:
   latest=read_queue();latest[key]=op;save_queue(latest)
 # Confirm only after the desktop has loaded its registration again.

async def confirmed_missing(sid):
 from websockets.asyncio.client import unix_connect
 async with unix_connect(str(BASE/'desktop.sock'),uri='ws://localhost/') as ws:
  async def rpc(i,method,params):
   await ws.send(json.dumps({'id':i,'method':method,'params':params}))
   while True:
    r=json.loads(await asyncio.wait_for(ws.recv(),10))
    if r.get('id')==i:return r
  r=await rpc(1,'initialize',{'clientInfo':{'name':'mobile-removal-confirm','version':'1'},'capabilities':{'experimentalApi':True}})
  if 'error' in r:return False
  r=await rpc(2,'project/read',{'projectId':sid})
  return 'error' in r and 'project not found:' in r['error'].get('message','')

async def worker():
 desktop_started=None
 while True:
  try:
   if desktop_running():
    if desktop_started is None:desktop_started=time.monotonic()
    if time.monotonic()-desktop_started<15:
     await asyncio.sleep(3);continue
    with _lock:q=read_queue()
    for key,op in q.items():
     if op['status']!='verifying':continue
     state=json.loads(STATE.read_text())
     if op['projectId'] in state.get('local-projects',{}):op.update(status='error',message='桌面重新登记了项目，移除尚未完成')
     elif await confirmed_missing(op['serverId']):op.update(status='ready',message='项目已移除，文件夹保留')
     else:continue
     with _lock:
      latest=read_queue();latest[key]=op;save_queue(latest)
   else:
    desktop_started=None
    await process_once()
  except Exception as e:print("Project removal check deferred: "+type(e).__name__,file=sys.stderr) # Retry without logging paths, tokens or false success.
  await asyncio.sleep(3)
