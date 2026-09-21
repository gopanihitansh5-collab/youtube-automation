"""Offline tests for the optional ComfyUI whiteboard provider."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfyui_whiteboard import provider


class WhiteboardProviderTests(unittest.TestCase):
    def test_disabled_without_host_and_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(provider.is_configured())

    def test_workflow_replaces_all_template_values(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            workflow = provider.build_workflow(
                "Explain why people choose the easy path", "least effort", seed=42
            )
        rendered = str(workflow)
        self.assertNotIn("{{", rendered)
        self.assertEqual(42, workflow["3"]["inputs"]["seed"])
        self.assertIn("whiteboard explainer", workflow["6"]["inputs"]["text"])

    def test_render_scene_submits_polls_and_downloads(self):
        config = provider.load_config()
        config.update(
            base_url="https://comfy.invalid/api",
            api_key="secret",
            checkpoint="model.safetensors",
            poll_interval_seconds=0,
        )
        queued = mock.Mock()
        queued.raise_for_status.return_value = None
        queued.json.return_value = {"prompt_id": "job-1"}
        history = mock.Mock()
        history.raise_for_status.return_value = None
        history.json.return_value = {
            "job-1": {"outputs": {"9": {"images": [{"filename": "x.png"}]}}}
        }
        image = mock.Mock(content=b"png-bytes")
        image.raise_for_status.return_value = None

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            provider, "load_config", return_value=config
        ), mock.patch.object(
            provider.requests, "post", return_value=queued
        ) as post, mock.patch.object(
            provider.requests, "get", side_effect=[history, image]
        ):
            output = Path(tmp) / "scene.png"
            result = provider.render_scene("Narration", "keyword", str(output), seed=1)
            self.assertEqual(str(output), result)
            self.assertEqual(b"png-bytes", output.read_bytes())
            self.assertIn("prompt", post.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
