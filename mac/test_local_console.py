import http.client,json,unittest
from urllib.parse import urlsplit
from local_console import start_console

class State:
 def __init__(self):self.actions=[]
 def status(self):return {'connected':False,'reason':'ambiguous'}
 def action(self,path,body):self.actions.append((path,body));return {'ok':True}
class ConsoleChecks(unittest.TestCase):
 def setUp(self):
  self.state=State();self.server=start_console(self.state);self.parts=urlsplit(self.server.url);self.cookie='';self.csrf=''
 def tearDown(self):self.server.shutdown()
 def request(self,method,path,body=None,headers=None):
  conn=http.client.HTTPConnection(self.parts.hostname,self.parts.port,timeout=3)
  h={'Origin':f'http://{self.parts.netloc}','Content-Type':'application/json','Cookie':self.cookie,'X-CSRF-Token':self.csrf};h.update(headers or {})
  conn.request(method,path,json.dumps(body) if body is not None else None,h);r=conn.getresponse();data=r.read();result=(r.status,dict(r.getheaders()),json.loads(data) if data and r.getheader('Content-Type','').startswith('application/json') else data);conn.close();return result
 def bootstrap(self):
  status,h,body=self.request('POST','/api/bootstrap',{'capability':self.parts.fragment.split('=')[1]})
  self.assertEqual(status,200);self.cookie=h['Set-Cookie'].split(';')[0];self.csrf=body['csrf'];self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
 def test_authenticated_flow_and_one_use_capability(self):
  self.assertEqual(self.request('GET','/api/status')[0],401)
  self.bootstrap();self.assertEqual(self.request('GET','/api/status')[2]['reason'],'ambiguous')
  self.assertEqual(self.request('POST','/api/pairings',{})[0],200)
  self.assertEqual(len(self.state.actions),1)
  self.assertEqual(self.request('POST','/api/bootstrap',{'capability':self.parts.fragment.split('=')[1]})[0],401)
 def test_authenticated_component_lifecycle_routes(self):
  self.bootstrap()
  self.assertEqual(self.request('POST','/api/autostart',{'enabled':True})[0],200)
  self.assertEqual(self.request('POST','/api/uninstall',{})[0],200)
 def test_desktop_setup_requires_the_owner_session_and_csrf(self):
  self.assertEqual(self.request('POST','/api/desktop/enable',{})[0],401)
  self.bootstrap()
  self.assertEqual(self.request('POST','/api/desktop/enable',{}, {'X-CSRF-Token':''})[0],403)
  self.assertEqual(self.state.actions,[])
  self.assertEqual(self.request('POST','/api/desktop/enable',{})[0],200)
 def test_trust_boundary_rejects_mutation(self):
  self.bootstrap()
  for h in [{'Host':'evil.example'},{'Origin':'https://evil.example'},{'X-CSRF-Token':''},{'Cookie':''},{'Origin':''}]:
   self.assertIn(self.request('POST','/api/pairings',{},h)[0],[401,403])
  self.assertEqual(self.request('OPTIONS','/api/pairings')[0],403)
  self.assertEqual(self.request('POST','/rpc',{})[0],404)
  self.assertEqual(self.state.actions,[])
 def test_expired_bootstrap_and_session(self):
  self.server.bootstrap_expires=0
  self.assertEqual(self.request('POST','/api/bootstrap',{'capability':self.parts.fragment.split('=')[1]})[0],401)
 def test_public_page_does_not_expose_secrets(self):
  status,h,body=self.request('GET','/');self.assertEqual(status,200)
  self.assertNotIn(self.parts.fragment.split('=')[1].encode(),body)
  self.assertIn('Content-Security-Policy',h)
if __name__=='__main__':unittest.main()
