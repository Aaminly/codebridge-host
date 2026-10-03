"""Keychain records must survive multiple pending devices without CLI size limits."""
import ctypes,unittest
from unittest.mock import patch,Mock
from device_store import DeviceStore
class Native:
 def __init__(self):
  self.data=None;self.buffers=[];self.denied=False
  for name in ('SecKeychainFindGenericPassword','SecKeychainAddGenericPassword','SecKeychainItemModifyAttributesAndData','SecKeychainItemFreeContent','CFRelease'):
   setattr(self,name,Mock(side_effect=getattr(self,name)))
 def SecKeychainFindGenericPassword(self,_keychain,_sl,_service,_al,_account,length,data,item):
  if self.denied:return -25293
  if self.data is None:return -25300
  buffer=ctypes.create_string_buffer(self.data);self.buffers.append(buffer)
  ctypes.cast(length,ctypes.POINTER(ctypes.c_uint32))[0]=len(self.data)
  ctypes.cast(data,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.addressof(buffer)
  ctypes.cast(item,ctypes.POINTER(ctypes.c_void_p))[0]=1
  return 0
 def SecKeychainAddGenericPassword(self,_keychain,_sl,_service,_al,_account,length,data,item):
  self.data=ctypes.string_at(data,length);return 0
 def SecKeychainItemModifyAttributesAndData(self,_item,_attrs,length,data):self.data=ctypes.string_at(data,length);return 0
 def SecKeychainItemFreeContent(self,*_args):return 0
 def CFRelease(self,*_args):pass
class StoreChecks(unittest.TestCase):
 def test_large_record_roundtrip_and_denied_access(self):
  native=Native();store=DeviceStore();record={'devices':{'phone':{'credential':'x'*16000}}}
  with patch('ctypes.CDLL',return_value=native),patch('subprocess.run',side_effect=AssertionError('Secrets must not use command-line storage')):
   store._save(record);self.assertEqual(store._load(),record)
   record['devices']['phone']['credential']='y'*20000
   store._save(record);self.assertEqual(store._load(),record)
   native.denied=True
   with self.assertRaises(OSError):store._load()
if __name__=='__main__':unittest.main()
