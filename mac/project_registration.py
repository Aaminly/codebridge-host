"""Offline-only project metadata registration; never writes while desktop is running."""
import json,os,subprocess,tempfile,time,uuid
from pathlib import Path
from host_paths import PATHS

def desktop_running():
 result=subprocess.run(['pgrep','-f','^/Applications/ChatGPT.app/Contents/MacOS/'],capture_output=True)
 if result.returncode not in (0,1):raise RuntimeError('无法确认桌面是否退出')
 return result.returncode==0

def registration(state,path,name,project_id):
 root=Path(path).resolve(strict=True)
 if not root.is_dir():raise ValueError('请选择 Mac 上的文件夹')
 if not name.strip() or len(name)>200:raise ValueError('项目名称无效')
 result=json.loads(json.dumps(state))
 projects=result.setdefault('local-projects',{})
 if project_id in projects:
  if projects[project_id]['rootPaths']!=[str(root)]:raise ValueError('项目 ID 冲突')
  return result
 now=int(time.time()*1000)
 projects[project_id]={'id':project_id,'name':name.strip(),'rootPaths':[str(root)],'createdAt':now,'updatedAt':now}
 result['project-order']=[project_id]+[p for p in result.get('project-order',[]) if p!=project_id]
 return result

def atomic_write(path,data):
 fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def apply(path,folder,name,project_id,running=desktop_running):
 if running():raise RuntimeError('桌面仍在运行，未修改项目元数据')
 original=path.read_bytes();state=json.loads(original)
 updated=registration(state,folder,name,project_id)
 if updated==state:return None
 backup=path.with_name(path.name+'.mobile-backup-'+uuid.uuid4().hex)
 atomic_write(backup,original)
 # Refuse concurrent writers; the backup remains available even on refusal.
 if running() or path.read_bytes()!=original:raise RuntimeError('桌面状态发生变化，登记已取消')
 atomic_write(path,json.dumps(updated,ensure_ascii=False).encode())
 return backup

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('folder');parser.add_argument('name');parser.add_argument('--id',default=None)
 args=parser.parse_args()
 backup=apply(PATHS.state,args.folder,args.name,args.id or str(uuid.uuid4()))
 print('登记完成，备份：',backup)
