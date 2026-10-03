"""Chunked uploads from the authenticated paired phone; never accepts a destination path."""
import base64,hashlib,re,uuid
from pathlib import Path
from host_paths import PATHS
ROOT=PATHS.base/'mobile-attachments'
LIMIT=20*1024*1024
class Uploads:
 def __init__(self):self.pending={}
 def start(self,p):
  key=str(uuid.UUID(p['id']));name=p['name'];size=p['size'];digest=p['sha256']
  if not isinstance(name,str) or not name or len(name)>200 or '/' in name or '\\' in name or name in {'.','..','.upload.part'} or any(ord(c)<32 for c in name):raise ValueError('文件名无效')
  if not isinstance(size,int) or not 0<=size<=LIMIT or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('文件超过 20 MB 或校验信息无效')
  folder=ROOT.resolve()/key;folder.mkdir(parents=True,exist_ok=True,mode=0o700);path=folder/name
  if path.exists():
   if path.stat().st_size==size and hashlib.sha256(path.read_bytes()).hexdigest()==digest:return {'path':str(path),'complete':True}
   raise ValueError('附件标识已被其他文件使用')
  partial=folder/'.upload.part';partial.write_bytes(b'');partial.chmod(0o600)
  self.pending[key]=(path,partial,size,digest);return {'id':key,'offset':0}
 def chunk(self,p):
  key=p['id'];path,partial,size,digest=self.pending[key]
  data=base64.b64decode(p['data'],validate=True)
  if len(data)>256*1024 or p['offset']!=partial.stat().st_size or partial.stat().st_size+len(data)>size:raise ValueError('附件分片顺序或大小无效')
  with partial.open('ab') as f:f.write(data)
  offset=partial.stat().st_size
  if offset==size:
   if hashlib.sha256(partial.read_bytes()).hexdigest()!=digest:raise ValueError('附件校验失败')
   partial.replace(path);self.pending.pop(key);return {'path':str(path),'complete':True}
  return {'offset':offset}
 def close(self):
  for _,partial,_,_ in self.pending.values():partial.unlink(missing_ok=True)

def browse(p):
 import mimetypes
 path=Path(p.get('path') or Path.home()).resolve(strict=True)
 if not path.is_dir():raise ValueError('请选择文件夹')
 media=p.get('media',False)
 entries=[]
 for file in sorted(path.iterdir(),key=lambda x:(not x.is_dir(),x.name.casefold())):
  if file.name.startswith('.') or not (file.is_dir() or file.is_file()):continue
  mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
  if media and file.is_file() and not mime.startswith(('image/','video/')):continue
  entries.append({'name':file.name,'path':str(file),'directory':file.is_dir(),'size':file.stat().st_size,'mime':mime})
 return {'path':str(path),'parent':str(path.parent),'folders':entries}
def select(p,allowed):
 import mimetypes
 path=Path(p['path']).resolve(strict=True)
 if str(path) not in allowed or not path.is_file():raise ValueError('请先浏览并选择此文件')
 if path.stat().st_size>LIMIT:raise ValueError('单个文件不能超过 20 MB')
 return {'id':str(uuid.uuid4()),'name':path.name,'size':path.stat().st_size,'remote':str(path),'local':'','mime':mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}
