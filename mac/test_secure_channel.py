import unittest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from secure_channel import SecureChannel
class ChannelChecks(unittest.TestCase):
 def pair(self,pattern='XX',wrong=False):
  a=X25519PrivateKey.generate();b=X25519PrivateKey.generate()
  remote=X25519PrivateKey.generate().public_key().public_bytes_raw() if wrong else b.public_key().public_bytes_raw()
  return SecureChannel(pattern,True,a.private_bytes_raw(),remote),SecureChannel(pattern,False,b.private_bytes_raw(),a.public_key().public_bytes_raw() if pattern=='IK' else None)
 def handshake(self,a,b,pattern):
  b.read_handshake(a.write_handshake());a.read_handshake(b.write_handshake())
  if pattern=='XX':b.read_handshake(a.write_handshake())
 def test_patterns_authenticated_payload_and_replay(self):
  for pattern in ('XX','IK'):
   a,b=self.pair(pattern)
   with self.assertRaises(ValueError):a.encrypt(b'no early task')
   self.handshake(a,b,pattern)
   ciphertext=a.encrypt(b'private approval');self.assertEqual(b.decrypt(ciphertext),b'private approval')
   self.assertEqual(a.decrypt(b.encrypt(b'answer')),b'answer')
   with self.assertRaises(ValueError):b.decrypt(ciphertext)
   with self.assertRaises(ValueError):b.encrypt(b'closed')
 def test_wrong_pin_tamper_and_no_handshake_payload(self):
  a,b=self.pair();self.handshake(a,b,'XX');c=a.encrypt(b'data')
  with self.assertRaises(ValueError):b.decrypt(c[:-1]+bytes([c[-1]^1]))
  for pattern in ('XX','IK'):
   a,b=self.pair(pattern,True)
   with self.assertRaises(ValueError):self.handshake(a,b,pattern)
if __name__=='__main__':unittest.main()
