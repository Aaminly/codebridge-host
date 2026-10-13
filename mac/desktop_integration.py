"""Owner-selected desktop startup adapter; never quits or edits the vendor app."""
import json,os,plistlib,subprocess,sys
from pathlib import Path
from host_paths import PATHS

def read():
 path=PATHS.host/'desktop.json'
 return json.loads(path.read_text()) if path.exists() else {}

def app_cli(app):
 app=app.resolve()
 info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
 if info.get('CFBundleIdentifier')!='com.openai.codex':raise ValueError('所选应用不是官方 Codex')
 subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True)
 signature=subprocess.run(['/usr/bin/codesign','-dv','--verbose=2',str(app)],check=True,capture_output=True,text=True)
 if 'TeamIdentifier=2DC432GLL2' not in signature.stderr:raise ValueError('无法确认 Codex 发行签名')
 for relative in ('Contents/Resources/codex','Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'):
  cli=app/relative
  if cli.is_file() and os.access(cli,os.X_OK):return cli
 raise ValueError('Codex 安装不完整，未找到原生连接程序')

def save(value):
 PATHS.host.mkdir(parents=True,exist_ok=True,mode=0o700)
 path=PATHS.host/'desktop.json';temporary=path.with_suffix('.tmp')
 with temporary.open('w') as out:temporary.chmod(0o600);json.dump(value,out)
 temporary.replace(path)

def enable():
 if not getattr(sys,'frozen',False):raise ValueError('请安装码桥 Mac 组件后启用桌面共享入口')
 wrapper=Path(sys.executable).resolve();roots=[Path('/Applications').resolve(),(PATHS.home/'Applications').resolve()]
 if not any(wrapper.is_relative_to(root) for root in roots):raise ValueError('请先将码桥移到应用程序目录，再启用共享入口')
 app=next((root/'Codex.app' for root in roots if (root/'Codex.app').is_dir()),None)
 if app is None:raise ValueError('请先安装官方独立 Codex App 到应用程序目录')
 cli=app_cli(app)
 save({'enabled':True,'app':str(app.resolve()),'cli':str(cli),'wrapper':str(wrapper)})
 return {'status':'configured','message':'请通过码桥打开 Codex；已有窗口和任务保持运行，下次启动时接入共享服务。'}

def open_desktop():
 value=read()
 if not value.get('enabled'):raise ValueError('请先启用桌面共享入口')
 app=Path(value['app']);app_cli(app)
 wrapper=Path(value['wrapper'])
 if not wrapper.is_file():raise ValueError('码桥组件已移动，请重新启用共享入口')
 subprocess.run(['/usr/bin/open','-a',str(app),'--env','CODEX_CLI_PATH='+str(wrapper)],check=True,capture_output=True)
 return {'status':'opening','message':'正在打开 Codex；已有窗口保持原状，任务不会被关闭。'}

def disable():
 value=read()
 if value:value['enabled']=False;save(value)
