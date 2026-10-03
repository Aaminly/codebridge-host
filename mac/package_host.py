"""Build a self-contained developer app. Signing/notarization is a release step."""
import argparse,json,subprocess,sys
from urllib.parse import urlsplit
from pathlib import Path

def main():
 root=Path(__file__).resolve().parent
 destination=root.parent/'qa/host-build'
 parser=argparse.ArgumentParser();parser.add_argument('--relay-origin');args=parser.parse_args();extra=[part for name in ('noiseprotocol','cryptography','qrcode','Pillow','websockets') for part in ('--copy-metadata',name)]
 if args.relay_origin:
  origin=urlsplit(args.relay_origin)
  if origin.scheme!='https' or not origin.hostname or origin.username or origin.query or origin.fragment or origin.path not in ('','/'):
   parser.error('Relay origin must be an HTTPS origin')
  destination.mkdir(parents=True,exist_ok=True);config=destination/'release_relay.json';config.write_text(json.dumps({'origin':args.relay_origin.rstrip('/')}));extra+=['--add-data',str(config)+':.']
 subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name','CodeBridge Host','--osx-bundle-identifier','dev.codebridge.host','--distpath',str(destination/'dist'),'--workpath',str(destination/'work'),'--specpath',str(destination),'--add-data',str(root/'web')+':web',*extra,str(root/'host.py')],check=True)
 import plistlib
 info=destination/'dist/CodeBridge Host.app/Contents/Info.plist'
 data=plistlib.loads(info.read_bytes());data['LSUIElement']=True;info.write_bytes(plistlib.dumps(data))
 # Changing Info.plist invalidates the build's ad-hoc signature; restore it for local execution.
 subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(destination/'dist/CodeBridge Host.app')],check=True)
if __name__=='__main__':main()
