import asyncio,tempfile,unittest
from pathlib import Path
from websockets.asyncio.server import unix_serve
from bridge import handle_phone
class Phone:
 def __aiter__(self):return self
 async def __anext__(self):await asyncio.Future()
 async def send(self,message):pass
 async def close(self,*args):pass
class CleanupChecks(unittest.IsolatedAsyncioTestCase):
 async def test_cancel_cleans_both_pumps(self):
  async def server(ws):await ws.wait_closed()
  with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
   path=Path(tmp)/'desktop.sock'
   async with unix_serve(server,str(path)):
    task=asyncio.create_task(handle_phone(Phone(),path));await asyncio.sleep(.05);task.cancel();await asyncio.gather(task,return_exceptions=True)
    pending=[t for t in asyncio.all_tasks() if 'handle_phone.<locals>' in t.get_coro().__qualname__]
    self.assertEqual(pending,[])
 async def test_unresponsive_desktop_close_is_bounded(self):
  ready=asyncio.get_running_loop().create_future()
  async def server(ws):ws.transport.pause_reading();ready.set_result(ws);await ws.wait_closed()
  with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
   path=Path(tmp)/'desktop.sock'
   async with unix_serve(server,str(path),close_timeout=.1):
    task=asyncio.create_task(handle_phone(Phone(),path));ws=await ready;await asyncio.sleep(.05);task.cancel()
    try:
     with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
    finally:ws.transport.resume_reading();task.cancel();await asyncio.gather(task,return_exceptions=True)
if __name__=='__main__':unittest.main()
