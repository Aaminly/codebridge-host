"""Authenticated folder picker; real project creation via macOS open-document event."""
import asyncio,json,os,re,subprocess,threading,time
from pathlib import Path
from host_paths import PATHS
STATE=PATHS.state
OPERATIONS=PATHS.base/'project-operations.json'
TRUST_POLICY=OPERATIONS.with_name('folder-trust-policy.json')
_lock=threading.Lock()
async def _trust_selected_folder(path):
 from websockets.asyncio.client import unix_connect
 async with unix_connect(str(OPERATIONS.parent/'desktop.sock'),uri='ws://localhost/',max_size=32*1024*1024) as ws:
  async def rpc(i,method,params):
   await ws.send(json.dumps({'id':i,'method':method,'params':params}))
   while True:
    message=json.loads(await asyncio.wait_for(ws.recv(),20))
    if message.get('id')==i:
     if 'error' in message:raise RuntimeError('桌面未能保存文件夹信任设置')
     return message['result']
  await rpc(1,'initialize',{'clientInfo':{'name':'codebridge_folder_trust','version':'1'},'capabilities':{'experimentalApi':True}})
  await ws.send('{"method":"initialized"}')
  current=await rpc(2,'config/read',{'includeLayers':True})
  if current.get('config',{}).get('projects',{}).get(str(path),{}).get('trust_level')=='trusted':return
  layer=next((x for x in current.get('layers',[]) if x.get('name',{}).get('type')=='user'),None)
  if layer is None:raise RuntimeError('没有可写的用户配置层，未创建项目')
  result=await rpc(3,'config/batchWrite',{'edits':[{'keyPath':'projects.'+json.dumps(str(path),ensure_ascii=False)+'.trust_level','value':'trusted','mergeStrategy':'replace'}],'expectedVersion':layer.get('version'),'filePath':None})
  if result.get('status')!='ok':raise RuntimeError('文件夹信任设置未生效，未创建项目')
  verified=await rpc(4,'config/read',{'includeLayers':False})
  if verified.get('config',{}).get('projects',{}).get(str(path),{}).get('trust_level')!='trusted':raise RuntimeError('信任设置被其他配置覆盖，未创建项目')
def trust_selected_folder(path):
 if TRUST_POLICY.exists() and json.loads(TRUST_POLICY.read_text()).get('trustSelectedFolders') is True:
  from websockets.exceptions import WebSocketException
  try:asyncio.run(_trust_selected_folder(path));return True
  except (OSError,TimeoutError,WebSocketException) as e:raise RuntimeError('电脑连接中断，文件夹信任未确认，未创建项目') from e

def directory(value):
 if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('请选择 Mac 的绝对文件夹路径')
 path=Path(value).resolve(strict=True)
 if not path.is_dir():raise ValueError('所选路径不是文件夹')
 return path
def folders(params):
 path=directory(params.get('path') or str(Path.home()))
 entries=sorted((x for x in path.iterdir() if not x.name.startswith('.') and x.is_dir()),key=lambda x:x.name.casefold())
 return {'path':str(path),'parent':str(path.parent),'folders':[{'name':x.name,'path':str(x)} for x in entries]}
def _read():return json.loads(OPERATIONS.read_text()) if OPERATIONS.exists() else {}
def _save(data):
 OPERATIONS.parent.mkdir(parents=True,exist_ok=True)
 temp=OPERATIONS.with_suffix('.tmp');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
 os.replace(temp,OPERATIONS)
def _status(operation):
 projects=json.loads(STATE.read_text()).get('local-projects',{})
 found=next((p for p in projects.values() if operation['path'] in p.get('rootPaths',[])),None)
 if found:return {**operation,'status':'ready','project':found}
 if operation.get('status')=='error':return operation
 if time.time()-operation['createdAt']>120:return {**operation,'status':'unconfirmed','message':'桌面尚未确认创建。请检查 Mac 的文件夹授权提示；再次检查不会重复创建。'}
 return {**operation,'message':'文件夹已信任，等待 Mac 完成创建并同步。' if operation.get('folderTrusted') else '等待 Mac 确认文件夹或完成创建；确认后会自动同步。'}
def status(params):
 with _lock:
  operation=_read().get(params.get('requestId'))
  if operation is None:raise ValueError('找不到创建请求，请勿重复提交')
  return _status(operation)
def create(params):
 path=directory(params.get('path'));key=params.get('requestId')
 if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9-]{8,80}',key):raise ValueError('无效的创建请求标识')
 with _lock:
  operations=_read()
  if key in operations:
   if operations[key]['path']!=str(path):raise ValueError('同一创建请求不能更换文件夹')
   return _status(operations[key])
  existing=next((v for v in operations.values() if v['path']==str(path) and _status(v)['status']=='pending'),None)
  if existing:
   operations[key]={**existing,'requestId':key};_save(operations);return _status(operations[key])
  trusted=trust_selected_folder(path) # Explicit owner policy; only the selected canonical folder.
  operation={'requestId':key,'path':str(path),'name':path.name or str(path),'createdAt':time.time(),'status':'pending','folderTrusted':bool(trusted)}
  operations[key]=operation;_save(operations) # Save before dispatch: uncertain outcomes are never automatically retried.
  if _status(operation)['status']=='ready':return _status(operation)
  try:
   from desktop_integration import read
   config=read();app=config['app'] if config.get('enabled') else '/Applications/ChatGPT.app'
   result=subprocess.run(['/usr/bin/open','-a',app,path.as_uri()],capture_output=True,timeout=10)
   if result.returncode:raise RuntimeError('Mac 未能打开所选文件夹')
  except (OSError,subprocess.TimeoutExpired,RuntimeError) as e:
   operation={**operation,'status':'error','message':'电脑端创建请求未确认，请检查桌面状态'};operations[key]=operation;_save(operations)
  return _status(operation)
