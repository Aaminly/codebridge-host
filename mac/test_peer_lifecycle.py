import asyncio,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from v2_host import Peer
class PeerChecks(unittest.IsolatedAsyncioTestCase):
 async def test_normal_forwarding_completion_closes_phone(self):
  k=X25519PrivateKey.generate();sent=[]
  async def send(value):sent.append(value)
  async def forward(*args):return None
  runtime=SimpleNamespace(identity={'privateKey':k.private_bytes_raw().hex(),'devices':{'device':{'publicKey':k.public_key().public_bytes_raw().hex()}}},state=SimpleNamespace(endpoint=SimpleNamespace(socket_path=Path('/not-used')),snapshot={}),send=send,socket=True)
  p=Peer(runtime,'peer',{'role':'device','deviceId':'device'})
  with patch('v2_host.handle_phone',forward):p.start_rpc();await asyncio.sleep(.05)
  self.assertTrue(any(x.get('type')=='close' for x in sent))
if __name__=='__main__':unittest.main()
