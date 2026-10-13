import base64,html,mimetypes,re,zipfile
from pathlib import Path
from urllib.parse import unquote,urlsplit
from xml.etree import ElementTree as ET
LIMIT=20*1024*1024

def local_path(link):
 link=unquote(link.strip('<>'))
 if link.startswith('file://'):link=urlsplit(link).path
 link=re.sub(r':\d+(?::\d+)?$','',link)
 if not link.startswith('/'):raise ValueError('仅支持会话中的电脑文件链接')
 return Path(link).resolve()

def collect_links(value,allowed):
 if isinstance(value,str):
  for link in re.findall(r'\]\((<[^>]+>|[^\s)]+)\)',value):
   try:allowed.add(str(local_path(link)))
   except ValueError:pass
 elif isinstance(value,list):
  for v in value:collect_links(v,allowed)
 elif isinstance(value,dict):
  key='savedPath' if value.get('type')=='imageGeneration' else 'path'
  if value.get('type') in {'mention','skill','localImage','localAudio','imageView','imageGeneration'} and isinstance(value.get(key),str):
   try:allowed.add(str(local_path(value[key])))
   except ValueError:pass
  for v in value.values():collect_links(v,allowed)

def office_html(path):
 with zipfile.ZipFile(path) as z:
  names=z.namelist()
  selected=[n for n in names if n=='word/document.xml' or re.fullmatch(r'ppt/slides/slide\d+\.xml',n) or re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n)]
  if sum(z.getinfo(n).file_size for n in selected)+sum(z.getinfo(n).file_size for n in ['xl/sharedStrings.xml'] if n in names)>LIMIT:raise ValueError('文档展开后超过 20 MB 预览限制')
  selected.sort(key=lambda n:int(re.search(r'(\d+)\.xml$',n)[1]) if re.search(r'(\d+)\.xml$',n) else 0)
  shared=[]
  def xml(name):
   if z.getinfo(name).file_size>LIMIT:raise ValueError('文档展开后过大')
   return ET.fromstring(z.read(name))
  if 'xl/sharedStrings.xml' in names:
   shared=[''.join(n.itertext()) for n in xml('xl/sharedStrings.xml')]
  sections=[]
  for name in selected:
   root=xml(name)
   if name.startswith('xl/'):
    rows=[]
    for row in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
     cells=[]
     for cell in row:
      v=cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v');text=v.text if v is not None and v.text else ''.join(cell.itertext())
      if cell.get('t')=='s':text=shared[int(text)]
      cells.append('<td>'+html.escape(text)+'</td>')
     rows.append('<tr>'+''.join(cells)+'</tr>')
    sections.append('<h3>'+html.escape(name.split('/')[-1])+'</h3><table>'+''.join(rows)+'</table>')
   else:
    paragraphs=[]
    for node in root.iter():
     if node.tag.endswith('}p'):
      text=''.join(n.text or '' for n in node.iter() if n.tag.endswith('}t'))
      if text:paragraphs.append('<p>'+html.escape(text)+'</p>')
    sections.append(''.join(paragraphs))
  return ''.join(sections)

def read_preview(link,allowed):
 try:
  path=local_path(link)
  if str(path) not in allowed:raise ValueError('此文件没有出现在当前会话链接中，请重新打开所属会话')
  if not path.is_file():raise ValueError('电脑上的文件已不存在或不可读取')
  if path.stat().st_size>LIMIT:raise ValueError('文件超过 20 MB 预览限制')
  data=path.read_bytes()
  if len(data)>LIMIT:raise ValueError('文件超过 20 MB 预览限制')
  mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
  result={'name':path.name,'mime':mime,'size':len(data),'data':base64.b64encode(data).decode('ascii')}
  if path.suffix.lower() in {'.docx','.xlsx','.pptx'}:
   result['html']=office_html(path)[:1_000_000];result['note']='内容预览；复杂排版、图表和公式请使用原文件查看'
  elif path.suffix.lower() in {'.zip','.jar','.apk'}:
   with zipfile.ZipFile(path) as z:result['text']='\n'.join(f'{i.file_size:>10}  {i.filename}' for i in z.infolist()[:2000])
  elif mime.startswith('text/') or path.suffix.lower() in {'.kt','.py','.js','.ts','.tsx','.jsx','.go','.rs','.swift','.java','.sh','.log','.json','.xml','.yaml','.yml','.toml','.sql','.csv','.md','.txt'}:
   result['text']=data.decode('utf-8-sig',errors='replace')[:1_000_000]
   if len(data)>1_000_000:result['note']='大文件预览显示前 100 万字符，原文件可使用其他应用完整查看'
   result['mime']=mime if mime.startswith('text/') else 'text/plain'
  return result
 except (OSError,ValueError,zipfile.BadZipFile,ET.ParseError,IndexError) as e:return {'error':str(e)}
