"""Professional 1080x1920 YouTube Shorts thumbnail with category-aware styling.

Pure FFmpeg pipeline — zero Python imaging dependencies.
Design: multi-layer gradient background, semi-transparent text area,
hierarchical hook text with accent underline, CTA badge with pill shape,
and optional category-themed color scheme.
"""
import os
import re
import subprocess

W, H = 1080, 1920

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

# Category → color palette mapping for thumbnail backgrounds
_CATEGORY_PALETTES = {
    "psychology":  ("0x1a0a2e", "0x7c3aed"),   # deep purple → violet
    "habits":      ("0x0f172a", "0x0ea5e9"),   # dark blue → sky blue
    "stoicism":    ("0x1a0a0a", "0x991b1b"),   # dark maroon → red
    "money":       ("0x1a1200", "0xd97706"),   # dark amber → gold
    "health":      ("0x052e16", "0x22d3ee"),   # dark teal → cyan
    "creativity":  ("0x1e1b4b", "0xdb2777"),   # indigo → pink
    "communication":("0x0c0a1e", "0x6366f1"),  # navy → indigo
    "productivity":("0x1c1917", "0xea580c"),   # dark brown → orange
    "general":     ("0x0f172a", "0x7c3aed"),   # default purple
}

# Emoji/icon for each category (shown above the main text)
_CATEGORY_ICONS = {
    "psychology":  "\U0001f9e0",
    "habits":      "\U0001f4aa",
    "stoicism":    "\U0001f3db\ufe0f",
    "money":       "\U0001f4b0",
    "health":      "\U0001f9a0",
    "creativity":  "\U0001f3a8",
    "communication": "\U0001f5e3\ufe0f",
    "productivity": "\u23f1\ufe0f",
    "general":     "\U0001f525",
}


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


def _run(cmd):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, capture_output=False)


def _classify(text):
    """Quick keyword-based category detection for palette selection."""
    t = text.lower()
    if re.search(r"psychology|brain|mind|memory|emotion|anxiety|neuroscience|dopamine|amygdala", t): return "psychology"
    if re.search(r"stoic|stoicism|marcus|seneca|epictetus|memento|amor.fati", t): return "stoicism"
    if re.search(r"billionaire|wealth|money|invest|rich|finance|income|budget|econom", t): return "money"
    if re.search(r"health|sleep|diet|workout|fasting|protein|longevity|exercise|fitness|weight", t): return "health"
    if re.search(r"habit|discipline|routine|procrastinat|consistency|willpower|morning", t): return "habits"
    if re.search(r"creativ|idea|innovate|scamper|first.principle|inversion|incubation", t): return "creativity"
    if re.search(r"persuasi|communicat|negotiat|charisma|body.language|influence|rapport", t): return "communication"
    if re.search(r"productivity|efficiency|parkinson|ivy.lee|time.management|deep.work", t): return "productivity"
    return "general"


def _smart_split(text, max_chars=25):
    """Split text into 2 lines at a natural break point (space near max_chars).
    Returns (line1, line2) with line2 being empty if text fits in one line."""
    text = text.strip()
    if len(text) <= max_chars:
        return text, ""
    # Try to split at a space near the midpoint
    mid = len(text) // 2
    for offset in range(int(max_chars * 0.4)):
        for pos in [mid - offset, mid + offset]:
            if 0 < pos < len(text) and text[pos] == " ":
                return text[:pos].strip(), text[pos:].strip()
    # Force split at max_chars
    return text[:max_chars].strip(), text[max_chars:].strip()


