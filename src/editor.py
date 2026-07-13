"""Video assembly using FFmpeg with crossfades, ASS captions, and energy-aware visuals.
CPU-only, works on GitHub Actions and locally on Windows.

Handles four kinds of scene visual:
  "video"        -> loop/crop to 1080x1920
  "image"        -> Ken Burns zoom + optional grain/post-processing
  "image/sd"     -> stronger Ken Burns zoom (20%) + denoise + film grain
  None / "gradient" -> animated gradient background with floating shapes

Then: concat with crossfades -> burn word-timed captions -> hook overlay ->
optional background music -> final H.264/AAC mux.
"""
import os
import glob
import json
import datetime
import subprocess
from concurrent.futures import ThreadPoolExecutor

W, H, FPS = 1080, 1920, 30
XFADE_DUR = 0.3

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

_ENERGY_PALETTES = {
    "calm":       ("0x0ea5e9", "0x06b6d4", "0x0891b2", "0x0f172a"),
    "energetic":  ("0xf97316", "0xea580c", "0xfbbf24", "0x7c2d12"),
    "mysterious": ("0x7c3aed", "0x6b21a8", "0x1e1b4b", "0x0f0f23"),
    "hopeful":    ("0x22d3ee", "0x06b6d4", "0xfbbf24", "0xfef3c7"),
    "intense":    ("0xef4444", "0xdc2626", "0x991b1b", "0x0a0a0a"),
    "curious":    ("0x10b981", "0x059669", "0x34d399", "0x022c22"),
    "reveal":     ("0xf59e0b", "0xd97706", "0xffffff", "0x1c1917"),
    "triumphant": ("0xfbbf24", "0xf59e0b", "0xffffff", "0x78350f"),
    "default":    ("0x0f172a", "0x7c3aed", "0x0ea5e9", "0x1e1b4b"),
}


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


_FFMPEG_TIMEOUT = 600


def _run(cmd, timeout=_FFMPEG_TIMEOUT):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, timeout=timeout)


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path], timeout=30)
    return float(json.loads(out)["format"]["duration"])


def _palette_for(index, scene_energies=None):
    energy = "default"
    if scene_energies and index < len(scene_energies):
        energy = scene_energies[index]
    return _ENERGY_PALETTES.get(energy, _ENERGY_PALETTES["default"])


# ------------------------------------------------------------ zoom curves
def _zoom_curve_linear(frames, zoom_max):
    return f"1+{zoom_max}*on/{frames}"


def _zoom_curve_ease_in(frames, zoom_max):
    return f"1+{zoom_max}*pow(on/{frames},1.5)"


def _zoom_curve_ease_out(frames, zoom_max):
    return f"1+{zoom_max}*pow(on/{frames},0.5)"


def _zoom_curve_ease_in_out(frames, zoom_max):
    t = "on/{frames}"
    return f"1+{zoom_max}*({t}*{t}*(3-2*{t}))"


def _zoom_curve_bounce(frames, zoom_max):
    return (
        f"1+{zoom_max}*(1-pow(2,-10*on/{frames})*"
        f"cos(6*3.14159*on/{frames})+0.05)"
    )


_ZOOM_PRESETS = {
    "stock-image":        (0.12, _zoom_curve_linear),
    "stock-image-even":   (0.12, _zoom_curve_ease_in_out),
    "stock-image-odd":    (0.12, _zoom_curve_linear),
    "local-sd":           (0.20, _zoom_curve_ease_in_out),
    "local-sd-even":      (0.22, _zoom_curve_ease_in),
    "local-sd-odd":       (0.18, _zoom_curve_ease_out),
    "intense":            (0.18, _zoom_curve_ease_in),
    "calm":               (0.10, _zoom_curve_ease_in_out),
}

_POST_FILTERS = {
    "stock-image": "",
    "local-sd": (
        "smartblur=lr=1.5:ls=-0.4:lt=-3.0,"
        "noise=alls=3:allf=t+u"
    ),
    "gradient": "",
}


def _scene_visual_kind(visual):
    if not visual or visual[0] is None:
        return "gradient", "gradient"
    path, kind = visual[:2]
    source_type = visual[2] if len(visual) >= 3 else "stock"
    if not path or not os.path.exists(path):
        return "gradient", "gradient"
    return kind, source_type


# ------------------------------------------------------------ scene visuals
def _norm_video(src, dur, out):
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps={FPS},setsar=1")
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src,
          "-t", f"{dur:.3f}", "-an", "-vf", vf,
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


