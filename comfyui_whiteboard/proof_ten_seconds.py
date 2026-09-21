"""Generate two whiteboard panels and render a 10-second proof video."""
from pathlib import Path
import subprocess

from comfyui_whiteboard.provider import render_scene

SCENES = [
    ("least effort", "A person choosing a short easy path while a harder path leads uphill"),
    ("better choice", "A person pausing and choosing one small useful action"),
]


def main():
    output = Path("output_long/comfyui_proof")
    images = []
    for index, (keyword, narration) in enumerate(SCENES):
        path = render_scene(
            narration, keyword, str(output / f"scene_{index}.png"), seed=4200 + index
        )
        images.append(path)

    list_file = output / "scenes.txt"
    list_file.write_text(
        "".join(f"file '{Path(path).resolve()}'\nduration 5\n" for path in images)
        + f"file '{Path(images[-1]).resolve()}'\n",
        encoding="utf-8",
    )
    video = output / "whiteboard-proof-10s.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,fps=30",
            "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        timeout=180,
    )
    print(video)


if __name__ == "__main__":
    main()
