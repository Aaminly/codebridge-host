import unittest
from unittest.mock import patch
from host import HostState
class HostChecks(unittest.TestCase):
 def test_denied_identity_keeps_console_available_without_false_relay_success(self):
  state=HostState()
  with patch('device_store.DeviceStore.identity',side_effect=OSError('denied')):state.configure({'origin':'https://relay.example'})
  value=state.status();self.assertFalse(value['relayReady']);self.assertTrue(value['relayConfigured']);self.assertTrue(value['connectionError']);self.assertIsNone(state.runtime)
if __name__=='__main__':unittest.main()