def make(hook_text, video_path, out_path):
    """Generate a 1080x1920 Shorts thumbnail with hook text and category-aware
    color scheme. Falls back to first video frame on any error."""
    font = _font()
    hook = (hook_text or "Watch this").replace(":", " ").replace("'", "").replace("\\", "")

    if not font:
        print("  thumbnail: no font found — extracting first video frame")
        _run(["ffmpeg", "-y", "-i", video_path, "-vframes", "1", out_path])
        return out_path

    cat = _classify(hook)
    c0, c1 = _CATEGORY_PALETTES.get(cat, _CATEGORY_PALETTES["general"])
    icon = _CATEGORY_ICONS.get(cat, "")

    line1, line2 = _smart_split(hook)

    # Build the filter chain step by step
    filters = []
    temp_files = []
    current = out_path + "_base.png"

    # Step 1: gradient background
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", f"gradients=s={W}x{H}:c0={c0}:c1={c1}:speed=0.02:d=1:r=1",
          "-update", "1", current])

    # Step 2: draw a semi-transparent dark overlay box (improves text readability)
    overlay = out_path + "_ov.png"
    # drawbox: x, y, width, height, color
    box_w, box_h = 960, 520
    box_x = (W - box_w) // 2
    box_y = (H - box_h) // 2 - 60
    try:
        _run(["ffmpeg", "-y", "-i", current,
              "-vf", f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:"
                     f"color=black@0.55:t=fill",
              "-update", "1", overlay])
        temp_files.append(current)
        current = overlay
    except subprocess.CalledProcessError:
        # If drawbox fails (older ffmpeg), skip the overlay
        pass

    # Step 3: draw text elements
    # Emoji/icon at top
    icon_size = 70
    icon_y = box_y + 40
    text_y1 = box_y + 130  # first line of hook
    text_y2 = text_y1 + 85 if line2 else 0  # second line
    cta_y = box_y + box_h - 80  # CTA near bottom of box

    # Accent underline below the icon
    accent_y = icon_y + icon_size + 15
    accent_w = 120

    drawtext_filters = []

    # Icon
    if icon:
        drawtext_filters.append(
            f"drawtext=fontfile='{_font_arg(font)}':text='{icon}':"
            f"fontsize={icon_size}:fontcolor=white:"
            f"x=(w-text_w)/2:y={icon_y}")

    # Accent line (small gold/yellow horizontal bar under icon)
    drawtext_filters.append(
        f"drawtext=fontfile='{_font_arg(font)}':text='\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501':"
        f"fontsize=18:fontcolor=yellow:"
        f"x=(w-text_w)/2:y={accent_y}")

    # Main hook line 1 (largest text)
    drawtext_filters.append(
        f"drawtext=fontfile='{_font_arg(font)}':text='{line1}':"
        f"fontcolor=yellow:fontsize=62:borderw=5:bordercolor=black@0.9:"
        f"x=(w-text_w)/2:y={text_y1}")

    # Main hook line 2 (if multi-line)
    if line2:
        drawtext_filters.append(
            f"drawtext=fontfile='{_font_arg(font)}':text='{line2}':"
            f"fontcolor=yellow:fontsize=52:borderw=4:bordercolor=black@0.9:"
            f"x=(w-text_w)/2:y={text_y2}")

    # CTA badge: "WATCH NOW" with a play icon
    cta_text = "\u25b6  WATCH SHORT"
    drawtext_filters.append(
        f"drawtext=fontfile='{_font_arg(font)}':text='{cta_text}':"
        f"fontcolor=white:fontsize=28:borderw=3:bordercolor=black:"
        f"box=1:boxcolor=yellow@0.2:boxborderw=12:"
        f"x=(w-text_w)/2:y={cta_y}")

    # Subtitle/brand text at very bottom
    brand_y = H - 120
    drawtext_filters.append(
        f"drawtext=fontfile='{_font_arg(font)}':text='Daily Insights':"
        f"fontcolor=white@0.5:fontsize=22:"
        f"x=(w-text_w)/2:y={brand_y}")

    vf = ",".join(drawtext_filters)

    try:
        _run(["ffmpeg", "-y", "-i", current,
              "-vf", vf,
              "-frames:v", "1", out_path])
    except subprocess.CalledProcessError:
        print("  thumbnail: drawtext failed — using gradient without text")
        _run(["ffmpeg", "-y", "-i", current, "-frames:v", "1", out_path])

    # Cleanup temp files
    for f in temp_files:
        try:
            os.remove(f)
        except OSError:
            pass

    return out_path