def _norm_image(src, dur, out, index, source_type="stock", energy=None):
    frames = max(int(dur * FPS), 2)

    preset_key = source_type
    if source_type == "local-sd":
        preset_key += "-even" if index % 2 == 0 else "-odd"
    elif source_type == "stock":
        preset_key += "-even" if index % 2 == 0 else "-odd"

    if energy == "intense" and source_type == "local-sd":
        preset_key = "intense"
    elif energy == "calm" and source_type == "local-sd":
        preset_key = "calm"

    zoom_max, zoom_fn = _ZOOM_PRESETS.get(preset_key, _ZOOM_PRESETS["stock-image"])
    post_filter = _POST_FILTERS.get(source_type, "")

    if index % 2 == 0:
        zexpr = zoom_fn(frames, zoom_max)
    else:
        zexpr = f"1+{zoom_max}-{zoom_max}*on/{frames}"

    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
        f"crop={W * 2}:{H * 2},"
        f"zoompan=z='{zexpr}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
        f"setsar=1"
    )

    if post_filter:
        vf += f",{post_filter}"

    print(
        f"    norm_image[{index}]: type={source_type} "
        f"zoom={zoom_max} curve={zoom_fn.__name__} "
        f"post={post_filter or 'none'} "
        f"dir={'in' if index % 2 == 0 else 'out'}",
        flush=True,
    )

    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-t", f"{dur:.3f}",
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


# ------------------------------------------------------ two-layer parallax
def _norm_image_parallax(src, dur, out, index, source_type="local-sd", energy=None):
    try:
        frames = max(int(dur * FPS), 2)
        mid_frame = int(frames * 0.3)

        layer1 = out.replace(".mp4", "_l1.mp4")
        _norm_image(src, dur, layer1, index, source_type, energy)

        layer2 = out.replace(".mp4", "_l2.mp4")
        zmax = 0.22
        zexpr = f"1+{zmax}*on/{frames}"
        vf2 = (
            f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
            f"crop={W * 2}:{H * 2},"
            f"zoompan=z='{zexpr}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)+20':y='ih/2-(ih/zoom/2)-10':"
            f"s={W}x{H}:fps={FPS},"
            f"setsar=1"
        )
        _run(["ffmpeg", "-y", "-i", src, "-vf", vf2, "-t", f"{dur:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", layer2])

        _run([
            "ffmpeg", "-y",
            "-i", layer1,
            "-i", layer2,
            "-filter_complex",
            f"[0:v][1:v]overlay=0:0:enable='gte(t,{mid_frame/FPS})':"
            f"format=auto,"
            f"lut=a='if(lte(t,{mid_frame/FPS}),255,128)'[v]",
            "-map", "[v]",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            out,
        ])

        for tmp in (layer1, layer2):
            if os.path.exists(tmp):
                os.remove(tmp)

        return out
    except Exception as e:
        print(f"    parallax effect failed ({e}), falling back to standard zoom",
              flush=True)
        return _norm_image(src, dur, out, index, source_type, energy)


# ----------------------------------------------------------- gradient scenes
def _norm_gradient(dur, out, index, scene_energies=None):
    pal = _palette_for(index, scene_energies)
    c0, c1, c2, c3 = pal

    shapes_filter = _build_shape_overlays(dur, index)
    try:
        try:
            g_vf = (f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:c3={c3}:"
                    f"speed=0.02:rotation=0.5:d={dur:.3f}:r={FPS}")
            if shapes_filter:
                _run(["ffmpeg", "-y", "-f", "lavfi",
                      "-i", g_vf,
                      "-vf", shapes_filter,
                      "-c:v", "libx264", "-preset", "veryfast",
                      "-pix_fmt", "yuv420p", out])
            else:
                _run(["ffmpeg", "-y", "-f", "lavfi",
                      "-i", g_vf,
                      "-c:v", "libx264", "-preset", "veryfast",
                      "-pix_fmt", "yuv420p", out])
        except subprocess.CalledProcessError:
            _run(["ffmpeg", "-y", "-f", "lavfi",
                  "-i", f"gradients=s={W}x{H}:c0={c0}:c1={c1}:speed=0.02:"
                        f"d={dur:.3f}:r={FPS}",
                  "-c:v", "libx264", "-preset", "veryfast",
                  "-pix_fmt", "yuv420p", out])
    except subprocess.CalledProcessError:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"color=c={c0}:s={W}x{H}:d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "veryfast",
              "-pix_fmt", "yuv420p", out])
    return out


