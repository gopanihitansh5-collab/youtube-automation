"""Integrity checks for the opt-in, locally rendered 3D scene."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'tools' / 'anatomy'


class DynamicToolkitTests(unittest.TestCase):
    def test_reviewed_demo_hash_and_local_sources(self):
        dynamic = ROOT / 'dynamic'
        metadata = json.loads((dynamic / 'asset.json').read_text())
        digest = hashlib.sha256((dynamic / 'approved-build-demo.mp4').read_bytes()).hexdigest()
        self.assertEqual(digest, metadata['sha256'])
        self.assertEqual(digest, json.loads((ROOT / 'manifest.json').read_text())['approved_dynamic_demo']['sha256'])
        scene = (dynamic / 'vertical-preview.html').read_text()
        self.assertIn('./three.module.js', scene)
        self.assertIn('window.renderFrame', scene)
        self.assertIn('Permission is hereby granted', (dynamic / 'THREE-LICENSE.txt').read_text())
        self.assertFalse('https://' in scene or 'http://' in scene)

    def test_picture_stream_matches_demo_contract(self):
        data = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
            str(ROOT / 'dynamic' / 'approved-build-demo.mp4')], timeout=30))
        self.assertEqual(len(data['streams']), 1)
        stream = data['streams'][0]
        self.assertEqual((stream['codec_type'], stream['width'], stream['height']), ('video', 720, 1280))
        self.assertEqual((stream['r_frame_rate'], int(stream['nb_frames'])), ('24/1', 288))
        self.assertAlmostEqual(float(data['format']['duration']), 12.0, places=3)
