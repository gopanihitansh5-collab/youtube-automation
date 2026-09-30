import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pipeline_safety import ProviderFailure, call_provider, write_failure

ROOT=Path(__file__).resolve().parents[1]
def local_models():
    spec=importlib.util.spec_from_file_location('isolated_local_models',ROOT/'src/providers/local_models.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class SafetyTests(unittest.TestCase):
    def test_concurrent_bootstrap_once(self):
        mod=local_models();obj=object()
        with patch.object(mod,'_build_kokoro',return_value=obj) as build:
            with ThreadPoolExecutor(max_workers=6) as pool:
                results=list(pool.map(lambda _:mod.ensure_kokoro(),range(24)))
        self.assertEqual(build.call_count,1);self.assertTrue(all(x is obj for x in results))
    def test_failed_bootstrap_cached(self):
        mod=local_models()
        with patch.object(mod,'_build_kokoro',side_effect=SystemExit(1)) as build:
            for _ in range(3):
                with self.assertRaises(ProviderFailure):mod.ensure_kokoro()
        self.assertEqual(build.call_count,1)
    def test_worker_systemexit_typed(self):
        def failing():raise SystemExit(1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(call_provider,failing)
            with self.assertRaises(ProviderFailure):future.result()
    def test_keyboard_interrupt_not_hidden(self):
        def interrupted():raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):call_provider(interrupted)
    def test_safe_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'failure.json';write_failure(RuntimeError('secret value'),'render',str(p))
            self.assertNotIn('secret value',p.read_text());self.assertIn('render',p.read_text())
    def test_voice_fallback_after_bootstrap_exit(self):
        spec=importlib.util.spec_from_file_location('isolated_voice',ROOT/'src/providers/voice.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with patch.object(m,'_kokoro',side_effect=SystemExit(1)),patch.object(m,'_edge',return_value=('audio',[],)):
            self.assertEqual(m.synth('test','en-US-AriaNeural','unused')[2],'edge-tts')
    def test_manual_preproduction_guard(self):
        s=(ROOT/'.github/workflows/daily-long-video.yml').read_text();self.assertIn('default: true',s);self.assertIn('SKIP_UPLOAD:',s);self.assertIn('output_long/failure.json',s)
    def test_single_inference_lock(self):
        s=(ROOT/'src/providers/voice.py').read_text();self.assertIn('with _KOKORO_INFERENCE_LOCK:',s)
