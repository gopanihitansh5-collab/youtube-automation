import pathlib,importlib.util,json,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,file):
 s=importlib.util.spec_from_file_location(name,ROOT/'long-videos'/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
r=load('residualreview','reviewer_agents.py');l=load('residuallong','longform_prompt.py')
class ResidualTests(unittest.TestCase):
 def test_paragraph_context(self):
  c=r._script_context([{'paragraphs':['Complete first paragraph.','Whole second paragraph.']}]);self.assertIn('all 2 complete paragraphs',c)
 def test_paragraph_omissions(self):
  c=r._script_context([{'paragraphs':['Short.','Long '*100]}],limit=90);self.assertIn('EXPLICIT SAMPLE',c)
 def test_stage1_only_applicable_reviewers(self):
  good={'passed':True,'score':9,'model':'test'}
  with patch.object(r,'review_script',return_value=good),patch.object(r,'review_safety',return_value=good),patch.object(r,'review_scenes_unique',side_effect=AssertionError('not applicable')):
   result=r.run_all_reviewers('T','H',[{'paragraphs':['Whole paragraph.']}],parallel=False,paragraph_stage=True)
  self.assertTrue(result['all_passed']);self.assertEqual(set(result['results']),{'script','safety'})
 def test_final_still_five(self):
  good={'passed':True,'score':9,'model':'test'}
  with patch.object(r,'review_script',return_value=good),patch.object(r,'review_safety',return_value=good),patch.object(r,'review_scenes_unique',return_value={'passed':False}),patch.object(r,'review_visual_feasibility',return_value=good),patch.object(r,'review_pacing',return_value=good):
   self.assertFalse(r.run_all_reviewers('T','H',[],parallel=False)['all_passed'])
 def test_evidence_rubric(self):
  with patch.object(r,'_call_reviewer',return_value=(json.dumps({'pass':True,'score':9}),'test')) as c:
   r.review_script('T','H',[{'paragraphs':['Useful qualitative explanation.']}],{'sources':[]})
  self.assertIn('Qualitative content can earn full credit',c.call_args.args[0]);self.assertIn('sources',c.call_args.args[0])
 def test_pacing_contradiction_fails_closed(self):
  with patch.object(r,'_call_reviewer',return_value=(json.dumps({'pass':True,'score':8,'issues':['All 2 scenes are under 15 seconds']}),'test')):
   result=r.review_pacing([{'scenes':[{'narration':'word '*16},{'narration':'word '*42}]}])
  self.assertFalse(result['passed'])
 def test_pacing_exact_counts(self):
  with patch.object(r,'_call_reviewer',return_value=(json.dumps({'pass':True,'score':8,'estimated_total_sec':999}),'test')):
   result=r.review_pacing([{'scenes':[{'narration':'word '*16},{'narration':'word '*42}]}])
  self.assertEqual(result['timing_estimates']['under_15s'],1);self.assertEqual(result['timing_estimates']['max_sec'],16.8);self.assertEqual(result['estimated_total_sec'],23)
 def test_offline_no_duplicates_or_fabricated_research(self):
  for _ in range(5):
   p=l.build_offline_long_script('Persuasion',{'num_chapters':6,'scenes_per_chapter':8});ns=[s['narration'] for c in p['chapters'] for s in c['scenes']];self.assertEqual(len(ns),len(set(ns)));text=' '.join(ns).lower();self.assertNotIn('data reveals',text);self.assertNotIn('experts',text);self.assertIn('offline preparation',text)
 def test_offline_overflow_refuses_repeat(self):
  with self.assertRaises(ValueError):l.build_offline_long_script('T',{'num_chapters':9,'scenes_per_chapter':8})
if __name__=='__main__':unittest.main()
