import pathlib,importlib.util,unittest,ast
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('claimreview',ROOT/'long-videos/reviewer_agents.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class ClaimContextTests(unittest.TestCase):
    def test_pacing_estimates_actual_words(self):
        with patch.object(r,'_call_reviewer',return_value=('{"pass":true,"score":8}', 'test-model')) as c:
            r.review_pacing([{'title':'T','scenes':[{'narration':'word '*50}]}]);prompt=c.call_args.args[0]
        self.assertIn('50 words, estimated 20.0s',prompt);self.assertIn('ESTIMATES ONLY',prompt);self.assertIn('150 words/minute',prompt)
    def test_safety_sees_claims_not_titles_only(self):
        text='Specific alleged claim in a complete sentence.'
        with patch.object(r,'_call_reviewer',return_value=('{"pass":true,"score":8}', 'test-model')) as c:
            r.review_safety('Title',[{'title':'Topic','scenes':[{'narration':text}]}]);self.assertIn(text,c.call_args.args[0]);self.assertIn('FULL SCRIPT CONTEXT',c.call_args.args[0])
    def test_safety_stage1_paragraph_context(self):
        with patch.object(r,'_call_reviewer',return_value=('{"pass":true,"score":8}', 'test-model')) as c:
            r.review_safety('T',[{'paragraphs':['Whole supplied paragraph.']}]);self.assertIn('Whole supplied paragraph.',c.call_args.args[0])
    def test_empty_timing_evidence_fails(self):
        self.assertFalse(r.review_pacing([{'scenes':[{'narration':None}]}])['passed'])
    def test_generation_constraints_added_to_both_paths(self):
        s=(ROOT/'long-videos/longform_prompt.py').read_text();self.assertIn('Do not invent citations, studies, memos, percentages',s);self.assertIn('prompt += "\\n\\n" + FACTUAL_GENERATION_RULE',s)
        s=(ROOT/'long-videos/multi_llm_pipeline.py').read_text();self.assertGreaterEqual(s.count('prompt += "\\n\\n" + FACTUAL_GENERATION_RULE'),5)
if __name__=='__main__':unittest.main()
