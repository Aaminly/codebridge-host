"""Bounded APK transfer using the same authenticated chat-file allowlist."""
import base64,hashlib,os,secrets,stat
from file_preview import local_path
from lan_transfer import LOCAL
CHUNK=256*1024
MAX_SIZE=512*1024*1024
def fingerprint(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
class Downloads:
 def __init__(self):self.files={}
 def start(self,params,allowed):
  path=local_path(params.get('path',''))
  if str(path) not in allowed:raise ValueError('此文件没有出现在当前会话链接中，请重新打开所属会话')
  if path.suffix.lower()!='.apk':raise ValueError('此入口仅用于APK安装包')
  if len(self.files)>=4:raise ValueError('下载任务过多，请先结束已有下载')
  f=path.open('rb')
  try:
   s=os.fstat(f.fileno())
   if not stat.S_ISREG(s.st_mode) or not 0<s.st_size<=MAX_SIZE:raise ValueError('安装包为空或超过512MB下载限制')
   digest=hashlib.file_digest(f,'sha256').hexdigest();f.seek(0)
   if fingerprint(os.fstat(f.fileno()))!=fingerprint(s):raise ValueError('文件正在变化，请稍后重试')
   key=secrets.token_hex(16);self.files[key]=(f,s)
   result={'id':key,'name':path.name,'size':s.st_size,'sha256':digest}
   lan=LOCAL.offer(key,f,s)
   if lan:result['lan']=lan
   return result
  except BaseException:f.close();raise
 def chunk(self,params):
  key=params.get('id');item=self.files.get(key)
  if item is None:raise ValueError('下载已结束或连接已改变，请重新点击')
  f,s=item;offset=params.get('offset')
  if type(offset)!=int or not 0<=offset<s.st_size:raise ValueError('下载偏移无效')
  if fingerprint(os.fstat(f.fileno()))!=fingerprint(s):raise ValueError('文件已变化，请重新下载')
  f.seek(offset);data=f.read(min(CHUNK,s.st_size-offset))
  if not data:raise ValueError('文件读取中断')
  return {'offset':offset,'data':base64.b64encode(data).decode('ascii')}
 def end(self,params):
  LOCAL.revoke(params.get('id'));item=self.files.pop(params.get('id'),None)
  if item:item[0].close()
  return {'complete':True}
 def close(self):
  for key,(f,_) in self.files.items():LOCAL.revoke(key);f.close()
  self.files.clear()
