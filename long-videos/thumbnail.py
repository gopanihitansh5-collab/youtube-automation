"""Thumbnail generator + enhancer for YouTube long-form videos.

Pipeline:
  1. Generate base image via Imagen 4 (Gemini API)
  2. Fallback: extract frame from video
  3. Enhance with FFmpeg: title text, gradient overlays, color grade, border
  4. Output 1280x720 JPG at quality 95
"""
import os
import base64
import subprocess
import re
import json
import shutil
import urllib.request

W, H = 1280, 720

FONT_DIR = "assets/fonts"

FONT_CANDIDATES = [
    f"{FONT_DIR}/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

_FONT_URLS = {
    "DejaVuSans-Bold.ttf": "https://github.com/dejavu-fonts/dejavu-fonts/raw/release-2_37/ttf/DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf": "https://github.com/dejavu-fonts/dejavu-fonts/raw/release-2_37/ttf/DejaVuSans.ttf",
}


def _ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for fname, url in _FONT_URLS.items():
        path = os.path.join(FONT_DIR, fname)
        if not os.path.exists(path):
            try:
                print(f"  downloading font: {fname}", flush=True)
                urllib.request.urlretrieve(url, path)
                print(f"  font saved: {path}", flush=True)
            except Exception as e:
                print(f"  font download failed ({fname}): {e}", flush=True)


_ensure_fonts()

THUMB_STYLES = [
    {
        "name": "bold_split",
        "gradient": "0.6",
        "title_y": "h/2-60",
        "subtitle_y": "h/2+40",
        "accent_color": "#FFD700",
    },
    {
        "name": "bottom_bar",
        "gradient": "0.5",
        "title_y": "h-160",
        "subtitle_y": "h-80",
        "accent_color": "#00FF88",
    },
    {
        "name": "cinematic",
        "gradient": "0.7",
        "title_y": "h/2-40",
        "subtitle_y": "h/2+50",
        "accent_color": "#FF4444",
    },
    {
        "name": "minimal",
        "gradient": "0.4",
        "title_y": "h-120",
        "subtitle_y": "h-50",
        "accent_color": "#FFFFFF",
    },
]


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


def _run(cmd, timeout=60):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, timeout=timeout)


def _sanitize(text):
    return re.sub(r'[^\x20-\x7E]', '', text).replace(":", " ").replace("'", "")


def _classify_topic(title, hook):
    t = (title + " " + hook).lower()
    categories = {
        "tech": ["ai", "technology", "software", "coding", "computer", "digital", "robot", "algorithm", "data", "quantum", "cyber", "programming", "app"],
        "finance": ["money", "invest", "stock", "wealth", "financial", "economy", "crypto", "bitcoin", "market", "trading", "passive income", "recession"],
        "science": ["science", "physics", "chemistry", "biology", "space", "universe", "evolution", "dna", "brain", "neuroscience", "memory", "sleep", "vaccine"],
        "history": ["history", "ancient", "civilization", "war", "empire", "revolution", "origin", "rise and fall", "century"],
        "psychology": ["psychology", "mind", "behavior", "cognitive", "bias", "persuasion", "habit", "procrastination", "stoic", "mental", "emotion"],
        "motivation": ["success", "habit", "discipline", "focus", "productivity", "deep work", "wealth", "master", "goals", "growth"],
        "nature": ["nature", "climate", "environment", "ocean", "space", "earth", "planet", "weather", "animal", "plant"],
        "education": ["guide", "explained", "tutorial", "complete", "beginners", "learn", "course", "lesson", "how to", "breakdown"],
    }
    for cat, keywords in categories.items():
        if any(kw in t for kw in keywords):
            return cat
    return "general"


