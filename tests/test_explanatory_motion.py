"""Typed scene contracts, real measured-duration render, and bounded repairs."""
import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'long-videos'))
from src import explanatory_motion as motion
from src.providers import visuals
import multi_llm_pipeline as mlp
import reviewer_agents as reviewers
import editor_long as editor

SPEC = {'title': 'Sleep changes through the night',
        'nodes': ['Light non-REM', 'Deep non-REM', 'REM'],
        'edges': [{'from': 0, 'to': 1, 'label': 'Stage change'},
                  {'from': 1, 'to': 2, 'label': 'Later in the cycle'}],
        'steps': [{'caption': 'Sleep moves through stages; the brain does not simply switch off.', 'highlight': [0]},
                  {'caption': 'Deep non-REM sleep is more common early in the night.', 'highlight': [1], 'edge': 0},
                  {'caption': 'REM sleep becomes more common later in the night.', 'highlight': [2], 'edge': 1}]}


def scene():
    return {'scene_id': 'sleep-1', 'narration': 'Sleep changes through stages, with more deep sleep early and REM later.',
            'keyword': 'person sleeping in bedroom', 'visual_type': 'authored_diagram',
            'diagram_description': 'Highlight sleep stage labels in order; no measured waveform or clock scale.',
            'diagram_spec': copy.deepcopy(SPEC), 'production_brief': 'Navy/gold schematic; advance each state in spoken order.',
            'visual_source_notes': 'Original qualitative illustration, not an EEG or measured hypnogram. NINDS sleep education.'}


class MotionTests(unittest.TestCase):
    def test_structured_contract_is_required_no_stock_disguise(self):
        good = scene()
        self.assertEqual(motion.validate_scene(good), 'authored_diagram')
        for bad in [dict(good, diagram_spec=None), dict(good, visual_type='stock'),
                    dict(good, visual_source_notes=''), dict(good, visual_type='brain_scan')]:
            with self.assertRaises(ValueError): motion.validate_scene(bad)

    def test_invalid_indices_and_degenerate_states_rejected(self):
        for path in ['edge', 'highlight', 'states', 'label', 'duplicate', 'boolean']:
            s = copy.deepcopy(SPEC)
            if path == 'edge': s['edges'][0]['to'] = 99
            if path == 'highlight': s['steps'][0]['highlight'] = [-1]
            if path == 'states': s['steps'] = [s['steps'][0], s['steps'][0]]
            if path == 'label': s['nodes'][0] = 'x' * 33
            if path == 'duplicate': s['nodes'][1] = s['nodes'][0]
            if path == 'boolean': s['edges'][0]['from'] = True
            with self.assertRaises(ValueError): motion.validate_spec(s)

    def test_original_lane_never_calls_stock_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(visuals, '_pexels') as stock:
            path, kind, used = visuals.get_visual('unused', d+'/v', scene=scene())
            self.assertEqual((kind, used), ('authored-motion', 'original-schematic'))
            with open(path) as f: self.assertEqual(json.load(f), scene())
            stock.assert_not_called()

    def test_bad_diagram_never_returns_gradient(self):
        with self.assertRaises(ValueError):
            visuals.get_visual('unused', '/tmp/unused', scene=dict(scene(), diagram_spec={}))

    def test_reviewer_sees_executed_spec_not_unused_search_alternative(self):
        ch = [{'scenes': [scene()]}]
        with mock.patch.object(reviewers, '_call_reviewer', return_value=('{"pass":true,"score":8}', 'test')) as call:
            self.assertTrue(reviewers.review_visual_feasibility(ch)['passed'])
            prompt = call.call_args.args[0]
            self.assertIn('Deep non-REM', prompt)
            self.assertIn('Original qualitative illustration', prompt)
            self.assertNotIn('person sleeping in bedroom', prompt)
        with mock.patch.object(reviewers, '_call_reviewer', return_value=('{"pass":true,"score":8}', 'test')) as call:
            self.assertTrue(reviewers.review_scenes_unique(ch)['passed'])
            self.assertIn('diagram_spec', call.call_args.args[0])

    def test_stock_failure_not_averaged_away_by_diagram(self):
        ch = [{'scenes': [{'keyword': 'rare stock'}, scene()]}]
        with mock.patch.object(reviewers, '_call_reviewer', side_effect=[('{"pass":false,"score":3}', 'stock'), ('{"pass":true,"score":10}', 'diagram')]):
            result = reviewers.review_visual_feasibility(ch)
        self.assertFalse(result['passed']); self.assertEqual(result['score'], 3)

    def test_malformed_or_below_threshold_diagram_review_blocks(self):
        for reply in ['{}', '{"pass":true,"score":6}', '{"pass":"true","score":8}']:
            with mock.patch.object(reviewers, '_call_reviewer', return_value=(reply, 'test')):
                self.assertFalse(reviewers.review_visual_feasibility([{'scenes': [scene()]}])['passed'])

    def test_all_scenes_reviewed_not_truncated_at_thirty(self):
        ch = [{'scenes': [{'keyword': 'stock '+str(i)} for i in range(40)]}]
        with mock.patch.object(reviewers, '_call_reviewer', return_value=('{"pass":true,"score":8}', 'test')) as call:
            reviewers.review_visual_feasibility(ch)
        self.assertIn('[39] stock 39', call.call_args.args[0])

    def test_bounded_atomic_chapter_repairs(self):
        ch = {'title': 'Chapter', 'scenes': [scene()]}
        plan = {'hook': 'Keep', 'chapters': [copy.deepcopy(ch), copy.deepcopy(ch)]}
        before = copy.deepcopy(plan)
        with mock.patch.object(mlp, '_save_authoring_diagnostic'), mock.patch.object(mlp, '_call_free_llm', return_value=(json.dumps(ch), 'test')) as call:
            fixed, _ = mlp._rewrite_from_review(plan, {'issues': ['FIX_ME']}, {'source': 'SOURCE_123'})
        self.assertEqual(call.call_count, 2); self.assertEqual(fixed, plan); self.assertEqual(plan, before)
        for c in call.call_args_list:
            self.assertEqual(c.kwargs['max_tokens'], 6500)
            self.assertIn('SOURCE_123', c.args[0]); self.assertIn('FIX_ME', c.args[0])
            self.assertNotIn('"hook": "Keep"', c.args[0])
        with mock.patch.object(mlp, '_save_authoring_diagnostic'), mock.patch.object(mlp, '_call_free_llm', side_effect=[(json.dumps(ch), 'test'), ('bad JSON', 'test')]):
            with self.assertRaises(ValueError): mlp._rewrite_from_review(plan, {})
        self.assertEqual(plan, before)

    def test_gemini_cannot_drop_or_relabel_reviewed_visual_contract(self):
        plan = {'chapters': [{'scenes': [scene()]}]}
        for key, value in [('visual_type', 'stock'), ('diagram_spec', {}), ('visual_source_notes', '')]:
            revised = copy.deepcopy(plan); revised['chapters'][0]['scenes'][0][key] = value
            with mock.patch.object(mlp, '_call_gemini_review', return_value=(json.dumps(revised), 'test')):
                with self.assertRaises(RuntimeError): mlp.stage5_final_review(plan)

    def test_distinct_animation_frames_and_text_overflow_fails(self):
        a = motion.frame(SPEC, 0).tobytes(); b = motion.frame(SPEC, .6).tobytes()
        self.assertNotEqual(a, b)
        spec = copy.deepcopy(SPEC); spec['title'] = 'W'*60
        # Title must fit rather than silently clip. Checked by production renderer.
        with self.assertRaises(ValueError): motion.frame(spec, 0)

    def test_real_editor_normalize_uses_measured_duration(self):
        with tempfile.TemporaryDirectory() as d:
            visual = visuals.get_visual('unused', d+'/v', scene=scene())
            out = editor._normalize(visual, 1.5, d+'/measured.mp4', 0)
            self.assertAlmostEqual(editor.probe_duration(out), 1.5, places=1)
            missing = (d+'/missing.json', 'authored-motion', 'original-schematic')
            with self.assertRaises(FileNotFoundError): editor._normalize(missing, 1.5, d+'/bad.mp4', 0)

    def test_pipeline_wires_spec_and_final_gemini_for_all_paths(self):
        code = (ROOT/'long-videos/main_long.py').read_text()
        self.assertIn('scene_text=sc.get("narration", ""), scene=sc', code)
        central = code[code.index('    plan, llm_used, meta = _generate_long_plan'):]
        self.assertLess(central.index('stage5_final_review(plan, evidence)'), central.index('run_all_reviewers('))
        self.assertIn('no visual substitution allowed', code)

