import asyncio,json,tempfile,unittest
from pathlib import Path
from websockets.asyncio.server import unix_serve
from unittest.mock import AsyncMock,patch
import thread_titles

class TitleChecks(unittest.IsolatedAsyncioTestCase):
 async def test_generation_uses_ephemeral_restricted_thread_and_cleans_up(self):
  for status in ('completed','failed'):
   calls=[]
   async def desktop(ws):
    async for raw in ws:
     request=json.loads(raw);method=request.get('method');p=request.get('params',{});calls.append((method,p))
     if 'id' not in request:continue
     result={}
     if method=='thread/read':result={'thread':{'name':None}}
     elif method=='thread/turns/list':result={'data':[{'id':'first'}]}
     elif method=='config/read':result={'config':{'mcp_servers':{'private_server':{'enabled':True}}}}
     elif method=='thread/start':result={'thread':{'id':'temporary'}}
     elif method=='turn/start':
      result={'turn':{'id':'generation'}}
      for notification in [
       {'method':'item/completed','params':{'threadId':'temporary','turnId':'generation','item':{'type':'agentMessage','text':'{"title":"简洁标题"}'}}},
       {'method':'turn/completed','params':{'threadId':'temporary','turn':{'id':'generation','status':status}}}]:await ws.send(json.dumps(notification))
     await ws.send(json.dumps({'id':request['id'],'result':result}))
   with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
    path=Path(tmp)/'socket'
    async with unix_serve(desktop,str(path)):
     if status=='completed':await thread_titles.run(path,'chat','first','原始文字')
     else:
      with self.assertRaisesRegex(ValueError,'did not complete'):await thread_titles.run(path,'chat','first','原始文字')
   params=next(p for m,p in calls if m=='thread/start')
   self.assertTrue(params['ephemeral']);self.assertEqual(params['permissions'],':read-only')
   self.assertEqual(params['runtimeWorkspaceRoots'],[]);self.assertFalse(params['config']['mcp_servers.private_server.enabled'])
   self.assertFalse(params['config']['features.shell_tool']);self.assertEqual(params['config']['project_doc_max_bytes'],0)
   self.assertIn(('thread/unsubscribe',{'threadId':'temporary'}),calls)
   self.assertEqual(any(m=='thread/name/set' for m,p in calls),status=='completed')
 async def test_bridge_only_schedules_accepted_sends_without_waiting_for_title(self):
  from bridge import handle_phone
  for error in (False,True):
   responses=[];received=asyncio.Event()
   class Phone:
    sent=False
    def __aiter__(self):return self
    async def __anext__(self):
     if self.sent:await asyncio.Future()
     self.sent=True
     return json.dumps({'id':7,'method':'turn/start','params':{'threadId':'chat','input':[{'type':'text','text':'原始输入'}]}})
    async def send(self,raw):responses.append(json.loads(raw));received.set()
    async def close(self,*args):pass
   async def desktop(ws):
    async for raw in ws:
     request=json.loads(raw)
     await ws.send(json.dumps({'id':request['id'],**({'error':{'message':'rejected'}} if error else {'result':{'turn':{'id':'first'}}})}))
   with tempfile.TemporaryDirectory(dir='/tmp') as tmp,patch.object(thread_titles,'schedule') as schedule:
    path=Path(tmp)/'socket'
    async with unix_serve(desktop,str(path)):
     task=asyncio.create_task(handle_phone(Phone(),path))
     await asyncio.wait_for(received.wait(),2);await asyncio.sleep(.01)
     if error:schedule.assert_not_called()
     else:schedule.assert_called_once_with(path,'chat','first','原始输入')
     self.assertEqual(responses[0]['id'],7)
     task.cancel();await asyncio.gather(task,return_exceptions=True)
 async def test_first_turn_sets_real_name_without_reading_messages(self):
  calls=[]
  async def rpc(method,params):
   calls.append((method,params))
   if method=='thread/read':return {'thread':{'id':'chat','name':None}}
   if method=='thread/turns/list':return {'data':[{'id':'first'}],'nextCursor':None}
   return {}
  generate=AsyncMock(return_value='优化读取性能')
  await thread_titles.name_first_turn(rpc,generate,'chat','first','请优化读取性能')
  self.assertEqual(calls[-1],('thread/name/set',{'threadId':'chat','name':'优化读取性能'}))
  self.assertTrue(all(not p.get('includeTurns',False) for m,p in calls if m=='thread/read'))
  self.assertEqual(generate.await_count,1)
 async def test_second_send_while_first_title_generates_does_not_cancel_naming(self):
  calls=[]
  async def rpc(method,params):
   calls.append(method)
   return {'thread':{}} if method=='thread/read' else {'data':[{'id':'first'},{'id':'second'}],'nextCursor':'more'}
  await thread_titles.name_first_turn(rpc,AsyncMock(return_value='简洁名称'),'chat','first','输入')
  self.assertEqual(calls[-1],'thread/name/set')
 async def test_metadata_flush_retry_is_bounded_and_specific(self):
  rpc=AsyncMock(side_effect=[ValueError('rollout at /qa is empty'),{'thread':{'name':'已有名称'}}])
  with patch('thread_titles.asyncio.sleep',new_callable=AsyncMock) as sleep:
   await thread_titles.name_first_turn(rpc,AsyncMock(),'chat','first','输入')
   self.assertEqual(rpc.await_count,2);sleep.assert_awaited_once_with(.25)
  rpc=AsyncMock(side_effect=ValueError('permission denied'))
  with self.assertRaisesRegex(ValueError,'permission denied'):
   await thread_titles.name_first_turn(rpc,AsyncMock(),'chat','first','输入')
  self.assertEqual(rpc.await_count,1)
 async def test_existing_name_or_later_turn_never_generates(self):
  for thread,turns in [({'name':'用户名称'},[{'id':'first'}]),({'name':None},[{'id':'older'},{'id':'first'}]),({'name':None},[{'id':'other'}])]:
   async def rpc(method,params):return {'thread':thread} if method=='thread/read' else {'data':turns,'nextCursor':None}
   generate=AsyncMock()
   await thread_titles.name_first_turn(rpc,generate,'chat','first','输入')
   generate.assert_not_awaited()
 async def test_rename_during_generation_wins(self):
  reads=iter([{'name':None},{'name':'桌面名称'}]);calls=[]
  async def rpc(method,params):
   calls.append(method)
   return {'thread':next(reads)} if method=='thread/read' else {'data':[{'id':'first'}]}
  await thread_titles.name_first_turn(rpc,AsyncMock(return_value='生成名称'),'chat','first','输入')
  self.assertNotIn('thread/name/set',calls)
 async def test_empty_or_invalid_output_cannot_change_title(self):
  for value in ['',None,'a\nb','x'*81]:
   rpc=AsyncMock(side_effect=[{'thread':{}},{'data':[{'id':'first'}]}])
   await thread_titles.name_first_turn(rpc,AsyncMock(return_value=value),'chat','first','输入')
   self.assertEqual(rpc.await_count,2)
 async def test_duplicate_connections_share_job_and_cleanup(self):
  started=asyncio.Event();release=asyncio.Event()
  async def run(*args):started.set();await release.wait()
  with patch.object(thread_titles,'run',run):
   thread_titles.schedule('/one','chat','first','输入')
   thread_titles.schedule('/one','chat','first','输入')
   await started.wait();self.assertEqual(len(thread_titles.jobs),1)
   release.set();await asyncio.gather(*list(thread_titles.jobs.values()));await asyncio.sleep(0)
   self.assertEqual(thread_titles.jobs,{})

if __name__=='__main__':unittest.main()
