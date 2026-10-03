"""Encrypted v2 relay transport, using the existing mobile RPC boundary."""
import asyncio,base64,hashlib,json,time,secrets
from urllib.parse import urlsplit
from websockets.asyncio.client import connect
from secure_channel import SecureChannel
from secure_messages import Messages
from bridge import handle_phone

class Peer:
 def __init__(self,runtime,id,info):
  self.runtime=runtime;self.id=id;self.info=info;self.incoming=asyncio.Queue(maxsize=8);self.lock=asyncio.Lock();self.messages=Messages();self.job=None
  device=runtime.identity['devices'].get(info.get('deviceId'))
  if info['role']=='device' and device is None:raise ValueError('Device revoked')
  if runtime.state.endpoint is None:raise ValueError('Desktop instance unconfirmed')
  self.channel=SecureChannel('XX' if info['role']=='pairing' else 'IK',False,bytes.fromhex(runtime.identity['privateKey']),bytes.fromhex(device['publicKey']) if device else None)
 async def frame(self,raw):
  data=base64.b64decode(raw,validate=True)
  if not self.channel.ready:
   self.channel.read_handshake(data)
   if not self.channel.ready:await self.runtime.send({'type':'data','id':self.id,'data':base64.b64encode(self.channel.write_handshake()).decode()})
   if self.channel.ready and self.info['role']=='device':self.start_rpc()
   return
  message=self.messages.read(self.channel.decrypt(data))
  if message is None:return
  if self.info['role']=='pairing':
   value=json.loads(message)
   p=self.runtime.pairings.pending.get(self.info['pairingId'])
   if p is None or p['expiresAt']<=time.time():raise ValueError('Pairing unavailable')
   if value.get('type')=='pairingReady' and p.get('device',{}).get('publicKey')==self.channel.remote_key.hex():p['phoneReady']=True;self.runtime.pairings.persist();return
   if value.get('type')!='pairingRequest' or self.job is not None:raise ValueError('Pairing request required')
   if self.info.get('resume'):
    if p.get('device',{}).get('publicKey')!=self.channel.remote_key.hex():raise ValueError('Pairing identity mismatch')
    if p['state']=='approved':
     self.job=asyncio.create_task(self.runtime.finish_approval(self,p['device']));return
    if p['state']!='claimed':raise ValueError('Pairing unavailable')
    await self.send(json.dumps({'type':'pairingPending','recoveryCredential':p['recoveryCredential']}))
   else:
    self.runtime.pairings.claim(self.info['pairingId'],p.get('capability',''),self.channel.remote_key.hex(),value.get('name',''),time.time())
    p['recoveryCredential']=secrets.token_urlsafe(32);self.runtime.pairings.persist()
    async def recovery():
     await self.runtime.control({'type':'recovery','id':self.id,'credentialHash':hashlib.sha256(p['recoveryCredential'].encode()).hexdigest()},'recoveryReady',self.id)
     await self.send(json.dumps({'type':'pairingPending','recoveryCredential':p['recoveryCredential']}))
    asyncio.create_task(recovery())
   async def expire():
    await asyncio.sleep(max(0,p['expiresAt']-time.time()));await self.close(1008,'Pairing expired')
   self.job=asyncio.create_task(expire())
  else:
   if self.info['role']!='device':raise ValueError('Fresh device handshake required')
   try:self.incoming.put_nowait(message.decode())
   except asyncio.QueueFull:raise ValueError('Desktop input queue exceeded')
 def start_rpc(self):
  self.job=asyncio.create_task(handle_phone(self,self.runtime.state.endpoint.socket_path))
  def completed(job):
   if not job.cancelled():
    error=job.exception()
    if error:self.runtime.state.snapshot['relayError']=type(error).__name__
    if self.runtime.socket:asyncio.create_task(self.close(1013,'Desktop forwarding ended'))
  self.job.add_done_callback(completed)
 async def send(self,message):
  data=message.encode() if isinstance(message,str) else message
  async with self.lock:
   for frame in Messages.frames(data):await self.runtime.send({'type':'data','id':self.id,'data':base64.b64encode(self.channel.encrypt(frame)).decode()})
 async def close(self,code=1000,reason=''):
  await self.runtime.send({'type':'close','id':self.id})
 def __aiter__(self):return self
 async def __anext__(self):return await self.incoming.get()
 def cancel(self):
  if self.job:self.job.cancel()
  self.channel.failed=True