_VISUAL_STYLES = {
    "tech": {
        "palette": "neon blue, cyan, deep purple, dark background, holographic elements",
        "lighting": "cyberpunk neon lighting, volumetric rays, blue/orange contrast",
        "composition": "futuristic minimal, centered subject with glowing edge lines, digital particles floating",
        "mood": "sleek, cutting-edge, sophisticated tech aesthetic",
    },
    "finance": {
        "palette": "gold, deep green, dark navy, white, premium metallic accents",
        "lighting": "dramatic studio lighting with golden rim light, soft cinematic shadows",
        "composition": "professional clean layout, upward movement suggesting growth, bar charts or graphs as background elements",
        "mood": "premium, authoritative, wealth-oriented, trustworthy",
    },
    "science": {
        "palette": "deep blue, teal, white, purple highlights, microscopic detail colors",
        "lighting": "laboratory cool lighting, edge-lit glass, bioluminescent glow",
        "composition": "macro details, cellular patterns, cosmic backgrounds with depth",
        "mood": "academic, fascinating, discovery-driven, mysterious",
    },
    "history": {
        "palette": "sepia, dark amber, warm brown, parchment tones, aged gold",
        "lighting": "dramatic chiaroscuro, candlelight warmth, dusty atmospheric rays",
        "composition": "epic wide landscapes, ancient textures, weathered surfaces, archival mood",
        "mood": "timeless, epic, scholarly, grand narrative",
    },
    "psychology": {
        "palette": "deep indigo, soft lavender, warm amber, brain-wave blue",
        "lighting": "soft diffused studio light, thought-bubble glow, split lighting",
        "composition": "abstract neural patterns, double exposure, mirrored faces or brain silhouettes",
        "mood": "introspective, revealing, thoughtful, mind-expanding",
    },
    "motivation": {
        "palette": "warm orange, gold, deep red, bright white, sunrise gradients",
        "lighting": "golden hour backlight, heroic rim lighting, dramatic sunrise rays",
        "composition": "dynamic upward angles, person conquering obstacle, mountain peaks, expansive open sky",
        "mood": "uplifting, powerful, transformative, triumphant",
    },
    "nature": {
        "palette": "emerald green, sky blue, warm earth tones, golden sunlight",
        "lighting": "natural golden hour, soft diffused forest light, underwater caustics",
        "composition": "wide panoramic landscapes, macro nature details, atmospheric depth, bioluminescence",
        "mood": "awe-inspiring, serene, majestic, connected",
    },
    "education": {
        "palette": "clean white, academic blue, warm orange accent, charcoal",
        "lighting": "clean bright studio lighting, softbox key light, bright and clear",
        "composition": "organized clean layout, book or digital screen elements, lightbulb or brain motifs",
        "mood": "clear, authoritative, accessible, knowledge-focused",
    },
    "general": {
        "palette": "vibrant red, electric blue, bright white, deep black contrast",
        "lighting": "cinematic dramatic lighting with strong contrast, rim light on subject",
        "composition": "dynamic diagonal composition, centered focal point with negative space for text, depth layers",
        "mood": "engaging, clickable, energetic, premium YouTube aesthetic",
    },
}


