import json,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from src.public_media_check import verify
from src.upload_ledger import UploadConflict
class PublicMediaTests(unittest.TestCase):
 def fake_run(self,args,**kw):
  if args[0]=='yt-dlp':Path(args[args.index('-o')+1]).write_bytes(b'media')
  if args[0]=='ffprobe':return Mock(stdout=json.dumps({'format':{'duration':'50'},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}).encode())
  if 'framemd5' in args:Path(args[-1]).write_text('# metadata\n0,0,0,1,1,hash1\n0,1,1,1,1,hash2\n')
  return Mock(stdout=b'')
 def test_valid_proof_records_decode_and_motion(self):
  with patch('src.public_media_check.subprocess.run',side_effect=self.fake_run):p=verify('abc','source.mp4')
  self.assertEqual(p['decoded_frame_hashes'],2);self.assertTrue(p['anonymous'])
 def test_mismatched_duration_stops(self):
  count=[0]
  def run(args,**kw):
   if args[0]=='ffprobe':
    count[0]+=1;return Mock(stdout=json.dumps({'format':{'duration': '50' if count[0]==1 else '70'},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}).encode())
   return self.fake_run(args,**kw)
  with patch('src.public_media_check.subprocess.run',side_effect=run):
   with self.assertRaises(UploadConflict):verify('abc','source.mp4')
 def test_network_errors_redacted(self):
  with patch('src.public_media_check.subprocess.run',side_effect=RuntimeError('PRIVATE')):
   with self.assertRaises(UploadConflict) as e:verify('abc','source.mp4')
  self.assertNotIn('PRIVATE',str(e.exception))
 def test_invalid_identity_stops(self):
  with self.assertRaises(UploadConflict):verify('../wrong','source.mp4')
