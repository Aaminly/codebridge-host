"""TLS-pinned, short-lived binary APK transfer advertised only over authenticated RPC."""
import asyncio,datetime,hashlib,hmac,ipaddress,json,os,re,secrets,ssl,subprocess,time
from pathlib import Path
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
class LanTransfer:
 def __init__(self):self.server=None;self.tickets={};self.addresses=[];self.pin='';self.port=0;self.start_lock=asyncio.Lock()
 async def start(self,base):
  async with self.start_lock:await self._start(base)
 async def _start(self,base):
  if self.server:return
  cert=base/'server.crt';key=base/'server.key'
  if not cert.exists() or not key.exists():
   from cryptography import x509
   from cryptography.hazmat.primitives import hashes,serialization
   from cryptography.hazmat.primitives.asymmetric import ec
   from cryptography.x509.oid import NameOID
   folder=base/'host-v2';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
   cert=folder/'lan.crt';key=folder/'lan.key'
   if not cert.exists() or not key.exists():
    private=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'CodeBridge local transfer')]);now=datetime.datetime.now(datetime.timezone.utc)
    certificate=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=3650)).sign(private,hashes.SHA256())
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM));cert.chmod(0o600)
  self.pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key)
  self.server=await serve(self.handle,'0.0.0.0',0,ssl=context,process_request=self.authorize,max_size=1024,write_limit=256*1024,ping_interval=20)
  self.port=self.server.sockets[0].getsockname()[1]
 def addresses_now(self):
  text=subprocess.check_output(['/sbin/ifconfig'],text=True);addresses=[];interface=''
  for line in text.splitlines():
   if line and not line[0].isspace():interface=line.split(':')[0]
   match=re.match(r'\s+inet (\d+\.\d+\.\d+\.\d+)\b',line)
   if match and not interface.startswith(('lo','utun','ipsec')):
    address=ipaddress.ip_address(match[1])
    if any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):addresses.append(str(address))
  return list(dict.fromkeys(addresses))[:6]
 def offer(self,owner,f,s):
  if not self.server:return None
  addresses=self.addresses_now()
  if not addresses:return None
  ticket=secrets.token_urlsafe(32);self.tickets[ticket]=(owner,f,s,time.monotonic()+120)
  return {'addresses':addresses,'port':self.port,'certificateSha256':self.pin,'ticket':ticket}
 def revoke(self,owner):
  for key,item in list(self.tickets.items()):
   if item[0]==owner or time.monotonic()>item[3]:self.tickets.pop(key,None)
 def authorize(self,conn,req):
  token=req.headers.get('Authorization','').removeprefix('Bearer ')
  item=self.tickets.get(token)
  if req.path!='/apk' or item is None or time.monotonic()>item[3]:return conn.respond(401,'Transfer authorization expired\n')
 async def handle(self,ws):
  token=ws.request.headers.get('Authorization','').removeprefix('Bearer ');item=self.tickets.pop(token,None)
  if item is None or time.monotonic()>item[3]:await ws.close(1008,'Transfer authorization expired');return
  _,f,s,_=item
  try:
   from file_download import fingerprint
   offset=0
   while offset<s.st_size:
    if f.closed or fingerprint(os.fstat(f.fileno()))!=fingerprint(s):raise ValueError('File changed')
    data=await asyncio.to_thread(os.pread,f.fileno(),min(64*1024,s.st_size-offset),offset)
    if not data:raise ValueError('File truncated')
    await ws.send(data);offset+=len(data)
   await ws.send(json.dumps({'complete':True}));await ws.close(1000,'Complete')
  except (OSError,ValueError,ConnectionClosed):await ws.close(1011,'File changed or unavailable')
 async def close(self):
  self.tickets.clear()
  if self.server:self.server.close();await self.server.wait_closed();self.server=None
LOCAL=LanTransfer()
