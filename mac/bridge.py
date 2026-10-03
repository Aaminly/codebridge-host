import asyncio,json,os,secrets,hmac,ssl,uuid,base64
from pathlib import Path
from host_paths import PATHS
from file_preview import collect_links,read_preview
import project_creation,project_removal,file_upload
from websockets.asyncio.server import serve
from websockets.asyncio.client import unix_connect
BASE=PATHS.base
ALLOWED={'initialize','initialized','thread/start','thread/list','thread/read','thread/resume','thread/settings/update','thread/archive','thread/unarchive','thread/loaded/list','thread/turns/list','thread/items/list','turn/start','turn/steer','turn/interrupt','model/list','account/rateLimits/read'}
def projects():
 d=json.loads(PATHS.state.read_text())
 order=d.get('project-order',[])
 items=list(d.get('local-projects',{}).values())
 items.sort(key=lambda p:order.index(p['id']) if p['id'] in order else len(order))
 return {'projects':items,'order':order,'assignments':d.get('thread-project-assignments',{}),'threadOrder':d.get('sidebar-project-thread-orders',{}),'pinnedProjects':d.get('pinned-project-ids',[]),'pinnedThreads':d.get('pinned-thread-ids',[]),'serverProjectIds':d.get('app-server-project-id-by-legacy-project-id-by-host',{}).get('local:'+str(PATHS.codex),{})}
def project_thread_params(params):
 d=json.loads(project_creation.STATE.read_text())
 project=d.get('local-projects',{}).get(params.get('projectId'))
 if project is None:raise ValueError('项目已不存在，请刷新列表')
 server_id=d.get('app-server-project-id-by-legacy-project-id-by-host',{}).get('local:'+str(PATHS.codex),{}).get(project['id'])
 if not server_id:raise ValueError('桌面项目尚未同步完成，请稍后重试')
 roots=project.get('rootPaths',[])
 if not roots:raise ValueError('项目没有可用文件夹')
 return {'cwd':roots[0],'projectId':server_id}
def mobile_messages(raw):
 if len(raw.encode('utf-8'))<=700_000:
  yield raw;return
 key=uuid.uuid4().hex;count=(len(raw)+99_999)//100_000
 for index in range(count):
  yield json.dumps({'method':'mobile/messageChunk','params':{'id':key,'index':index,'count':count,'data':raw[index*100_000:(index+1)*100_000]}},ensure_ascii=False)
def resolve_local_images(value):
 if isinstance(value,list):return [resolve_local_images(v) for v in value]
 if not isinstance(value,dict):return value
 if value.get('type')=='localImage':
  # Only resolve paths supplied by the authenticated desktop response, never phone parameters.
  try:
   path=Path(value['path']);size=path.stat().st_size
   if size>2_900_000:raise ValueError('附件超过当前图片传输限制')
   data=path.read_bytes()
   mime='image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None
   if not mime:raise ValueError('暂不支持此图片格式')
   return {'type':'image','url':'data:'+mime+';base64,'+base64.b64encode(data).decode('ascii'),'detail':value.get('detail')}
  except (OSError,ValueError) as e:return {'type':'imageError','message':str(e) if isinstance(e,ValueError) else '电脑上的原图已不可读取'}
 return {k:resolve_local_images(v) for k,v in value.items()}
