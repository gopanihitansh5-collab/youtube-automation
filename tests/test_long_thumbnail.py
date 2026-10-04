"""Regression tests for the long-form thumbnail pipeline."""
import importlib.util
import tempfile
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "long-videos" / "thumbnail.py"


def load_thumbnail_module():
    spec = importlib.util.spec_from_file_location("long_thumbnail", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch("urllib.request.urlretrieve"):
        spec.loader.exec_module(module)
    return module


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.thumbnail = load_thumbnail_module()

    def test_make_passes_topic_context_to_base_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "thumbnail.jpg"
            base = Path(tmp) / "thumbnail_base.png"
            context = {"region": "US", "video_angle": "behavior science"}

            def create_base(*_args, **_kwargs):
                base.write_bytes(b"image")
                return str(base)

            with mock.patch.object(
                self.thumbnail, "generate_base", side_effect=create_base
            ) as generate, mock.patch.object(
                self.thumbnail, "enhance", return_value=str(output)
            ):
                self.thumbnail.make(
                    "Title", "Hook", out_path=str(output), extra_context=context
                )

            generate.assert_called_once_with(
                "Title", "Hook", str(base), extra_context=context
            )

    def test_generate_base_adds_nonempty_topic_context_to_prompt(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"predictions": [{}]}
        requests = mock.Mock()
        requests.post.return_value = response
        self.thumbnail.requests = requests

        self.thumbnail.generate_base(
            "Title",
            "Hook",
            "unused.png",
            api_key="test-key",
            extra_context={
                "region": "India",
                "video_angle": "daily decision making",
                "reason": "rising interest",
            },
        )

        prompt = requests.post.call_args.kwargs["json"]["instances"][0]["prompt"]
        self.assertIn("Target region: India", prompt)
        self.assertIn("Video angle: daily decision making", prompt)
        self.assertIn("Why it matters: rising interest", prompt)

    def test_drawbox_uses_input_height_not_drawtext_height(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "base.png"
            source.write_bytes(b"image")
            for style in self.thumbnail.THUMB_STYLES:
                with mock.patch.object(self.thumbnail, "_font", return_value="font.ttf"), mock.patch.object(self.thumbnail, "_run") as run:
                    self.thumbnail.enhance(str(source), "Dark Matter", "Hidden forces", str(Path(tmp)/"thumb.jpg"), style["name"])
                cmd = run.call_args_list[0].args[0]
                filters = cmd[cmd.index("-vf")+1]
                box = filters.split("drawbox=",1)[1].split(",",1)[0]
                self.assertIn("ih", box)
                self.assertNotRegex(box.replace("h=", "height="), r"(?<!i)\bh\b")

    @unittest.skipUnless(os.environ.get("FFMPEG_INTEGRATION"), "Set FFMPEG_INTEGRATION for real renderer regression")
    def test_real_ffmpeg_all_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"base.jpg"
            from PIL import Image
            Image.new("RGB", (1280,720), (10,25,60)).save(source)
            for style in self.thumbnail.THUMB_STYLES:
                output=Path(tmp)/(style["name"]+".jpg")
                self.thumbnail.enhance(str(source), "Dark Matter", "Hidden universe", str(output), style["name"])
                self.assertGreater(output.stat().st_size, 1000)

    def test_all_styles_build_valid_expression_based_offsets(self):
        self.assertTrue(
            all(isinstance(style["title_y"], str) for style in self.thumbnail.THUMB_STYLES)
        )
        # This protects styles such as "h/2-60" from being converted with int().
        self.assertEqual(
            "(h/2-60)+60",
            f"({self.thumbnail.THUMB_STYLES[0]['title_y']})+60",
        )


if __name__ == "__main__":
    unittest.main()