def _build_shape_overlays(dur, index):
    import random
    rng = random.Random(index * 137 + int(dur * 10))
    frames = max(int(dur * FPS), 2)
    shapes = []
    for _ in range(rng.randint(2, 4)):
        cx = rng.randint(100, W - 100)
        cy = rng.randint(100, H - 100)
        r_ = rng.randint(20, 60)
        x_start = cx - r_
        y_start = cy - r_
        dx = rng.randint(-80, 80)
        dy = rng.randint(-80, 80)
        alpha = rng.choice(["0.15", "0.25", "0.35"])
        color = rng.choice(["0xFFFFFF", "0x000000"])
        x_expr = f"'{x_start}+{dx}*on/{frames}'"
        y_expr = f"'{y_start}+{dy}*on/{frames}'"
        shapes.append(
            f"drawbox=x={x_expr}:y={y_expr}:w={r_*2}:h={r_*2}:"
            f"color={color}@{alpha}:t=fill"
        )
    return ",".join(shapes) if shapes else ""


# ------------------------------------------------------------ normalizer
def _normalize(visual, dur, out, index, scene_energies=None):
    kind, source_type = _scene_visual_kind(visual)
    energy = _palette_for(index, scene_energies)

    if kind == "video" and visual[0] and os.path.exists(visual[0]):
        print(
            f"    normalizing video scene {index}: {source_type}, {dur:.1f}s",
            flush=True,
        )
        return _norm_video(visual[0], dur, out)

    if kind == "image" and visual[0] and os.path.exists(visual[0]):
        if source_type == "local-sd":
            dur = max(dur, 6.0)
        else:
            dur = max(dur, 4.0)

        print(
            f"    normalizing image scene {index}: "
            f"type={source_type}, dur={dur:.1f}s",
            flush=True,
        )

        if source_type == "local-sd" and dur >= 6.0:
            return _norm_image_parallax(visual[0], dur, out, index, source_type, energy)

        return _norm_image(visual[0], dur, out, index, source_type, energy)

    print(
        f"    normalizing gradient scene {index}: {dur:.1f}s, "
        f"palette={_palette_for(index, scene_energies)}",
        flush=True,
    )
    return _norm_gradient(dur, out, index, scene_energies)


# ------------------------------------------------------------ transitions
def _concat_xfade(paths, out):
    n = len(paths)
    if n == 0:
        raise ValueError("no scenes to concat")
    if n == 1:
        _run(["ffmpeg", "-y", "-i", paths[0],
              "-c", "copy", out])
        return out

    durations = [probe_duration(p) for p in paths]
    td = XFADE_DUR
    inputs = []
    for p in paths:
        inputs.extend(["-i", p])

    parts = []
    for i in range(n - 1):
        cum = sum(durations[:i + 1])
        offset = cum - (i + 1) * td
        if offset < 0:
            offset = 0
        in0 = f"v{i}" if i > 0 else "0"
        in1 = str(i + 1)
        out_lbl = f"v{i + 1}"
        parts.append(
            f"[{in0}][{in1}]xfade=transition=fade:duration={td}:"
            f"offset={offset}[{out_lbl}]"
        )

    filter_complex = ";".join(parts)

    _run(["ffmpeg", "-y"] + inputs +
         ["-filter_complex", filter_complex,
          "-map", f"[v{n - 1}]",
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


def _concat_audio(paths, durations, out):
    wavs = []
    for i, (p, dur) in enumerate(zip(paths, durations)):
        w = f"output/seg_{i}.wav"
        _run(["ffmpeg", "-y", "-i", p, "-ar", "44100", "-ac", "2",
              "-af", "apad", "-t", f"{dur:.4f}", "-c:a", "pcm_s16le", w])
        wavs.append(w)
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
          "-i", _listfile(wavs, out), "-c:a", "pcm_s16le", out])
    return out


def _listfile(paths, out):
    listfile = out + ".txt"
    with open(listfile, "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '" + os.path.abspath(p).replace("\\", "/") + "'\n")
    return listfile


# ---------------------------------------------------------------- captions
def _fmt_ass_ts(t):
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    cs = int(round((s - int(s)) * 100))
    return f"{int(h)}:{int(m):02}:{int(s):02}.{cs:02}"


_ASS_COLORS = [
    "&H000066FF&", "&H00FFCC00&", "&H00FF00FF&", "&H0000FF44&",
    "&H00FF66AA&", "&H0000FFFF&", "&H00FFAA44&", "&H008844FF&",
    "&H0044FFAA&", "&H00FFFFFF&", "&H0044AAFF&", "&H0000FF88&",
]


