import asyncio,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import host
class ManagementEntryChecks(unittest.TestCase):
 def test_existing_service_opens_fresh_authorized_page_without_starting_another(self):
  with patch('host.control',side_effect=[{'hostVersion':'0.1.1'},{'url':'http://127.0.0.1:1234/#bootstrap=temporary'}]),patch('subprocess.Popen') as start,patch('webbrowser.open') as browser:
   asyncio.run(host.open_management())
   start.assert_not_called();browser.assert_called_once_with('http://127.0.0.1:1234/#bootstrap=temporary')
if __name__=='__main__':unittest.main()
