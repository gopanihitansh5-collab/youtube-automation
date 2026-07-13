"""Cinematic landscape 1920x1080 video assembly for long-form YouTube.

Smooth easing curves on all animations, cinematic transitions between chapters,
text with glow/shadow animation, high-quality CRF 16 encode, embedded chapter
metadata markers.
"""
import os
import json
import subprocess
import glob
import datetime
import re
import random
from concurrent.futures import ThreadPoolExecutor

W, H, FPS = 1920, 1080, 24
CHAPTER_XFADE_DUR = 1.2
SCENE_XFADE_DUR = 0.4

TRANSITION_STYLES = ["fade", "slideleft", "slideright", "fadeblack",
                     "fadewhite", "pixelize", "glow", "hslbright",
                     "smoothleft", "smoothright", "circlepaint"]

# Brand color palette — consistent across all channel videos
BRAND_PALETTES = [
    ("#0f172a", "#1e293b", "#334155", "#FFD700"),  # Dark navy + gold
    ("#0a0a1a", "#1a1a3e", "#2d1b69", "#FF6B35"),  # Deep purple + orange
    ("#0f0f23", "#1e293b", "#3b82f6", "#F59E0B"),  # Slate + blue + amber
    ("#0d1117", "#161b22", "#58a6ff", "#F0F6FC"),  # GitHub dark + blue
]

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

_FFMPEG_TIMEOUT = 900


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


def _run(cmd, timeout=_FFMPEG_TIMEOUT):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, timeout=timeout)


def probe_duration(path):
    if not path or not os.path.exists(path):
        return 0.0
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path], timeout=30)
    return float(json.loads(out)["format"]["duration"])


def probe_info(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size,bit_rate",
             "-of", "json", path], timeout=30)
        return json.loads(out).get("format", {})
    except Exception:
        return {}


def _listfile(paths, out):
    listfile = out + ".txt"
    with open(listfile, "w", encoding="utf-8") as f:
        for p in paths:
            if p and os.path.exists(p):
                f.write("file '" + os.path.abspath(p).replace("\\", "/") + "'\n")
    return listfile


def _chapter_title_card(title, chapter_num, dur, out, index=0):
    """Cinematic chapter title card with animated gradient + text reveal."""
    font = _font()
    if not font:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"color=c=#0a0a1a:s={W}x{H}:d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "slow", "-crf", "16",
              "-pix_fmt", "yuv420p", out])
        return out

    frames = int(dur * FPS)
    palettes = [
        ("#0a0a1a", "#1a1a3e", "#2d1b69", "#16213e"),
        ("#0f0f23", "#1e293b", "#334155", "#0f172a"),
        ("#1a0a2e", "#2d1b69", "#16213e", "#0a0a1a"),
        ("#0a1628", "#1a2744", "#0d2137", "#16213e"),
    ]
    pal = palettes[index % len(palettes)]
    c0, c1, c2, c3 = pal

    chapter_label = f"Chapter {chapter_num}" if chapter_num else ""
    safe_title = title.replace("'", "\\'").replace(":", "\\:")

    animate_zoom = f"1+0.015*sin(2*PI*on/{frames})+0.01*on/{frames}"
    text_fade = f"'if(lt(t,0.5),0,if(lt(t,1.5),(t-0.5)/1,1))'"
    subtitle_fade = f"'if(lt(t,1.0),0,if(lt(t,2.0),(t-1.0)/1,1))'"

    vf = (
        f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:c3={c3}:"
        f"speed=0.008:rotation=0.2:d={dur:.3f}:r={FPS}[bg];"
        f"[bg]drawtext=fontfile='{_font_arg(font)}':text='{chapter_label}':"
        f"fontcolor=#FFD700@{text_fade}:fontsize=44:"
        f"borderw=2:bordercolor=#000000:"
        f"shadowcolor=#000000@0.9:shadowx=3:shadowy=3:"
        f"x=(w-text_w)/2:y=th+380:t=1[txt1];"
        f"[txt1]drawtext=fontfile='{_font_arg(font)}':text='{safe_title}':"
        f"fontcolor=#FFFFFF@{subtitle_fade}:fontsize=62:"
        f"borderw=3:bordercolor=#000000:"
        f"shadowcolor=#000000@0.9:shadowx=4:shadowy=4:"
        f"x=(w-text_w)/2:y=th+480:t=1"
    )
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
          f"color=c=black:s={W}x{H}:d={dur:.3f}:r={FPS}",
          "-filter_complex", vf,
          "-map", "[txt1]",
          "-c:v", "libx264", "-preset", "slow", "-crf", "16",
          "-pix_fmt", "yuv420p", out])
    return out