def _write_ass(scene_words, durations, path):
    """ASS captions: each word individually timed with rotating vibrant colors."""
    import re
    _clean = lambda t: re.sub(r'[^\x20-\x7E]', '', t).strip()
    MIN_DUR = 0.3

    lines = []
    lines.append("[Script Info]")
    lines.append("ScriptType: v4.00+")
    lines.append("Collisions: Normal")
    lines.append("PlayResX: 1080")
    lines.append("PlayResY: 1920")
    lines.append("")
    lines.append("[V4+ Styles]")
    lines.append(
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding"
    )
    lines.append(
        "Style: W,DejaVu Sans,66,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,-1,0,1,4,3,3,2,0,0,160,0,1"
    )
    lines.append("")
    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text"
    )

    offset = 0.0

    for scene_i, (words, dur) in enumerate(zip(scene_words, durations)):
        scene_color = _ASS_COLORS[scene_i % len(_ASS_COLORS)]
        for w in words:
            raw = _clean(w[0])
            if not raw:
                continue
            start = offset + w[1]
            end = offset + w[2]
            if end - start < MIN_DUR:
                end = start + MIN_DUR
            if end > offset + dur:
                end = offset + dur
            if end <= start:
                end = start + MIN_DUR

            lines.append(
                f"Dialogue: 0,{_fmt_ass_ts(start)},{_fmt_ass_ts(end)},"
                f"W,,0,0,0,,"
                f"{{\\an2\\c{scene_color}\\b1\\fs72\\shad3\\bord4"
                f"\\3c&H00000000&\\3a&HFF&}}{raw}"
            )
        offset += dur

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ------------------------------------------------------------------- music
def _pick_music():
    tracks = []
    for ext in ("mp3", "m4a", "wav", "ogg"):
        tracks.extend(sorted(glob.glob(f"assets/music/*.{ext}")))
    if not tracks:
        return None
    idx = datetime.date.today().toordinal() % len(tracks)
    picked = tracks[idx]
    print(f"  background music: {os.path.basename(picked)}")
    return picked


# ------------------------------------------------------------------- build
def build(scene_visuals, scene_audios, scene_words, durations, hook, out,
          scene_energies=None):
    """Assemble final video from scene components.

    Args:
        scene_visuals: list of (path, kind[, provider_name]) or (None, None, ...)
        scene_audios: list of audio file paths
        scene_words: list of word timing dicts per scene
        durations: list of scene durations in seconds
        hook: hook text string for intro overlay
        out: output mp4 path
        scene_energies: optional list of energy strings for color theming

    Returns:
        Path to final rendered mp4 file.
    """
    durations = [max(round(d * FPS), 2) / FPS for d in durations]

    print(
        f"  normalizing {len(scene_visuals)} scenes "
        f"(max {min(4, len(durations))} parallel workers) ...",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=min(4, len(durations))) as pool:
        norm = list(pool.map(
            lambda iv: _normalize(iv[1], durations[iv[0]],
                                  f"output/norm_{iv[0]}.mp4", iv[0],
                                  scene_energies),
            enumerate(scene_visuals)))

    print("  concat with crossfades ...", flush=True)
    base_video = _concat_xfade(norm, "output/base.mp4")

    print("  concat audio ...", flush=True)
    voice = _concat_audio(scene_audios, durations, "output/voice.wav")

    print("  writing captions (ASS) ...", flush=True)
    _write_ass(scene_words, durations, "output/subs.ass")

    vf = "subtitles=output/subs.ass"

    font = _font()
    import re
    hook_txt = re.sub(
        r'[^\x20-\x7E]', '',
        (hook or "").replace(":", " ").replace("'", "").replace("\\", "")
    )
    if font and hook_txt:
        zoom_fs = "'if(lt(t,2.5),30+22*t,85)'"
        vf += (
            f",drawtext=fontfile='{_font_arg(font)}':text='{hook_txt}':"
            f"fontcolor=#FFD700:fontsize={zoom_fs}:"
            f"alpha='if(lt(t,0.4),t/0.4,1)':"
            f"borderw=5:bordercolor=#000000:"
            f"shadowcolor=#000000@0.8:shadowx=4:shadowy=4:"
            f"line_spacing=12:x=(w-text_w)/2:y=200:enable='lt(t,3)'"
        )

    LOUD = "loudnorm=I=-16:TP=-1.5:LRA=11"
    music = _pick_music()
    cmd = ["ffmpeg", "-y", "-i", base_video, "-i", voice]
    if music:
        cmd += [
            "-stream_loop", "-1", "-i", music,
            "-filter_complex",
            f"[0:v]{vf}[v];"
            f"[1:a]{LOUD}[vo];"
            f"[2:a]volume=0.12[m];"
            f"[vo][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "[v]", "-map", "[a]",
        ]
    else:
        cmd += ["-vf", vf, "-af", LOUD, "-map", "0:v", "-map", "1:a"]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", out,
    ]

    print("  encoding final video ...", flush=True)
    _run(cmd)

    final_dur = probe_duration(out)
    print(f"  final video: {out} ({final_dur:.1f}s)", flush=True)
    return out
