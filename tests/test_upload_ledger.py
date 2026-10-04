import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.upload_ledger import Ledger, RecordingHttp, UploadConflict
from src import youtube_upload as uploader

class UploadLedgerTests(unittest.TestCase):
    def setUp(self):
        self.remote=patch.object(uploader,'PrivateGitHubStore',return_value=None)
        self.remote.start();self.addCleanup(self.remote.stop)
    def setup_files(self, directory):
        p=Path(directory)/'final.mp4';p.write_bytes(b'media');return p

    def test_atomic_receipt_and_changed_hash_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_files(d);l=Ledger(p,'episode',d+'/receipts');l.save(video_id='id')
            self.assertEqual(Ledger(p,'episode',d+'/receipts').data['video_id'],'id')
            p.write_bytes(b'new media')
            with self.assertRaises(UploadConflict):Ledger(p,'episode',d+'/receipts')

    def test_session_saved_before_media(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_files(d);l=Ledger(p,'episode',d+'/receipts')
            response=Mock(status=200);response.__contains__=Mock(return_value=True);response.__getitem__=Mock(return_value='private-session')
            inner=Mock();inner.request.return_value=(response,b'')
            RecordingHttp(inner,l).request('uri')
            self.assertEqual(Ledger(p,'episode',d+'/receipts').data['session_uri'],'private-session')
            self.assertEqual(l.path.stat().st_mode & 0o777,0o600)

    def test_existing_id_never_inserts(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_files(d);l=Ledger(p,'ep',d+'/receipts');l.save(video_id='existing')
            svc=Mock()
            with patch.object(uploader,'_service',return_value=svc),patch.object(uploader,'_verify_ready'):
                self.assertEqual(uploader.upload(str(p),'title','desc',[],episode_id='ep',ledger_dir=d+'/receipts'),'https://youtu.be/existing')
            svc.videos.assert_not_called()

    def test_ambiguous_start_never_reinserts(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_files(d);l=Ledger(p,'ep',d+'/receipts');l.save(state='initiating')
            svc=Mock()
            with patch.object(uploader,'_service',return_value=svc),patch.object(uploader,'_reconcile_existing',side_effect=UploadConflict('unresolved')):
                with self.assertRaises(UploadConflict):uploader.upload(str(p),'title','desc',[],episode_id='ep',ledger_dir=d+'/receipts')
            svc.videos.assert_not_called()

    def test_pending_entity_not_done(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_files(d);l=Ledger(p,'ep',d+'/receipts');svc=Mock()
            svc.videos.return_value.list.return_value.execute.return_value={'items':[{'status':{'uploadStatus':'uploaded','privacyStatus':'public'},'processingDetails':{'processingStatus':'processing'}}]}
            with patch.object(uploader.time,'sleep'):
                with self.assertRaises(UploadConflict):uploader._verify_ready(svc,'id','public',l)
            self.assertNotEqual(l.data.get('state'),'processed')
