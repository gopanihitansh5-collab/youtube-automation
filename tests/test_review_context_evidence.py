import importlib.util
import pathlib
import unittest
import tempfile
import os
import json
import ast
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reviewers_context',ROOT/'long-videos/reviewer_agents.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class ContextTests(unittest.TestCase):
    def test_full_context_not_sliced(self):
        narration='A complete scene with more than 150 characters. '*8
        chapters=[{'title':'Title','scenes':[{'narration':narration}]}]*5
        text=r._script_context(chapters)
        self.assertIn('FULL SCRIPT CONTEXT',text);self.assertEqual(text.count(narration.strip()),5)
    def test_cap_labels_omission_preserves_whole_scenes(self):
        text=r._script_context([{'scenes':[{'narration':'Complete scene one.'},{'narration':'Complete scene two.'}]}],limit=50)
        self.assertIn('EXPLICIT SAMPLE',text);self.assertIn('Complete scene one.',text);self.assertNotIn('Complete scene two.',text)
    def test_empty_reply_clear_failure(self):
        for value in [None,'',{},7]:
            with self.assertRaises(ValueError):r._extract_json(value)
        with patch.object(r,'_call_reviewer',return_value=(None,'test-model')):
            self.assertFalse(r.review_scenes_unique([{'scenes':[{'keyword':'desk'}]}])['passed'])
    def test_missing_keyword_fails_not_crashes(self):
        self.assertFalse(r.review_scenes_unique([{'scenes':[{'keyword':None}]}])['passed'])
    def test_rejected_evidence_exact_private_payload(self):
        tree=ast.parse((ROOT/'long-videos/main_long.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_save_rejected_plan');ctx={'os':os,'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),'main','exec'),ctx)
        with tempfile.TemporaryDirectory() as d:
            old=os.getcwd();os.chdir(d)
            try:
                plan={'chapters':[{'scenes':[{'narration':'Keep every word.'}]}]};ctx['_save_rejected_plan'](plan,'Topic','model','quality','repetition');data=json.load(open('output_long/rejected_plan.json'));self.assertEqual(data['plan'],plan);self.assertEqual(data['status'],'rejected_not_rendered_or_uploaded')
            finally:os.chdir(old)
    def test_artifact_and_gate_order(self):
        main=(ROOT/'long-videos/main_long.py').read_text();self.assertIn('_save_rejected_plan(plan, topic, llm_used, "review", review)',main);self.assertIn('_save_rejected_plan(plan, topic, llm_used, "quality", why)',main);self.assertIn('output_long/rejected_plan.json',(ROOT/'.github/workflows/daily-long-video.yml').read_text())
if __name__=='__main__':unittest.main()
