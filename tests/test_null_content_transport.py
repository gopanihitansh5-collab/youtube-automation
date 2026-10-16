"""Null/empty provider content must advance the model chain, not abort the pipeline."""
import importlib.util, pathlib, sys, types, unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "long-videos"))
import multi_llm_pipeline as mlp  # noqa: E402


def _resp(content):
    r = mock.Mock()
    r.raise_for_status = lambda: None
    r.json = lambda: {"choices": [{"message": {"content": content}}]}
    return r


class NullContentTests(unittest.TestCase):
    def test_extract_json_tolerates_none(self):
        self.assertIsNone(mlp._extract_json(None))
        self.assertIsNone(mlp._extract_json_array(None))

    def test_groq_skips_null_model(self):
        replies = iter([_resp(None), _resp("   "), _resp('{"a": 1}')])
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "x"}), \
             mock.patch.object(mlp, "GROQ_MODELS", ["m1", "m2", "m3"]), \
             mock.patch.object(mlp.requests, "post", lambda *a, **k: next(replies)):
            text, model = mlp._call_groq("p")
        self.assertEqual(text, '{"a": 1}')
        self.assertEqual(model, "groq-m3")

    def test_openrouter_skips_null_model(self):
        replies = iter([_resp(None), _resp("ok")])
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "x"}), \
             mock.patch.object(mlp, "openrouter_free_models", lambda: ["a:free", "b:free"]), \
             mock.patch.object(mlp.requests, "post", lambda *a, **k: next(replies)):
            text, model = mlp._call_openrouter("p")
        self.assertEqual((text, model), ("ok", "openrouter-b:free"))

    def test_all_null_raises_runtime_error_not_attribute_error(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "x"}), \
             mock.patch.object(mlp, "openrouter_free_models", lambda: ["a:free"]), \
             mock.patch.object(mlp.requests, "post", lambda *a, **k: _resp(None)):
            with self.assertRaises(RuntimeError):
                mlp._call_openrouter("p")

    def test_stage1_null_does_not_raise_attribute_error(self):
        with mock.patch.object(mlp, "_call_free_llm", lambda *a, **k: (None, "m")):
            try:
                mlp.stage1_write_script("topic")
            except AttributeError:
                self.fail("AttributeError from null content")
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
