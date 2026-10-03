import unittest
from secure_messages import Messages
class MessageChecks(unittest.TestCase):
 def test_chunked_roundtrip_and_bounds(self):
  m=Messages();data=b'x'*150000;parts=list(Messages.frames(data));self.assertGreater(len(parts),1)
  result=None
  for p in parts:result=m.read(p)
  self.assertEqual(result,data)
  for value in [parts[1],b'short',b'\xff'*8]:
   with self.assertRaises(ValueError):Messages().read(value)
  with self.assertRaises(ValueError):list(Messages.frames(b'x'*(32*1024*1024+1)))
if __name__=='__main__':unittest.main()
