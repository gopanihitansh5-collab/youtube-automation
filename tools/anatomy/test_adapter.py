import tempfile
import hashlib
import subprocess
import json
from pathlib import Path
import unittest
from compose_local import validate, compose

ROOT = Path(__file__).parent


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.asset = ROOT/'anatomy-vertical-smoke.mp4'
        self.manifest = json.loads((ROOT/'sample-asset.json').read_text())

    def test_valid_asset(self):
        self.assertEqual(validate(self.asset, self.manifest, 8), self.asset.resolve())

    def test_hash_mismatch(self):
        self.manifest['sha256'] = '0'*64
        with self.assertRaises(ValueError):
            validate(self.asset, self.manifest, 8)

    def test_no_loop_to_hide_short_asset(self):
        with self.assertRaises(ValueError):
            validate(self.asset, self.manifest, 8.1)

    def test_no_wrong_provenance(self):
        self.manifest['asset_type'] = 'stock'
        with self.assertRaises(ValueError):
            validate(self.asset, self.manifest, 8)

    def test_invalid_duration(self):
        for duration in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                validate(self.asset, self.manifest, duration)

    def test_short_picture_long_audio_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            asset = Path(folder)/'adversarial.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                'color=c=black:s=90x160:r=24:d=1','-f','lavfi','-i',
                'anullsrc=r=48000:cl=mono','-t','3','-c:v','libx264',
                '-c:a','aac',str(asset)],check=True)
            manifest = dict(self.manifest)
            manifest['sha256'] = hashlib.sha256(asset.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'too short'):
                validate(asset, manifest, 2)

    def test_existing_receipt_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'new.mp4'
            receipt = out.with_suffix('.receipt.json')
            receipt.write_text('preserve')
            with self.assertRaises(ValueError):
                compose(self.asset, self.manifest, 8, out)
            self.assertEqual(receipt.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
