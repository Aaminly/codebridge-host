"""Atomic one-use pairing. claim receives a Noise-authenticated static identity."""
import hmac,re,secrets,threading,time,uuid
class Pairings:
 def __init__(self,host_id,public_key,relay_origin,store):
  self.host_id=host_id;self.public_key=public_key;self.relay_origin=relay_origin;self.store=store
  self.pending=store.pairings();self.lock=threading.RLock()
 def begin_pairing(self,now=None):
  now=time.time() if now is None else now
  with self.lock:
   self.pending={k:v for k,v in self.pending.items() if v['expiresAt']>now}
   if len(self.pending)>=8:raise ValueError('Too many pending pairings')
   offer={'protocolVersion':2,'relayOrigin':self.relay_origin,'hostId':self.host_id,'hostPublicKey':self.public_key,'pairingId':str(uuid.uuid4()),'capability':secrets.token_urlsafe(32),'expiresAt':now+120}
   self.pending[offer['pairingId']]={**offer,'state':'offered'}
   self.persist();return dict(offer)
 def claim(self,pairing_id,capability,public_key,name,now=None):
  now=time.time() if now is None else now
  if not isinstance(public_key,str) or not re.fullmatch('[a-f0-9]{64}',public_key) or public_key=='0'*64:raise ValueError('Invalid device identity')
  if not isinstance(name,str) or not 1<=len(name)<=80 or any(ord(c)<32 for c in name):raise ValueError('Invalid device name')
  with self.lock:
   p=self.pending.get(pairing_id)
   if p is None or p['state']!='offered' or now>=p['expiresAt'] or not isinstance(capability,str) or not hmac.compare_digest(capability,p['capability']):raise ValueError('Pairing unavailable')
   device={'id':str(uuid.uuid4()),'publicKey':public_key,'name':name,'credential':secrets.token_urlsafe(32)}
   p.update(state='claimed',device=device);p.pop('capability')
   self.persist();return {k:v for k,v in device.items() if k!='credential'}
 def approve(self,pairing_id,device_key,now=None):
  now=time.time() if now is None else now
  with self.lock:
   p=self.pending.get(pairing_id)
   if p is None or p['state']!='claimed' or now>=p['expiresAt'] or not hmac.compare_digest(p['device']['publicKey'],device_key):raise ValueError('Pairing confirmation unavailable')
   p['state']='approved'
   self.store.approve_pairing(p['device'],self.pending) # One durable identity record contains both decisions.
   return dict(p['device'])
 def reject(self,pairing_id):
  with self.lock:
   p=self.pending.get(pairing_id)
   if p is None or p['state'] not in ('offered','claimed'):raise ValueError('Pairing unavailable')
   p['state']='rejected';p.pop('capability',None);p.pop('device',None);self.persist()
 def persist(self):
  with self.lock:self.store.save_pairings(self.pending)
 def revoke(self,device_id):
  with self.lock:
   self.store.revoke(device_id)
   for p in self.pending.values():
    if p.get('device',{}).get('id')==device_id:p['state']='revoked'
   self.persist()
 def status(self,now=None):
  now=time.time() if now is None else now
  with self.lock:
   return [{'id':k,'state':p['state'],'expiresAt':p['expiresAt'],'name':p.get('device',{}).get('name',''),'fingerprint':p.get('device',{}).get('publicKey',''),'phoneReady':p.get('phoneReady',False)} for k,p in self.pending.items() if now<p['expiresAt'] and p['state'] in ('offered','claimed')]
