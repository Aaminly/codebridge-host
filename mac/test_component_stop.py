import asyncio,unittest
from unittest.mock import patch
import host
class StopChecks(unittest.IsolatedAsyncioTestCase):
 async def test_failed_unregistration_is_visible_and_does_not_report_stopped(self):
  state=host.HostState();stop=asyncio.Event()
  with patch('desktop_integration.disable'),patch('host.autostart',side_effect=OSError('denied')):
   self.assertFalse(await host.disable_component(state,stop))
  self.assertFalse(stop.is_set());self.assertIn('未能停用',state.snapshot['componentError'])
if __name__=='__main__':unittest.main()
