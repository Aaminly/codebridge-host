"""Loopback-only configuration API. Never a general RPC or file proxy."""
import hmac,json,re,secrets,threading,time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

class ConsoleHandle:
 def __init__(self,server):
  self.server=server;self.capability=secrets.token_urlsafe(32);self.bootstrap_expires=time.monotonic()+60
  self.sessions={};self.lock=threading.Lock();self.origin=f'http://127.0.0.1:{server.server_port}'
  self.url=self.origin+'/#bootstrap='+self.capability
 def shutdown(self):self.server.shutdown();self.server.server_close()

def start_console(host_state,bind='127.0.0.1',port=0):
 if bind!='127.0.0.1':raise ValueError('Console must use IPv4 loopback')
 class Handler(BaseHTTPRequestHandler):
  def setup(self):super().setup();self.connection.settimeout(5)
  def log_message(self,*args):pass # No capability, cookie, path or payload logging.
  def reply(self,status,body,cookie=None,html=False):
   data=body if html else json.dumps(body,ensure_ascii=False).encode()
   self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
   self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
   self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
   self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
   if cookie:self.send_header('Set-Cookie',cookie)
   self.end_headers();self.wfile.write(data)
  def boundary(self,mutating=False):
   if self.headers.get_all('Host')!=[handle.origin.removeprefix('http://')]:
    self.reply(403,{'error':'Invalid host'});return False
   origins=self.headers.get_all('Origin') or []
   if (mutating and origins!=[handle.origin]) or (origins and origins!=[handle.origin]):
    self.reply(403,{'error':'Invalid origin'});return False
   return True
  def session(self,mutating=False):
   cookie=SimpleCookie()
   try:cookie.load(self.headers.get('Cookie',''))
   except Exception:self.reply(401,{'error':'Invalid session'});return None
   key=cookie.get('cb_session');session=handle.sessions.get(key.value if key else '')
   if session is None or session[1]<time.monotonic():self.reply(401,{'error':'Open configuration from CodeBridge'});return None
   if mutating and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session[0]):self.reply(403,{'error':'Invalid CSRF token'});return None
   return session
  def do_OPTIONS(self):self.reply(403,{'error':'Cross-origin access is disabled'})
  def do_GET(self):
   if not self.boundary():return
   if self.path=='/':self.reply(200,(Path(__file__).parent/'web/index.html').read_bytes(),html=True);return
   if self.path!='/api/status':self.reply(404,{'error':'Unknown route'});return
   if self.session():self.reply(200,host_state.status())
  def do_POST(self):
   if not self.boundary(True):return
   try:
    if self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding'):raise ValueError()
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=16384:raise ValueError()
    body=json.loads(self.rfile.read(length))
    if not isinstance(body,dict):raise ValueError()
   except (ValueError,OSError):self.reply(400,{'error':'Invalid request'});return
   if self.path=='/api/bootstrap':
    capability=body.get('capability')
    with handle.lock:
     if not isinstance(capability,str) or not handle.capability or time.monotonic()>handle.bootstrap_expires or not hmac.compare_digest(capability,handle.capability):self.reply(401,{'error':'Configuration link expired'});return
     handle.capability='';key=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
     handle.sessions={key:(csrf,time.monotonic()+28800)}
    self.reply(200,{'csrf':csrf},f'cb_session={key}; HttpOnly; SameSite=Strict; Path=/');return
   if not (self.path in ('/api/pairings','/api/autostart','/api/uninstall','/api/desktop/enable','/api/desktop/open') or re.fullmatch(r'/api/(?:pairings/[A-Za-z0-9_-]{1,80}/(?:approve|reject)|devices/[A-Za-z0-9_-]{1,80}/revoke)',self.path)):
    self.reply(404,{'error':'Unknown route'});return
   if not self.session(True):return
   try:self.reply(200,host_state.action(self.path,body))
   except (ValueError,RuntimeError,OSError) as e:self.reply(409,{'error':str(e) if isinstance(e,ValueError) else 'Action failed; no success confirmed'})
 server=ThreadingHTTPServer((bind,port),Handler);server.daemon_threads=True
 handle=ConsoleHandle(server)
 threading.Thread(target=server.serve_forever,name='codebridge-console',daemon=True).start()
 return handle
