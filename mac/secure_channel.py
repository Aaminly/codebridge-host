"""Pinned standard Noise XX/IK. No business data until the handshake completes."""
import hmac
from cryptography.exceptions import InvalidTag
from noise.connection import NoiseConnection,Keypair
from noise.exceptions import NoiseHandshakeError,NoiseInvalidMessage,NoiseValueError,NoiseValidationError

class SecureChannel:
 def __init__(self,pattern,initiator,private_key,remote_key=None):
  if pattern not in ('XX','IK') or len(private_key)!=32 or (remote_key is not None and len(remote_key)!=32):raise ValueError('Invalid Noise identity')
  if (initiator or pattern=='IK') and remote_key is None:raise ValueError('Remote identity required')
  self.expected=remote_key;self.remote_key=None;self.failed=False
  self.noise=NoiseConnection.from_name(f'Noise_{pattern}_25519_ChaChaPoly_SHA256'.encode())
  (self.noise.set_as_initiator if initiator else self.noise.set_as_responder)()
  self.noise.set_keypair_from_private_bytes(Keypair.STATIC,private_key)
  if pattern=='IK':self.noise.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC,remote_key)
  self.noise.set_prologue(b'CodeBridge/v2')
  self.noise.start_handshake()
 def _check_pin(self,state):
  remote=getattr(state.rs,'public_bytes',None)
  if remote:
   if self.expected is not None and not hmac.compare_digest(self.expected,remote):raise ValueError('Desktop identity mismatch')
   self.remote_key=remote
 def _perform(self,operation):
  if self.failed:raise ValueError('Noise connection is closed')
  try:return operation()
  except (NoiseHandshakeError,NoiseInvalidMessage,NoiseValueError,NoiseValidationError,InvalidTag,ValueError) as error:
   self.failed=True;raise ValueError('Noise authentication failed') from error
 def write_handshake(self):
  def write():
   state=self.noise.noise_protocol.handshake_state
   result=bytes(self.noise.write_message())
   self._check_pin(state);return result
  return self._perform(write)
 def read_handshake(self,message):
  def read():
   state=self.noise.noise_protocol.handshake_state
   if self.noise.read_message(message):raise ValueError('Handshake must not carry business data')
   self._check_pin(state)
  return self._perform(read)
 @property
 def ready(self):return self.noise.handshake_finished and not self.failed and self.remote_key is not None
 def encrypt(self,data):
  if not self.ready:raise ValueError('Handshake incomplete')
  return self._perform(lambda:self.noise.encrypt(data))
 def decrypt(self,data):
  if not self.ready:raise ValueError('Handshake incomplete')
  return self._perform(lambda:self.noise.decrypt(data))