async def handle_phone(phone,desktop_path=None):
 allowed_files=set();selectable_files=set();uploads=file_upload.Uploads()
 try:
  async with unix_connect(str(desktop_path or BASE/'desktop.sock'),uri='ws://localhost/',max_size=32*1024*1024,close_timeout=1) as desktop:
   async def upstream():
    async for raw in phone:
     x=json.loads(raw);m=x.get('method')
     if m in {'mobile/files/browse','mobile/files/select'}:
      try:
       result=await asyncio.to_thread(file_upload.browse,x.get('params',{})) if m.endswith('browse') else await asyncio.to_thread(file_upload.select,x.get('params',{}),selectable_files)
       if m.endswith('browse'):selectable_files.update(str(Path(f['path']).resolve()) for f in result['folders'] if not f['directory'])
       else:allowed_files.add(result['remote'])
      except (OSError,ValueError,KeyError) as e:result={'status':'error','message':str(e)}
      for message in mobile_messages(json.dumps({'id':x['id'],'result':result},ensure_ascii=False)):await phone.send(message)
      continue
     if m in {'mobile/files/uploadStart' ,'mobile/files/uploadChunk'}:
      try:
       result=await asyncio.to_thread(uploads.start if m.endswith('Start') else uploads.chunk,x.get('params',{}))
       if result.get('path'):allowed_files.add(result['path'])
       await phone.send(json.dumps({'id':x['id'],'result':result}))
      except (OSError,ValueError,KeyError,TypeError) as e:await phone.send(json.dumps({'id':x.get('id'),'error':{'code':-32602,'message':str(e)}}))
      continue
     if m=='mobile/files/read':
      result=await asyncio.to_thread(read_preview,x.get('params',{}).get('path',''),allowed_files)
      for message in mobile_messages(json.dumps({'id':x['id'],'result':result},ensure_ascii=False)):await phone.send(message)
      continue
     if m in {'mobile/folders/list','mobile/projects/create','mobile/projects/status','mobile/projects/remove','mobile/projects/removals'}:
      try:
       if m=='mobile/projects/remove':raise ValueError('延迟移除已停用；即时桌面同步入口尚未打通')
       action={'mobile/folders/list':project_creation.folders,'mobile/projects/create':project_creation.create,'mobile/projects/status':project_creation.status,'mobile/projects/remove':project_removal.request,'mobile/projects/removals':project_removal.statuses}[m]
       result=await asyncio.to_thread(action,x.get('params',{}))
      except (OSError,ValueError,RuntimeError,TimeoutError) as e:result={'status':'error','message':str(e)}
      await phone.send(json.dumps({'id':x['id'],'result':result},ensure_ascii=False));continue
     if m=='mobile/projects/list':
      await phone.send(json.dumps({'id':x['id'],'result':projects()}));continue
     if m=='mobile/thread/start':
      try:x['params']=project_thread_params(x.get('params',{}))
      except (OSError,ValueError) as e:
       await phone.send(json.dumps({'id':x.get('id'),'error':{'code':-32602,'message':str(e)}}));continue
      x['method']='thread/start';raw=json.dumps(x);m='thread/start'
     # Responses to actual server approval requests carry id and no method.
     if m is not None and m not in ALLOWED:
      await phone.send(json.dumps({'id':x.get('id'),'error':{'code':-32601,'message':'Unsupported mobile operation'}}));continue
     if m=='thread/settings/update' and (not isinstance(x.get('params'),dict) or set(x['params'])-{'threadId','model','effort','serviceTier'}):
      await phone.send(json.dumps({'id':x.get('id'),'error':{'code':-32602,'message':'Only model, reasoning effort and service tier may be updated'}}));continue
     await desktop.send(raw)
   async def downstream():
    async for raw in desktop:
     value=json.loads(raw)
     collect_links(value,allowed_files)
     resolved=await asyncio.to_thread(resolve_local_images,value)
     for message in mobile_messages(json.dumps(resolved,ensure_ascii=False)):await phone.send(message)
   jobs=[asyncio.create_task(upstream()),asyncio.create_task(downstream())]
   try:
    done,pending=await asyncio.wait(jobs,return_when=asyncio.FIRST_COMPLETED)
    for job in done:job.result()
   finally:
    for job in jobs:job.cancel()
    await asyncio.gather(*jobs,return_exceptions=True)
 except (OSError,TimeoutError):await phone.close(1013,'Desktop connection is not ready')
 finally:await asyncio.to_thread(uploads.close)

async def main():
 token=(BASE/'device.token').read_text().strip()
 async def auth(conn,req):
  if req.path!='/rpc' or not hmac.compare_digest(req.headers.get('Authorization',''),'Bearer '+token):
   return conn.respond(401,'Device authentication required\n')
 ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2
 ctx.load_cert_chain(BASE/'server.crt',BASE/'server.key')
 async with serve(handle_phone,'0.0.0.0',9443,ssl=ctx,process_request=auth,max_size=32*1024*1024):
  worker=None # Deferred removal disabled: user rejected desktop-exit requirement.
  try:await asyncio.Future()
  finally:
   if worker is not None:worker.cancel()
if __name__=="__main__":asyncio.run(main())
