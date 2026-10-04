"""Offline regression tests. No credentials or provider calls required."""
import ast
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reviewer_agents', ROOT / 'long-videos/reviewer_agents.py')
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def function(path, name, context):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), context)
    return context[name]


class FailClosedTests(unittest.TestCase):
    chapters = [{'title': 'Example', 'scenes': [{'narration': 'One sentence.', 'keyword': 'desk'}]}]

    def review_calls(self):
        return [lambda: reviewer.review_script('T', 'H', self.chapters),
                lambda: reviewer.review_scenes_unique(self.chapters),
                lambda: reviewer.review_safety('T', self.chapters),
                lambda: reviewer.review_visual_feasibility(self.chapters),
                lambda: reviewer.review_pacing(self.chapters)]

    def test_unavailable_and_malformed_fail_each_reviewer(self):
        for payload in [None, 'not json', '{}', '{"pass":"true","score":8}', '{"pass":true}', '{"pass":true,"score":11}']:
            with patch.object(reviewer, '_call_reviewer') as call:
                if payload is None:
                    call.side_effect = RuntimeError('404')
                else:
                    call.return_value = (payload, 'test-model')
                for run in self.review_calls():
                    self.assertIs(run()['passed'], False)

    def test_good_evidence_passes(self):
        with patch.object(reviewer, '_call_reviewer', return_value=('{"pass":true,"score":8}', 'test-model')):
            self.assertTrue(reviewer.run_all_reviewers('T', 'H', self.chapters, parallel=False)['all_passed'])

    def test_missing_review_fails_aggregate(self):
        with patch.object(reviewer, 'review_script', side_effect=RuntimeError('lost')):
            with patch.object(reviewer, '_call_reviewer', return_value=('{"pass":true,"score":8}', 'test-model')):
                self.assertFalse(reviewer.run_all_reviewers('T', 'H', self.chapters, parallel=False)['all_passed'])

    def test_no_visual_data_fails(self):
        self.assertFalse(reviewer.review_scenes_unique([])['passed'])
        self.assertFalse(reviewer.review_visual_feasibility([])['passed'])

    def test_pipeline_wrapper_exception_fails(self):
        f = function(ROOT/'long-videos/multi_llm_pipeline.py', '_run_reviewers', {})
        with patch.dict(sys.modules, {'reviewer_agents': reviewer}):
            with patch.object(reviewer, 'run_all_reviewers', side_effect=RuntimeError('404')):
                self.assertEqual(f('T','H',self.chapters,'final'), (False, {}))

    def test_gemini_unavailable_is_not_a_reviewed_plan(self):
        def fail(*a, **k): raise RuntimeError('429')
        import json
        f = function(ROOT/'long-videos/multi_llm_pipeline.py', 'stage5_final_review',
                     {'FACTUAL_GENERATION_RULE':'No invented facts.','json':json,'STAGE5_PROMPT':'{plan_json}', '_safe_format':lambda s, **k:s.format(**k), '_call_gemini_review':fail})
        with self.assertRaises(RuntimeError): f({'chapters': self.chapters})

    def test_gate_and_cache_order(self):
        source = (ROOT/'long-videos/main_long.py').read_text()
        self.assertLess(source.index('if not review_ok:'), source.index('sheets.write_script_metadata(item, plan)'))
        start = source.index('    if not ok:\n', source.index('ok, why = quality_gate.check'))
        block = source[start:source.index('    print(f"  quality gate:', start)]
        self.assertIn('clear_cache()', block)
        self.assertIn('clear_stages(topic)', block)
        start = source.index('if os.environ.get("FRESH_SCRIPT")')
        block = source[start:source.index('    # Check if we already', start)]
        self.assertIn('cached_for_reset.get("topic") == topic', block)
        self.assertIn('clear_stages(topic)', block)
        workflow = (ROOT/'.github/workflows/daily-long-video.yml').read_text()
        self.assertIn('fresh_script:', workflow)
        self.assertIn('inputs.fresh_script', workflow)

if __name__ == '__main__': unittest.main()
