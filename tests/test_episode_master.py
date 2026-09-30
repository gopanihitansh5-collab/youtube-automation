import importlib.util
import sys
import types
from pathlib import Path
import unittest
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('src');pkg.__path__=[str(ROOT/'src')];sys.modules.setdefault('src',pkg)
from src.episode_master import SheetLedger, QueueBlocked, PrivateBank, verify_channel, verify_uploaded, commit_master, reconcile_known_upload, run_managed_episode
from src.episode_queue import BASE_HEADERS, MANAGED_HEADERS

class Request:
 def __init__(self,value):self.value=value
 def execute(self):return self.value
class Youtube:
 def __init__(self,channel='channel',privacy='public'):self.channel=channel;self.privacy=privacy
 def channels(self):return self
 def videos(self):return self
 def list(self,**kwargs):
  if 'mine' in kwargs:return Request({'items':[{'id':self.channel}]})
  return Request({'items':[{'snippet':{'channelId':self.channel,'title':'Title','description':'Description','tags':['tag']},'status':{'privacyStatus':self.privacy,'uploadStatus':'processed'}}]})
class Worksheet:
 def __init__(self,row):
  self.header=list(BASE_HEADERS+MANAGED_HEADERS)+['youtube_video_id','upload_attempt_id','upload_started_at'];self.row=[row.get(k,'') for k in self.header];self.writes=0;self.fail=False
 def get_all_values(self):return [self.header,self.row]
 def update(self,values,**kwargs):
  self.writes+=1
  if self.fail:raise RuntimeError('fake write failed')
  self.row=values[0]

class MasterTests(unittest.TestCase):
 def setUp(self):
  self.row={'episode_id':'e1','topic':'T','voice':'af_heart','privacy':'public','status':'ready_to_publish','type':'short','publish_at':'2026-10-02T05:30:00+05:30','timezone':'Asia/Calcutta','manifest_ref':'file','manifest_sha256':'a'*64,'master_sha256':'b'*64}
  self.manifest={'channel_id':'channel','metadata':{'title':'Title','description':'Description','tags':['tag']}}
  self.now=datetime(2026,10,2,tzinfo=timezone.utc);self.ws=Worksheet(self.row);self.ledger=SheetLedger(self.ws)
 def test_upload_success_has_verified_intent_id_readback(self):
  seen=[]
  def uploader(*args):seen.append(self.ledger.read('e1')[2]['status']);return 'abcdef12345'
  self.assertEqual(commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(),self.now,uploader),'abcdef12345')
  self.assertEqual(seen,['uploading']);live=self.ledger.read('e1')[2];self.assertEqual(live['status'],'posted');self.assertEqual(live['youtube_video_id'],'abcdef12345');self.assertEqual(self.ws.writes,3)
 def test_insert_failure_never_retries(self):
  count=[]
  def uploader(*args):count.append(1);raise RuntimeError('ambiguous network')
  with self.assertRaises(RuntimeError):commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(),self.now,uploader)
  self.assertEqual(count,[1]);self.assertEqual(self.ledger.read('e1')[2]['status'],'uploading')
  with self.assertRaises(QueueBlocked):reconcile_known_upload(self.ledger,self.row,self.manifest,Youtube(),self.now)
 def test_mismatch_retains_id_for_reconcile(self):
  with self.assertRaises(QueueBlocked):commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(privacy='private'),self.now,lambda *a:'abcdef12345')
  live=self.ledger.read('e1')[2];self.assertEqual(live['status'],'uploading');self.assertEqual(live['youtube_video_id'],'abcdef12345')
  self.assertEqual(reconcile_known_upload(self.ledger,self.row,self.manifest,Youtube(),self.now),'abcdef12345')
 def test_wrong_channel_blocks_before_intent(self):
  with self.assertRaises(QueueBlocked):commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(channel='wrong'),self.now,lambda *a:'abcdef12345')
  self.assertEqual(self.ws.writes,0)
 def test_early_blocks_before_intent(self):
  with self.assertRaises(QueueBlocked):commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(),datetime(2026,10,1,tzinfo=timezone.utc),lambda *a:'abcdef12345')
  self.assertEqual(self.ws.writes,0)
 def test_changed_binding_blocks(self):
  self.ws.row[self.ws.header.index('master_sha256')]='c'*64
  with self.assertRaises(QueueBlocked):self.ledger.transition(self.row,'ready_to_publish',{'status':'uploading'})
  self.assertEqual(self.ws.writes,0)
 def test_failed_intent_blocks_insert(self):
  self.ws.fail=True;calls=[]
  with self.assertRaises(RuntimeError):commit_master(self.ledger,self.row,self.manifest,'fake',Youtube(),self.now,lambda *a:calls.append(1))
  self.assertEqual(calls,[])
 def test_activation_always_held(self):
  with self.assertRaisesRegex(QueueBlocked,'activation_pending'):run_managed_episode(self.row)
 def test_bank_missing(self):
  with self.assertRaises(QueueBlocked):PrivateBank(None,'')
 def test_public_permission_blocked(self):
  class Drive:
   def permissions(self):return self
   def list(self,**kw):return Request({'permissions':[{'type':'anyone','role':'reader'}]})
  with self.assertRaises(QueueBlocked):PrivateBank(Drive(),'folder')._private('file')

if __name__=='__main__':unittest.main()