def _norm_video(src, dur, out):
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps={FPS},setsar=1,"
          f"unsharp=5:5:0.8:3:3:0.4")
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src,
          "-t", f"{dur:.3f}", "-an", "-vf", vf,
          "-c:v", "libx264", "-preset", "slow", "-crf", "16",
          "-pix_fmt", "yuv420p", out])
    return out


def _ease_in_out(t):
    """Smooth easing: t should be 0.0 to 1.0, returns eased value."""
    return t * t * (3 - 2 * t)


def _ease_out_cubic(t):
    return 1 - pow(1 - t, 3)


def _norm_image(src, dur, out, index):
    frames = max(int(dur * FPS), 2)
    zoom_max = 0.04
    t_expr = "on/" + str(frames)

    if index % 2 == 0:
        zoom_curve = f"1+{zoom_max}*({t_expr}*{t_expr}*(3-2*{t_expr}))"
    else:
        zoom_curve = f"1+{zoom_max}*(1-pow(1-{t_expr},3))"

    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
        f"crop={W * 2}:{H * 2},"
        f"zoompan=z='{zoom_curve}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={W}x{H}:fps={FPS},"
        f"setsar=1,unsharp=5:5:0.6:3:3:0.3"
    )
    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-t", f"{dur:.3f}",
          "-c:v", "libx264", "-preset", "slow", "-crf", "16",
          "-pix_fmt", "yuv420p", out])
    return out


def _norm_gradient(dur, out, index=0):
    palettes = [
        ("#0f172a", "#1e293b", "#334155", "#0f0f23"),
        ("#1a0a2e", "#2d1b69", "#16213e", "#0a0a1a"),
        ("#0a1628", "#1a2744", "#0d2137", "#16213e"),
        ("#1a1a2e", "#16213e", "#0f3460", "#0a0a1a"),
        ("#2d1b69", "#16213e", "#1a1a3e", "#0a0a1a"),
    ]
    pal = palettes[index % len(palettes)]
    c0, c1, c2, c3 = pal

    try:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i",
              f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:c3={c3}:"
              f"speed=0.015:rotation=0.3:d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "slow", "-crf", "16",
              "-pix_fmt", "yuv420p", out])
    except subprocess.CalledProcessError:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"color=c=#0f172a:s={W}x{H}:d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "slow", "-crf", "16",
              "-pix_fmt", "yuv420p", out])
    return out


def _scene_visual_kind(visual):
    if not visual or visual[0] is None:
        return "gradient"
    path, kind = visual[:2]
    if not path or not os.path.exists(path):
        return "gradient"
    return kind


def _normalize(visual, dur, out, index):
    kind = _scene_visual_kind(visual)
    if kind == "video" and visual[0] and os.path.exists(visual[0]):
        return _norm_video(visual[0], max(dur, 3.0), out)
    if kind == "image" and visual[0] and os.path.exists(visual[0]):
        return _norm_image(visual[0], max(dur, 4.0), out, index)
    return _norm_gradient(max(dur, 3.0), out, index)


