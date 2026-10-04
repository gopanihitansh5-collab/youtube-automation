import importlib.util, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UploadOnlyBankTests(unittest.TestCase):
    def test_ai_sandbox_is_private_upload_only(self):
        mod = load('publish_reviewed_bank', 'scripts/publish_reviewed_bank.py')
        self.assertIn('ai-sandbox-private', mod.BANK)
        self.assertEqual(mod.UPLOAD_ONLY, {'ai-sandbox-private'})
        self.assertEqual(mod.BANK['ai-sandbox-private'][0], 'c89c0a45076eeffeea67f40a9870d046f4d9ee40d5e6826e240212cb5d733fd0')

    def test_metadata_title_and_no_readonly_scope_request(self):
        import json
        meta = json.loads((ROOT / 'reviewed-bank/ai-sandbox-private.json').read_text())
        self.assertEqual(meta['title'], 'The AI Test That Found a Hole in Its Own Sandbox')
        src = (ROOT / 'scripts/publish_reviewed_bank.py').read_text()
        branch = src.split('if episode in UPLOAD_ONLY:')[1].split('return')[0]
        self.assertNotIn('readonly', branch)
        self.assertIn("'private'", branch)
        self.assertIn('verify_readback=False', branch)


if __name__ == '__main__':
    unittest.main()
