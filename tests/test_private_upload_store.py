import unittest,base64,json,os
from unittest.mock import Mock,patch
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.private_upload_store import PrivateGitHubStore
from src.upload_ledger import UploadConflict
class PrivateStoreTests(unittest.TestCase):
 def store(self):
  s=object.__new__(PrivateGitHubStore);s.entries={'a':{'state':'old'}};s.sha='revision';s.cipher=AESGCM(b'k'*32);s.aad=b'repo:branch:path';s.branch='private-upload-state';return s
 def test_missing_provisioning_disables_upload(self):
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(UploadConflict):PrivateGitHubStore()
 def test_stale_revision_blocks_write(self):
  s=self.store()
  with patch.object(s,'_read',return_value=({'a':{'state':'old'}},'new')),patch.object(s,'_request') as request:
   with self.assertRaises(UploadConflict):s.put('a',{'state':'mine'})
   request.assert_not_called()
 def test_conditional_ciphertext_write_and_readback(self):
  s=self.store();receipt={'session_uri':'PRIVATE SESSION URL','state':'mine'};new={'a':receipt};response=Mock(status_code=200);response.json.return_value={'content':{'sha':'next'}}
  with patch.object(s,'_read',side_effect=[({'a':{'state':'old'}},'revision'),(new,'next')]),patch.object(s,'_request',return_value=response) as request:
   s.put('a',receipt)
  body=request.call_args.kwargs['json'];self.assertEqual(body['sha'],'revision')
  envelope=json.loads(base64.b64decode(body['content']));self.assertNotIn('PRIVATE',json.dumps(envelope))
  plain=s.cipher.decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),s.aad)
  self.assertEqual(json.loads(plain),new);self.assertEqual(s.sha,'next')
 def test_initial_write_has_no_sha_and_conflict_stops(self):
  s=self.store();s.entries={};s.sha=None
  with patch.object(s,'_read',return_value=({},None)),patch.object(s,'_request',return_value=Mock(status_code=409)) as request:
   with self.assertRaises(UploadConflict):s.put('a',{})
  self.assertNotIn('sha',request.call_args.kwargs['json'])
 def test_tamper_fails_closed(self):
  s=self.store();env={'version':1,'nonce':base64.b64encode(b'n'*12).decode(),'ciphertext':base64.b64encode(b'bad').decode()}
  r=Mock(status_code=200);r.json.return_value={'sha':'a','encoding':'base64','content':base64.b64encode(json.dumps(env).encode()).decode()}
  with patch.object(s,'_request',return_value=r):
   with self.assertRaises(UploadConflict):s._read()
 def test_network_error_redacted(self):
  s=self.store();s.http=Mock();s.base='https://api.github.com';s.http.request.side_effect=RuntimeError('PRIVATE SESSION URL')
  with self.assertRaises(UploadConflict) as error:s._request('GET','/contents')
  self.assertNotIn('PRIVATE',str(error.exception))
 def test_processed_without_public_proof_holds(self):
  from src.youtube_upload import _verify_ready
  ledger=Mock();ledger.data={};svc=Mock();svc.videos.return_value.list.return_value.execute.return_value={'items':[{'status':{'uploadStatus':'processed','privacyStatus':'public'},'processingDetails':{'processingStatus':'succeeded'}}]}
  ledger.source_path='source.mp4'
  with patch('src.public_media_check.verify',side_effect=UploadConflict('public proof failed')):
   with self.assertRaises(UploadConflict):_verify_ready(svc,'video','public',ledger)
