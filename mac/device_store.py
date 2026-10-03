"""Dedicated v2 identity and device records in macOS Keychain, never legacy tokens."""
import base64,ctypes,json,threading,uuid,secrets
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
SERVICE='dev.codebridge.host-v2'
def _keychain(value=None):
 """Use native buffers: security's interactive CLI truncates lines at 4096 bytes."""
 security=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
 core=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
 pointer=ctypes.c_void_p;uint=ctypes.c_uint32;char=ctypes.c_char_p
 signatures={
  'SecKeychainFindGenericPassword':[pointer,uint,char,uint,char,ctypes.POINTER(uint),ctypes.POINTER(pointer),ctypes.POINTER(pointer)],
  'SecKeychainAddGenericPassword':[pointer,uint,char,uint,char,uint,pointer,ctypes.POINTER(pointer)],
  'SecKeychainItemModifyAttributesAndData':[pointer,pointer,uint,pointer],
  'SecKeychainItemFreeContent':[pointer,pointer],
 }
 for name,args in signatures.items():
  function=getattr(security,name);function.argtypes=args;function.restype=ctypes.c_int32
 core.CFRelease.argtypes=[pointer];core.CFRelease.restype=None
 service=SERVICE.encode();account=b'identity';length=uint();data=pointer();item=pointer()
 status=security.SecKeychainFindGenericPassword(None,len(service),service,len(account),account,ctypes.byref(length),ctypes.byref(data),ctypes.byref(item))
 try:
  if status not in (0,-25300):raise OSError('Keychain identity unavailable')
  if value is None:return ctypes.string_at(data,length.value) if status==0 else None
  buffer=ctypes.create_string_buffer(value)
  if status==0:status=security.SecKeychainItemModifyAttributesAndData(item,None,len(value),buffer)
  else:status=security.SecKeychainAddGenericPassword(None,len(service),service,len(account),account,len(value),buffer,ctypes.byref(item))
  if status:raise OSError('Keychain write not confirmed')
 finally:
  if data.value:security.SecKeychainItemFreeContent(None,data)
  if item.value:core.CFRelease(item)
class DeviceStore:
 def __init__(self):self.lock=threading.RLock()
 def _load(self):
  value=_keychain()
  return json.loads(base64.b64decode(value,validate=True)) if value is not None else None
 def _save(self,data):
  value=base64.b64encode(json.dumps(data,separators=(',',':')).encode())
  _keychain(value)
  if self._load()!=data:raise OSError('Keychain write not confirmed')
 def identity(self):
  with self.lock:
   data=self._load()
   if data is None:
    key=X25519PrivateKey.generate();data={'hostId':str(uuid.uuid4()),'privateKey':key.private_bytes_raw().hex(),'publicKey':key.public_key().public_bytes_raw().hex(),'devices':{},'relayCredential':secrets.token_urlsafe(32),'revoked':[]}
    self._save(data)
   return data
 def pairings(self):return self.identity().get('pairings',{})
 def save_pairings(self,pairings):
  with self.lock:
   data=self.identity();data['pairings']=pairings;self._save(data)
 def approve_pairing(self,device,pairings):
  with self.lock:
   data=self.identity();data['devices'][device['id']]=device;data['pairings']=pairings;self._save(data)
 def save_device(self,device):
  with self.lock:
   data=self.identity();data['devices'][device['id']]=device;self._save(data)
 def revoke(self,device_id):
  with self.lock:
   data=self.identity()
   if device_id not in data['devices']:raise ValueError('Device unavailable')
   del data['devices'][device_id];data.setdefault('revoked',[]).append(device_id);self._save(data)