def _concat_xfade(paths, out, xfade_dur=SCENE_XFADE_DUR,
                  transition_style=None):
    paths = [p for p in paths if p and os.path.exists(p)]
    n = len(paths)
    if n == 0:
        raise ValueError("no scenes to concat")
    if n == 1:
        _run(["ffmpeg", "-y", "-i", paths[0], "-c", "copy", out])
        return out

    durations = [probe_duration(p) for p in paths]
    inputs = []
    for p in paths:
        inputs.extend(["-i", p])

    style = transition_style or "fade"

    parts = []
    for i in range(n - 1):
        cum = sum(durations[:i + 1])
        offset = cum - (i + 1) * xfade_dur
        if offset < 0:
            offset = 0
        in0 = f"v{i}" if i > 0 else "0"
        in1 = str(i + 1)
        out_lbl = f"v{i + 1}"
        parts.append(
            f"[{in0}][{in1}]xfade=transition={style}:duration={xfade_dur}:"
            f"offset={offset}[{out_lbl}]"
        )

    filter_complex = ";".join(parts)
    _run(["ffmpeg", "-y"] + inputs +
         ["-filter_complex", filter_complex,
          "-map", f"[v{n - 1}]",
          "-c:v", "libx264", "-preset", "slow", "-crf", "16",
          "-pix_fmt", "yuv420p", out])
    return out


def _concat_audio(paths, durations, out):
    wavs = []
    for i, (p, dur) in enumerate(zip(paths, durations)):
        if not p or not os.path.exists(p):
            continue
        w = f"output_long/seg_{i}.wav"
        _run(["ffmpeg", "-y", "-i", p, "-ar", "48000", "-ac", "2",
              "-af", "apad", "-t", f"{dur:.4f}", "-c:a", "pcm_s16le", w])
        wavs.append(w)
    if not wavs:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"anullsrc=r=48000:cl=stereo:d=1",
              "-c:a", "pcm_s16le", out])
        return out
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
          "-i", _listfile(wavs, out), "-c:a", "pcm_s16le", out])
    return out


def _fmt_ass_ts(t):
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    cs = int(round((s - int(s)) * 100))
    return f"{int(h)}:{int(m):02}:{int(s):02}.{cs:02}"


CHAPTER_ASS_COLORS = [
    "&H0066FFAA&", "&H00FFCC00&", "&H00FF66AA&", "&H0044AAFF&",
    "&H00AAFF44&", "&H00FF8844&", "&H008844FF&", "&H0044FFAA&",
]


def _write_ass(chapter_scenes, chapter_durs, path):
    lines = []
    lines.append("[Script Info]")
    lines.append("ScriptType: v4.00+")
    lines.append("Collisions: Normal")
    lines.append("PlayResX: 1920")
    lines.append("PlayResY: 1080")
    lines.append("")
    lines.append("[V4+ Styles]")
    lines.append(
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding"
    )
    lines.append(
        "Style: W,DejaVu Sans,48,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,-1,0,1,3,3,3,2,0,0,100,0,1"
    )
    lines.append("")
    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text"
    )

    global_offset = 0.0
    for ci, (scenes, ch_dur) in enumerate(zip(chapter_scenes, chapter_durs)):
        color = CHAPTER_ASS_COLORS[ci % len(CHAPTER_ASS_COLORS)]
        scene_offset = 0.0
        for si, words in enumerate(scenes):
            if not words:
                scene_offset += ch_dur[si] if si < len(ch_dur) else 5.0
                continue
            dur = ch_dur[si] if si < len(ch_dur) else 5.0
            for w in words:
                raw = w[0].strip()
                if not raw:
                    continue
                start = global_offset + scene_offset + w[1]
                end = global_offset + scene_offset + w[2]
                if end - start < 0.3:
                    end = start + 0.3
                if end > global_offset + scene_offset + dur:
                    end = global_offset + scene_offset + dur
                lines.append(
                    f"Dialogue: 0,{_fmt_ass_ts(start)},{_fmt_ass_ts(end)},"
                    f"W,,0,0,0,,"
                    f"{{\\an2\\c{color}\\b1\\fs48\\shad2\\bord2"
                    f"\\3c&H00000000&\\3a&HFF&}}{raw}"
                )
            scene_offset += dur
        global_offset += sum(ch_dur)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


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


