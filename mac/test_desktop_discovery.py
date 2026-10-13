import asyncio,json,tempfile,unittest
from pathlib import Path
from websockets.asyncio.server import unix_serve
from desktop_discovery import Endpoint,ProbeResult,choose,discover,probe


class DiscoveryChecks(unittest.IsolatedAsyncioTestCase):
 async def test_real_socket_handshake_and_loaded_pages(self):
  seen=[]
  async def server(ws):
   async for raw in ws:
    x=json.loads(raw);seen.append(x['method'])
    if x['method']=='initialized':continue
    if x['method']=='initialize':result={'userAgent':'test-desktop/1'}
    elif x['method']=='thread/loaded/list':
     result={'data':['active-thread'],'nextCursor':'page2'} if not x['params'].get('cursor') else {'data':['other-thread'],'nextCursor':None}
    else:self.fail('Probe sent a mutating or unrelated RPC')
    await ws.send(json.dumps({'id':x['id'],'result':result}))
  with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
   home=Path(tmp);path=home/'.codex/app-server-control/app-server-control.sock';path.parent.mkdir(parents=True)
   async with unix_serve(server,str(path)):
    endpoints=discover(home)
    self.assertEqual(endpoints,[Endpoint(path)])
    result=await probe(endpoints[0])
   self.assertIsNone(result.error)
   self.assertEqual(result.loaded_thread_ids,frozenset(['active-thread','other-thread']))
   self.assertEqual(result.version,'test-desktop/1')
   self.assertEqual(seen,['initialize','initialized','thread/loaded/list','thread/loaded/list'])

 async def test_missing_and_bad_socket_do_not_report_success(self):
  with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
   home=Path(tmp);self.assertEqual(discover(home),[])
   path=home/'.codex/app-server-control/app-server-control.sock';path.parent.mkdir(parents=True);path.write_text('not a socket')
   self.assertEqual(discover(home),[])
   result=await probe(Endpoint(path))
   self.assertIsNotNone(result.error)
   with self.assertRaises(ValueError):choose([result],None)

 async def test_server_error_and_repeated_cursor_are_not_success(self):
  for payload in [{'error':{'code':-1,'message':'unsupported'}},{'result':{'data':['id'],'nextCursor':'same'}}]:
   async def server(ws):
    async for raw in ws:
     x=json.loads(raw)
     if x['method']=='initialized':continue
     body={'result':{'userAgent':'test'}} if x['method']=='initialize' else payload
     await ws.send(json.dumps({'id':x['id'],**body}))
   with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
    path=Path(tmp)/'test.sock'
    async with unix_serve(server,str(path)):
     result=await probe(Endpoint(path))
    self.assertIsNotNone(result.error)

 async def test_owned_socket_is_hidden_after_desktop_disconnect(self):
  with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
   home=Path(tmp);base=home/'Library/Application Support/CodexMobile';base.mkdir(parents=True)
   config=base/'host-v2/desktop.json';config.parent.mkdir();config.write_text(json.dumps({'enabled':True}))
   async with unix_serve(lambda ws: ws.wait_closed(),str(base/'desktop.sock')):
    self.assertEqual(discover(home),[])

 def test_selection_requires_unambiguous_loaded_thread(self):
  first=ProbeResult(Endpoint(Path('/a')), '1',frozenset(['a']))
  second=ProbeResult(Endpoint(Path('/b')), '1',frozenset(['target']))
  self.assertEqual(choose([first,second],'target'),second)
  for candidates,target in [([first,second],None),([first,second],'missing'),([],None),([second,second],'target')]:
   with self.assertRaises(ValueError):choose(candidates,target)
  self.assertEqual(choose([first],None),first)


if __name__=='__main__':unittest.main()