class Runtime:
 def __init__(self,state,store,pairings,origin,test_local=False):
  u=urlsplit(origin)
  if u.path not in ('','/') or u.query or u.fragment or u.username or not u.hostname:raise ValueError('Invalid relay origin')
  if u.scheme!='https' and not (test_local and u.scheme=='http' and u.hostname=='127.0.0.1'):raise ValueError('TLS relay required')
  self.origin=origin.rstrip('/');self.state=state;self.store=store;self.pairings=pairings;self.identity=store.identity();self.peers={};self.socket=None;self.waiters={};self.loop=None
 async def send(self,value):
  if self.socket is None:raise ValueError('Relay disconnected')
  await self.socket.send(json.dumps(value,separators=(',',':')))
 async def control(self,value,response,key):
  future=asyncio.get_running_loop().create_future();self.waiters[(response,key)]=future
  try:await self.send(value);await asyncio.wait_for(future,10)
  finally:self.waiters.pop((response,key),None)
 async def begin(self):
  if self.socket is None or self.state.endpoint is None:raise ValueError('Desktop or relay disconnected')
  offer=self.pairings.begin_pairing();await self.control({'type':'offer','pairingId':offer['pairingId'],'capabilityHash':hashlib.sha256(offer['capability'].encode()).hexdigest(),'expiresAt':int(offer['expiresAt']*1000)},'offered',offer['pairingId']);return offer
 async def approve(self,id):
  peer=next((p for p in self.peers.values() if p.info.get('pairingId')==id),None)
  if peer is None or not peer.channel.ready:raise ValueError('Phone disconnected')
  if not self.pairings.pending.get(id,{}).get('phoneReady'):raise ValueError('Phone identity persistence not confirmed')
  device=self.pairings.approve(id,peer.channel.remote_key.hex());self.identity=self.store.identity()
  await self.finish_approval(peer,device);return {'approved':True}
 async def finish_approval(self,peer,device):
  self.identity=self.store.identity()
  authorized=self.identity['devices'].get(device['id'])
  if authorized is None or authorized['publicKey']!=peer.channel.remote_key.hex():raise ValueError('Device authorization unavailable')
  await self.control({'type':'authorize','id':peer.id,'deviceId':device['id'],'credentialHash':hashlib.sha256(device['credential'].encode()).hexdigest()},'authorized',peer.id)
  await peer.send(json.dumps({'type':'approved','deviceId':device['id'],'credential':device['credential']}));peer.info['role']='approved'
  if peer.job and peer.job is not asyncio.current_task():peer.job.cancel()
 async def reject(self,id):self.pairings.reject(id);await self.send({'type':'reject','pairingId':id});return {'rejected':True}
 async def revoke(self,id):
  self.pairings.revoke(id);self.identity=self.store.identity()
  for peer in list(self.peers.values()):
   if peer.info.get('deviceId')==id:peer.cancel()
  if self.socket:await self.control({'type':'revoke','deviceId':id},'revoked',id)
  return {'revoked':True}
 async def run(self):
  self.loop=asyncio.get_running_loop()
  while True:
   try:
    url=self.origin.replace('https://','wss://').replace('http://','ws://')+'/v2/hosts/'+self.identity['hostId']+'/connect'
    async with connect(url,additional_headers={'Authorization':'Bearer '+self.identity['relayCredential']},max_size=1048576) as ws:
     self.socket=ws;self.state.snapshot['relayReady']=True
     # Reconcile offline revocations before devices receive any business channel.
     for id in self.identity.get('revoked',[]):await self.send({'type':'revoke','deviceId':id})
     async for raw in ws:
      x=json.loads(raw);id=x.get('id')
      if x['type'] in ('offered','authorized','revoked','recoveryReady'):
       key=x.get('pairingId') if x['type']=='offered' else x.get('deviceId') if x['type']=='revoked' else id
       future=self.waiters.get((x['type'],key))
       if future and not future.done():future.set_result(x)
      elif x['type']=='open':
       try:self.peers[id]=Peer(self,id,x)
       except ValueError:await self.send({'type':'close','id':id})
      elif x['type']=='close':
       peer=self.peers.pop(id,None)
       if peer:peer.cancel()
      elif x['type']=='data':
       peer=self.peers.get(id)
       if peer:
        try:await peer.frame(x['data'])
        except (ValueError,KeyError,UnicodeError):peer.cancel();await self.send({'type':'close','id':id})
   except asyncio.CancelledError:raise
   except Exception as error:self.state.snapshot['relayError']=type(error).__name__ # No payload logging or false success.
   finally:
    self.socket=None;self.state.snapshot['relayReady']=False
    for peer in self.peers.values():peer.cancel()
    jobs=[p.job for p in self.peers.values() if p.job]
    if jobs:await asyncio.gather(*jobs,return_exceptions=True)
    self.peers.clear()
    for future in self.waiters.values():
     if not future.done():future.set_exception(ValueError('Relay disconnected; outcome unconfirmed'))
   await asyncio.sleep(3)
