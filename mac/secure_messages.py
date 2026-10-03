"""Bounded framing inside Noise: ordering and lengths are authenticated."""
import struct,time
LIMIT=32*1024*1024
class Messages:
 def __init__(self):self.data=bytearray();self.total=0;self.started=0
 @staticmethod
 def frames(data):
  if not 0<len(data)<=LIMIT:raise ValueError('Message exceeds 32 MiB')
  for offset in range(0,len(data),60000):yield struct.pack('!II',len(data),offset)+data[offset:offset+60000]
 def read(self,frame):
  if not 8<len(frame)<=60008:raise ValueError('Invalid message frame')
  total,offset=struct.unpack('!II',frame[:8])
  if not 0<total<=LIMIT or offset!=len(self.data) or offset+len(frame)-8>total or (offset and (total!=self.total or time.monotonic()-self.started>120)):raise ValueError('Invalid message assembly')
  if offset==0:self.total=total;self.started=time.monotonic()
  self.data.extend(frame[8:])
  if len(self.data)==total:
   result=bytes(self.data);self.data.clear();self.total=0;return result
  return None