class BoundedSceneTests(unittest.TestCase):
    def test_breakdown_is_one_chapter_per_call_with_owned_scene_ids(self):
        source = [{'title': 'One', 'paragraphs': ['Source paragraph.']},
                  {'title': 'Two', 'paragraphs': ['Next paragraph.']}]
        unit = {'chapters': [{'title': 'Generated', 'scenes': [scene() for _ in range(4)]}]}
        with mock.patch.object(mlp, '_save_authoring_diagnostic'), mock.patch.object(mlp, '_call_free_llm', return_value=(json.dumps(unit), 'test')) as call:
            chapters, _ = mlp.stage2_breakdown_scenes(source, {'evidence': 'FACT_123'})
        self.assertEqual(call.call_count, 2)
        self.assertEqual(chapters[1]['scenes'][3]['scene_id'], 'ch1-sc3')
        for c in call.call_args_list:
            self.assertEqual(c.kwargs['max_tokens'], 6500)
            self.assertIn('FACT_123', c.args[0])

    def test_longform_stock_search_preserves_literal_brief(self):
        with mock.patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}), mock.patch.object(visuals, '_pexels', return_value='v.mp4') as provider:
            result = visuals.get_visual('person writing sleep diary', '/tmp/literal', scene={'keyword': 'person writing sleep diary'})
        self.assertEqual(result[2], 'pexels')
        self.assertTrue(provider.call_args.kwargs['literal_query'])
        with mock.patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}), mock.patch.object(visuals, '_pexels', return_value='v.mp4') as provider:
            visuals.get_visual('shorts topic', '/tmp/legacy')
        self.assertFalse(provider.call_args.kwargs['literal_query'])

if __name__ == '__main__': unittest.main()
