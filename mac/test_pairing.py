import concurrent.futures,unittest
from pairing import Pairings
class Store:
 def __init__(self):self.devices={};self.saved={}
 def pairings(self):return self.saved.copy()
 def save_pairings(self,p):self.saved=p.copy()
 def approve_pairing(self,d,p):self.save_device(d);self.save_pairings(p)
 def save_device(self,device):self.devices[device['id']]=device
 def revoke(self,device_id):self.devices.pop(device_id,None)
class PairingChecks(unittest.TestCase):
 def setUp(self):self.store=Store();self.p=Pairings('host','key','https://relay.example',self.store)
 def test_expiry_reuse_confirmation_and_revocation(self):
  offer=self.p.begin_pairing(100)
  with self.assertRaises(ValueError):self.p.claim(offer['pairingId'],offer['capability'],'key1','phone',220)
  offer=self.p.begin_pairing(300)
  device=self.p.claim(offer['pairingId'],offer['capability'],'11'*32,'phone',301)
  self.assertEqual(self.store.devices,{})
  with self.assertRaises(ValueError):self.p.claim(offer['pairingId'],offer['capability'],'22'*32,'phone',302)
  with self.assertRaises(ValueError):self.p.approve(offer['pairingId'],'22'*32,303)
  self.p.approve(offer['pairingId'],'11'*32,303);self.assertIn(device['id'],self.store.devices)
  with self.assertRaises(ValueError):self.p.approve(offer['pairingId'],'11'*32,304)
  self.p.revoke(device['id']);self.assertEqual(self.store.devices,{})
 def test_parallel_claim_and_rejection(self):
  offer=self.p.begin_pairing(100)
  def claim(i):
   try:return self.p.claim(offer['pairingId'],offer['capability'],('%02x'%i)*32,'phone',101)
   except ValueError:return None
  with concurrent.futures.ThreadPoolExecutor() as pool:results=list(pool.map(claim,range(1,9)))
  self.assertEqual(sum(r is not None for r in results),1)
  self.p.reject(offer['pairingId'])
  with self.assertRaises(ValueError):self.p.approve(offer['pairingId'],next(r for r in results if r)['publicKey'],102)
if __name__=='__main__':unittest.main()