def _build_metadata(chapters, title, description, tags):
    """Build FFmpeg metadata file for chapter markers + video metadata."""
    lines = [";FFMETADATA1"]
    lines.append(f"title={title}")
    lines.append(f"description={description}")
    if tags:
        lines.append(f"comment=Tags: {', '.join(tags[:8])}")

    offset = 0.0
    for ch in chapters:
        chapters_dur = sum(s.get("duration", 10.0)
                          for s in ch.get("scenes", []))
        ts_start = int(offset * 1000)
        ts_end = int((offset + chapters_dur) * 1000)
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={ts_start}")
        lines.append(f"END={ts_end}")
        lines.append(f"title={ch['title']}")
        offset += chapters_dur

    meta_path = "output_long/metadata.ffmeta"
    os.makedirs("output_long", exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return meta_path


def build(chapters, scene_visuals, scene_audios, scene_words,
          chapter_durations, hook, out_path, title="", description="",
          tags=None):
    """Assemble final long-form video with cinematic quality.

    Args:
        chapters: list of {title, timestamp_sec, scenes}
        scene_visuals: flat list of (path, kind, provider)
        scene_audios: flat list of audio paths
        scene_words: flat list of word timing lists per scene
        chapter_durations: list of lists, durations per scene per chapter
        hook: hook text
        out_path: output mp4 path
        title: video title for metadata
        description: video description for metadata
        tags: list of tags for metadata
    """
    os.makedirs("output_long", exist_ok=True)
    norm_dir = "output_long/norm"
    os.makedirs(norm_dir, exist_ok=True)

    print(f"  normalizing {len(scene_visuals)} scenes ...", flush=True)
    with ThreadPoolExecutor(max_workers=min(4, len(scene_visuals))) as pool:
        norm = list(pool.map(
            lambda iv: _normalize(
                iv[1],
                sum(chapter_durations[iv[0]]) if isinstance(iv[0], int) else 5.0,
                f"{norm_dir}/scene_{iv[0]}.mp4", iv[0]),
            enumerate(scene_visuals)))

    chapter_card_dir = "output_long/chapters"
    os.makedirs(chapter_card_dir, exist_ok=True)
    all_norm = []
    scene_idx = 0

    rng = random.Random(datetime.date.today().toordinal())

    for ci, ch in enumerate(chapters):
        card_path = f"{chapter_card_dir}/card_{ci}.mp4"
        _chapter_title_card(ch["title"], ci + 1, 3.0, card_path, index=ci)
        all_norm.append(card_path)
        ch_scene_count = len(ch["scenes"])
        for si in range(ch_scene_count):
            if scene_idx < len(norm):
                all_norm.append(norm[scene_idx])
            scene_idx += 1

    print("  concat with cinematic transitions ...", flush=True)
    card_count = len(chapters)
    concat_dir = "output_long/concat"
    os.makedirs(concat_dir, exist_ok=True)

    segment_paths = []
    current_segment = []
    for ni, np_ in enumerate(all_norm):
        current_segment.append(np_)

        is_card = any(f"card_{c}" in np_ for c in range(card_count))
        is_last = (ni == len(all_norm) - 1)
        next_is_card = (ni + 1 < len(all_norm) and
                        any(f"card_{c}" in all_norm[ni + 1]
                            for c in range(card_count)))

        if is_last or (is_card and len(current_segment) >= 2) or next_is_card:
            if len(current_segment) >= 2:
                t_style = rng.choice(TRANSITION_STYLES)
                seg_out = f"{concat_dir}/seg_{len(segment_paths)}.mp4"
                _concat_xfade(current_segment, seg_out,
                              xfade_dur=SCENE_XFADE_DUR,
                              transition_style=t_style)
                segment_paths.append(seg_out)
            else:
                segment_paths.extend(current_segment)
            current_segment = []

    if current_segment:
        segment_paths.extend(current_segment)

    if len(segment_paths) > 1:
        print("  concat chapter segments with cinematic crossfades ...",
              flush=True)
        base_video = _concat_xfade(segment_paths, "output_long/base.mp4",
                                   xfade_dur=CHAPTER_XFADE_DUR,
                                   transition_style="fade")
    elif segment_paths:
        base_video = segment_paths[0]
    else:
        raise ValueError("no video segments to concat")

    flat_durs = [d for ch_durs in chapter_durations for d in ch_durs]
    print("  concat audio (48kHz) ...", flush=True)
    voice = _concat_audio(scene_audios, flat_durs, "output_long/voice.wav")

    print("  writing captions (ASS, 48pt, per-chapter color) ...", flush=True)
    chapter_word_groups = []
    word_idx = 0
    for ci, ch in enumerate(chapters):
        ch_scene_words = []
        for si in range(len(ch["scenes"])):
            if word_idx < len(scene_words):
                ch_scene_words.append(scene_words[word_idx])
            else:
                ch_scene_words.append([])
            word_idx += 1
        chapter_word_groups.append(ch_scene_words)
    _write_ass(chapter_word_groups, chapter_durations, "output_long/subs.ass")

    vf = "subtitles=output_long/subs.ass"

    font = _font()
    hook_txt = re.sub(
        r'[^\x20-\x7E]', '',
        (hook or "").replace(":", " ").replace("'", "").replace("\\", "")
    )
    if font and hook_txt:
        vf += (
            f",drawtext=fontfile='{_font_arg(font)}':text='{hook_txt}':"
            f"fontcolor=#FFD700:fontsize=72:"
            f"alpha='if(lt(t,0.3),t/0.3,if(gt(t,4.7),(5.5-t)/0.8,1))':"
            f"borderw=5:bordercolor=#000000:"
            f"shadowcolor=#000000@0.8:shadowx=4:shadowy=4:"
            f"x=(w-text_w)/2:y=h/3:enable='lt(t,5.5)'"
        )

    LOUD = "loudnorm=I=-16:TP=-1.5:LRA=11"
    music = _pick_music()
    cmd = ["ffmpeg", "-y", "-i", base_video, "-i", voice]

    brand_idx = datetime.date.today().toordinal() % len(BRAND_PALETTES)
    brand = BRAND_PALETTES[brand_idx]

    color_grade = (
        f"eq=contrast=1.1:brightness=0.02:saturation=1.15:gamma=1.05,"
        f"colorbalance=rs=0.05:gs=-0.02:bs=-0.03:rh=0.02:gh=0.0:bh=-0.02,"
        f"unsharp=5:5:0.6:3:3:0.3"
    )

    vf_color = f"{vf},{color_grade}"

    audio_filter = f"[1:a]{LOUD}[vo]"
    audio_maps = "-map", "[vo]"
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        audio_filter = (
            f"[1:a]{LOUD}[vo];"
            f"[2:a]volume=0.10:precision=fixed[m];"
            f"[vo][m]amix=inputs=2:duration=first:normalize=0,"
            f"volume=1.0[a]"
        )
        audio_maps = "-map", "[a]"

    meta_file = _build_metadata(chapters, title, description, tags or [])

    filter_complex = f"[0:v]{vf_color}[v]"
    cmd += [
        "-filter_complex", f"{filter_complex};{audio_filter}",
        "-map", "[v]", *audio_maps,
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k",
        "-ar", "48000",
        "-map_metadata", "0",
        "-metadata", f"title={title[:80]}",
        "-metadata", f"description={description[:200]}",
        "-metadata", "genre=Education",
        "-metadata", "comment=Brand: long-form educational deep dives",
        "-shortest",
        "-movflags", "+faststart",
        out_path,
    ]

    print("  encoding final cinematic video (CRF 16, preset slow, "
          "48kHz AAC) ...", flush=True)
    _run(cmd)

    if os.path.exists(out_path):
        _run([
            "ffmpeg", "-y", "-i", out_path, "-i", meta_file,
            "-map_metadata", "1", "-codec", "copy",
            "-movflags", "+faststart",
            out_path.replace(".mp4", "_meta.mp4"),
        ])
        os.replace(out_path.replace(".mp4", "_meta.mp4"), out_path)

    info = probe_info(out_path)
    final_dur = float(info.get("duration", 0))
    size_mb = int(info.get("size", 0)) / (1024 * 1024) if info.get("size") else 0
    bitrate = info.get("bit_rate", "?")
    print(f"  final video: {out_path} ({final_dur:.1f}s, {size_mb:.0f}MB, "
          f"{bitrate}b/s)", flush=True)
    return out_path
