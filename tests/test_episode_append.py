import sys,types
from pathlib import Path
import unittest
p=Path(__file__).resolve().parents[1];pkg=types.ModuleType('src');pkg.__path__=[str(p/'src')];sys.modules.setdefault('src',pkg)
from src.episode_append import *

class AppendTests(unittest.TestCase):
 def setUp(self):
  self.r={'episode_id':'e1','topic':'Exact topic','publish_at':'2026-10-02T12:00:00+05:30','timezone':'Asia/Calcutta','voice':'af_heart','source_urls':['https://example.invalid/source'],'caveats_source_notes':'Check current source','privacy':'private','status':'production_hold','script_title':'Title','script_tags':'tag','script_hook':'hook','master_artifact_id':None,'master_url':None}
  self.v=[list(BASE_HEADERS),['old','voice','public','done','url','date','title','desc','tag','hook']]
 def test_held_empty_master_and_schema_preserved(self):
  h,rows,n=plan_append(self.v,[self.r]);self.assertEqual(h[:10],list(BASE_HEADERS));r=dict(zip(h,rows[0]));self.assertEqual(r['status'],'production_hold');self.assertEqual(r['type'],'short');self.assertEqual(r['manifest_ref'],'')
 def test_idempotent_does_not_reset_progress(self):
  h,rows,n=plan_append(self.v,[self.r]);rows[0][h.index('status')]='awaiting_review';_,again,same=plan_append([h]+self.v[1:]+rows,[self.r]);self.assertEqual((again,same),([],1))
 def test_conflict_rejected(self):
  h,rows,n=plan_append(self.v,[self.r]);changed=dict(self.r,topic='new')
  with self.assertRaises(QueueBlocked):plan_append([h]+rows,[changed])
 def test_bad_shape_count_type_date_duplicate(self):
  for records in ([],[self.r]*4,[self.r,self.r],[dict(self.r,status='ready_to_publish')],[dict(self.r,publish_at='2026-10-02')],[dict(self.r,voice='other')]):
   with self.subTest(records=records),self.assertRaises(QueueBlocked):plan_append(self.v,records)
 def test_dry_run_no_mutation(self):
  class W:
   def get_all_values(w):return self.v
  out=append_held(W(),[self.r]);self.assertEqual(out['status'],'dry_run');self.assertEqual(out['append_count'],1)
 def test_existing_duplicates_rejected(self):
  h,rows,n=plan_append(self.v,[self.r])
  with self.assertRaises(QueueBlocked):plan_append([h]+rows+rows,[self.r])
if __name__=='__main__':unittest.main()
