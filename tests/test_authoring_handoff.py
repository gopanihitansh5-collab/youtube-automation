"""Evidence and full text must survive every authoring handoff."""
import datetime
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'long-videos'))
import multi_llm_pipeline as mlp
import topic_context as tc
import longform_prompt as lp

class AuthoringTests(unittest.TestCase):
    def test_format_does_not_double_json_value_braces(self):
        source = json.dumps({'chapters': [{'scenes': [{'narration': 'Whole sentence.'}]}]})
        result = mlp._safe_format('INPUT: {source}', source=source)
        self.assertEqual(json.loads(result.removeprefix('INPUT: ')), json.loads(source))

    def test_stage1_keeps_hook_and_passes_review_findings(self):
        reply = json.dumps({'title':'Title','hook':'Why does this happen?', 'chapters':[{'paragraphs':['Full paragraph.']}], 'key_points':['Fact']})
        with mock.patch.object(mlp, '_call_free_llm', return_value=(reply, 'test')) as call:
            plan, _ = mlp.stage1_write_script('Topic', {'context_block':'SUPPLIED FACT'}, {'issue':'REPAIR THIS'})
        self.assertEqual(plan['hook'], 'Why does this happen?')
        self.assertIn('SUPPLIED FACT', call.call_args.args[0])
        self.assertIn('REPAIR THIS', call.call_args.args[0])

    def test_full_plan_tail_and_source_reach_required_gemini(self):
        plan = {'chapters':[{'scenes':[{'narration':'x' * 13000 + 'TAIL_UNCUT'}]}]}
        with mock.patch.object(mlp, '_call_gemini_review', return_value=(json.dumps(plan), 'test')) as call:
            mlp.stage5_final_review(plan, {'sources':['VERIFIED SOURCE URL']})
        self.assertIn('TAIL_UNCUT', call.call_args.args[0])
        self.assertIn('VERIFIED SOURCE URL', call.call_args.args[0])

    def test_gemini_failure_remains_failure(self):
        with mock.patch.object(mlp, '_call_gemini_review', side_effect=RuntimeError('quota')):
            with self.assertRaisesRegex(RuntimeError, 'Final Gemini review unavailable'):
                mlp.stage5_final_review({'chapters':[]})

    def test_fallback_prompt_keeps_context_block(self):
        with mock.patch.object(lp, '_save_memory'), mock.patch.object(lp, '_load_memory', return_value=[]):
            prompt, _ = lp.build_long_prompt('Topic', {'context_block':'EVIDENCE_BOUNDARY_123'})
        self.assertIn('EVIDENCE_BOUNDARY_123', prompt)
        self.assertIn('3-6 literal stock search words', prompt)

    def test_rewrite_rejects_missing_scenes(self):
        plan={'chapters':[{'scenes':[{'narration':'a'}, {'narration':'b'}]}]}
        reply=json.dumps({'chapters':[{'scenes':[{'narration':'a'}]}]})
        with mock.patch.object(mlp, '_call_free_llm', return_value=(reply,'test')):
            with self.assertRaisesRegex(ValueError, 'changed the scene structure'):
                mlp._rewrite_from_review(plan, {'passed':False}, {'sources':['source']})

    def test_verified_bundle_exact_match_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            bundle={'topic':'Exact Topic','verified_on':'2026-10-16','review_after_days':30,
                    'key_facts':['Supported fact'], 'sources':['https://example.com/verified']}
            pathlib.Path(d, 'topic.json').write_text(json.dumps(bundle))
            today=datetime.date(2026,10,16)
            ctx=tc.apply_verified_topic_evidence(tc.TopicContext('Exact Topic'), d, today)
            self.assertEqual(ctx.key_facts,['Supported fact'])
            self.assertFalse(tc.apply_verified_topic_evidence(tc.TopicContext('Other Topic'), d, today).key_facts)
            with self.assertRaisesRegex(ValueError, 're-verification'):
                tc.apply_verified_topic_evidence(tc.TopicContext('Exact Topic'), d, datetime.date(2027,1,1))

    def test_existing_facts_not_overwritten(self):
        ctx=tc.TopicContext('The Science of Sleep: Why We Dream',key_facts=['Live supplied fact'])
        self.assertEqual(tc.apply_verified_topic_evidence(ctx).key_facts,['Live supplied fact'])

    def test_new_diagnostics_in_artifacts_and_pass2_before_validation(self):
        workflow=(ROOT/'.github/workflows/daily-long-video.yml').read_text()
        for name in ['authoring_diagnostics.json','storyboard_script_raw.json']:
            self.assertIn(name,workflow)
        code=(ROOT/'long-videos/main_long.py').read_text().split('raw, model2 = call(prompt, 14000)')[1]
        self.assertLess(code.index('storyboard_script_raw.json'),code.index('_validate_long(raw, topic)'))

if __name__=='__main__': unittest.main()
