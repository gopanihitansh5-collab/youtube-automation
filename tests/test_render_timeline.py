import importlib.util,unittest,tempfile,os
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('editor_timeline','long-videos/editor_long.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
class TimelineTests(unittest.TestCase):
 def test_measured_boundaries_include_cards(self):
  with patch.object(e,'probe_duration',side_effect=[3,10,5,3,7]):
   t=e.measured_timeline([{'title':'a','scenes':[{},{}]},{'title':'b','scenes':[{}]}],['c0','c1'],['s0','s1','s2'])
  self.assertEqual(t['duration_sec'],28);self.assertEqual(t['chapters'][1]['start_sec'],18)
  self.assertEqual(t['chapters'][0]['scenes'][1]['start_sec'],13)
 def test_caption_offset_matches_rendered_scene(self):
  t={'chapters':[{'start_sec':0,'card_duration_sec':3,'scenes':[{'start_sec':3},{'start_sec':13}]}]}
  with tempfile.TemporaryDirectory() as d:
   p=e._write_ass([[[('hello',0,1)],[],]],[[10,5]],os.path.join(d,'captions.ass'),timeline=t)
   with open(p) as f:self.assertIn('0:00:03.00,0:00:04.00',f.read())
 def test_missing_measured_metadata_rejected(self):
  with self.assertRaises(ValueError):e._build_metadata([], 'a','b',[])
 def test_measured_metadata_not_plan_grid(self):
  t={'chapters':[{'title':'a','start_sec':0,'end_sec':18},{'title':'b','start_sec':18,'end_sec':28}]}
  with tempfile.TemporaryDirectory() as d:
   cwd=os.getcwd();os.chdir(d)
   try:
    p=e._build_metadata([{'timestamp_sec':600}],'title','text\nmore',[],timeline=t)
    with open(p) as f:s=f.read()
    self.assertIn('START=18000',s);self.assertNotIn('600000',s);self.assertIn('END=28000',s)
   finally:os.chdir(cwd)