def generate_base(title, hook, out_path, api_key=None):
    """Generate base thumbnail image via Imagen 4 with dynamic topic-adaptive prompt."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("  GEMINI_API_KEY not set for Imagen 4", flush=True)
        return None

    import random
    rng = random.Random()

    cat = _classify_topic(title, hook)
    style = _VISUAL_STYLES.get(cat, _VISUAL_STYLES["general"])

    mood_extras = [
        "photorealistic, 8K resolution, highly detailed",
        "cinematic shot, volumetric lighting, deep shadows",
        "trending YouTube thumbnail aesthetic, high click-through rate design",
        "professional graphic design composition, balanced negative space",
        "dramatic atmosphere with depth of field and atmospheric haze",
        "bold visual metaphor that instantly communicates the video concept",
    ]
    extra = rng.choice(mood_extras)

    prompt = (
        f"Professional YouTube thumbnail for video titled '{title}'. "
        f"Core hook: '{hook}'. "
        f"16:9 landscape, 1280x720. "
        f"Style: {cat.upper()} category aesthetic. "
        f"Color palette: {style['palette']}. "
        f"Lighting: {style['lighting']}. "
        f"Composition: {style['composition']}. "
        f"Mood: {style['mood']}. "
        f"{extra}. "
        f"CLEAN COMPOSITION: large empty area in bottom third for text overlay. "
        f"No text, no watermarks, no logos in the image. "
        f"No cluttered backgrounds. Keep focal point clear and centered."
    )

    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "imagen-4-generate:predict",
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
            },
            json={
                "instances": [{"prompt": prompt}],
                "parameters": {
                    "sampleCount": 1,
                    "aspectRatio": "16:9",
                    "personGeneration": "allow_adult",
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        img_b64 = data.get("predictions", [{}])[0].get("bytesBase64Encoded")
        if img_b64:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(img_b64))
            print(f"  Imagen 4 base thumbnail generated", flush=True)
            return out_path
        print("  Imagen 4 returned no image data", flush=True)
    except Exception as e:
        print(f"  Imagen 4 generation failed: {e}", flush=True)
    return None


def extract_from_video(video_path, out_path, time_sec=2):
    """Extract a frame from the video as fallback base image."""
    if not video_path or not os.path.exists(video_path):
        print("  no video available for frame extraction", flush=True)
        return None
    try:
        _run([
            "ffmpeg", "-y", "-i", video_path,
            "-ss", str(time_sec),
            "-vframes", "1",
            "-s", f"{W}x{H}",
            "-q:v", "2",
            out_path,
        ])
        print(f"  frame extracted from video at {time_sec}s", flush=True)
        return out_path
    except Exception as e:
        print(f"  frame extraction failed: {e}", flush=True)
    return None


def enhance(image_path, title, hook, out_path, style="bold_split"):
    """Enhance thumbnail with FFmpeg: gradient overlay, text, color grade."""
    if not image_path or not os.path.exists(image_path):
        return None

    font = _font()
    if not font:
        print("  no font found, copying raw image", flush=True)
        _run(["ffmpeg", "-y", "-i", image_path, "-q:v", "2", out_path])
        return out_path

    style_config = next((s for s in THUMB_STYLES if s["name"] == style), THUMB_STYLES[0])

    safe_title = _sanitize(title)[:60]
    safe_hook = _sanitize(hook)[:80]
    accent = style_config["accent_color"]
    alpha = style_config["gradient"]

    lines = safe_title.count(" ") > 5
    if lines:
        words = safe_title.split()
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
    else:
        line1 = safe_title
        line2 = ""

    vf = (
        f"format=rgba,"
        f"drawbox=x=0:y={style_config['title_y']}-40:w=iw:h=ih-{style_config['title_y']}+60:"
        f"color=black@{alpha}:t=fill,"
        f"drawtext=fontfile='{_font_arg(font)}':text='{line1}':"
        f"fontcolor={accent}:fontsize={48 if line2 else 56}:"
        f"borderw=4:bordercolor=#000000:"
        f"shadowcolor=#000000@0.9:shadowx=5:shadowy=5:"
        f"x=(w-text_w)/2:y={style_config['title_y']}:"
        f"box=0:boxcolor=black@0.3:boxborderw=10,"
    )

    if line2:
        vf += (
            f"drawtext=fontfile='{_font_arg(font)}':text='{line2}':"
            f"fontcolor=#FFFFFF:fontsize=44:"
            f"borderw=3:bordercolor=#000000:"
            f"shadowcolor=#000000@0.9:shadowx=4:shadowy=4:"
            f"x=(w-text_w)/2:y={int(style_config['title_y']) + 60}:"
            f"box=0:boxcolor=black@0.3:boxborderw=8,"
        )

    vf += (
        f"drawtext=fontfile='{_font_arg(font)}':text='{safe_hook}':"
        f"fontcolor=#FFFFFF@0.85:fontsize=28:"
        f"borderw=2:bordercolor=#000000:"
        f"x=(w-text_w)/2:y={style_config['subtitle_y'] + 60}:"
        f"box=0:boxcolor=black@0.2:boxborderw=6"
    )

    temp_out = out_path.replace(".jpg", "_temp.jpg").replace(".png", "_temp.png")

    _run([
        "ffmpeg", "-y", "-i", image_path,
        "-vf", vf,
        "-q:v", "2",
        "-qmin", "1", "-qmax", "5",
        temp_out,
    ])

    _run([
        "ffmpeg", "-y", "-i", temp_out,
        "-vf", (
            f"eq=contrast=1.15:brightness=0.05:saturation=1.2:gamma=1.1,"
            f"unsharp=7:7:1.2:5:5:0.6,"
            f"format=yuv420p"
        ),
        "-q:v", "2", "-qmin", "1", "-qmax", "5",
        "-frames:v", "1",
        out_path,
    ])

    if os.path.exists(temp_out):
        os.remove(temp_out)

    size_kb = os.path.getsize(out_path) / 1024 if os.path.exists(out_path) else 0
    print(f"  enhanced thumbnail: {out_path} ({size_kb:.0f}KB)", flush=True)
    return out_path


def make(title, hook, video_path=None, out_path="output_long/thumbnail.jpg",
         style="bold_split"):
    """Full pipeline: generate → enhance → output.

    Args:
        title: video title for text overlay
        hook: hook text for subtitle
        video_path: optional video path for frame fallback
        out_path: output path (.jpg or .png)
        style: thumbnail style name

    Returns:
        path to final thumbnail, or None
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    base_path = out_path.replace(".jpg", "_base.png").replace(".png", "_base.png")

    base = generate_base(title, hook, base_path)
    if not base and video_path:
        base = extract_from_video(video_path, base_path)

    if not base:
        print("  no base image available for thumbnail", flush=True)
        return None

    result = enhance(base, title, hook, out_path, style=style)

    if os.path.exists(base_path) and base_path != result:
        os.remove(base_path)

    return result


try:
    import requests
except ImportError:
    requests = None
