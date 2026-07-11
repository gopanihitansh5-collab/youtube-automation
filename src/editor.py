"""FFmpeg assembly — CPU-only, works on GitHub Actions and locally on Windows.

Handles three kinds of scene visual:
  "video" -> loop/crop to 1080x1920
  "image" -> Ken Burns zoom (in on even scenes, out on odd scenes)
  None    -> animated gradient background (flat color if the filter is missing)

Then: concat -> burn word-timed captions -> hook overlay with zoom animation ->
optional background music from assets/music/ -> final H.264/AAC mux.
"""
import os
import glob
import json
import datetime
import subprocess
from concurrent.futures import ThreadPoolExecutor

W, H, FPS = 1080, 1920, 30

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _font_arg(path):
    return path.replace("\\", "/").replace(":", "\\:")


def _run(cmd):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


# ------------------------------------------------------------ scene visuals
def _norm_video(src, dur, out):
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps={FPS},setsar=1")
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src,
          "-t", f"{dur:.3f}", "-an", "-vf", vf,
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


def _norm_image(src, dur, out, index):
    frames = max(int(dur * FPS), 2)
    if index % 2 == 0:
        zexpr = f"1+0.12*on/{frames}"
    else:
        zexpr = f"1.12-0.12*on/{frames}"
    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
        f"crop={W * 2}:{H * 2},"
        f"zoompan=z='{zexpr}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
        f"setsar=1"
    )
    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-t", f"{dur:.3f}",
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


def _norm_gradient(dur, out, index):
    palettes = ["0x0f172a:0x7c3aed", "0x111827:0x0ea5e9",
                "0x1e1b4b:0xdb2777", "0x052e16:0x22d3ee"]
    c0, c1 = palettes[index % len(palettes)].split(":")
    try:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"gradients=s={W}x{H}:c0={c0}:c1={c1}:speed=0.03:"
                    f"d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    except subprocess.CalledProcessError:
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", f"color=c={c0}:s={W}x{H}:d={dur:.3f}:r={FPS}",
              "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


def _normalize(visual, dur, out, index):
    path, kind = visual
    if kind == "video" and path and os.path.exists(path):
        return _norm_video(path, dur, out)
    if kind == "image" and path and os.path.exists(path):
        return _norm_image(path, dur, out, index)
    return _norm_gradient(dur, out, index)


# ------------------------------------------------------------------ concat
def _listfile(paths, out):
    listfile = out + ".txt"
    with open(listfile, "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '" + os.path.abspath(p).replace("\\", "/") + "'\n")
    return listfile


def _concat(paths, out):
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
          "-i", _listfile(paths, out), "-c", "copy", out])
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


# ---------------------------------------------------------------- captions
def _fmt_ts(t):
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    ms = int(round((s - int(s)) * 1000))
    return f"{int(h):02}:{int(m):02}:{int(s):02},{ms:03}"


def _write_srt(scene_words, durations, path):
    """Per-word SRT captions: each word pops up individually at its exact timing.
    Minimum 0.3s per cue.  Emoji and non-ASCII characters are stripped because
    the Ubuntu runner font (DejaVu Sans) lacks those glyphs.
    """
    import re
    _clean = lambda t: re.sub(r'[^\x20-\x7E]', '', t).strip()
    MIN_DUR = 0.3
    cues, n, offset = [], 1, 0.0

    for words, dur in zip(scene_words, durations):
        i = 0
        while i < len(words):
            w = words[i]
            raw = _clean(w[0])
            if not raw:
                i += 1
                continue
            start = offset + w[1]
            end = offset + w[2]
            if end - start < MIN_DUR:
                end = start + MIN_DUR
            if end > offset + dur:
                end = offset + dur
            if end <= start:
                end = start + MIN_DUR
            cues.append((start, end, raw))
            i += 1
        offset += dur

    with open(path, "w", encoding="utf-8") as f:
        for st, en, txt in cues:
            f.write(f"{n}\n{_fmt_ts(st)} --> {_fmt_ts(en)}\n{txt}\n\n")
            n += 1
    return path


# ------------------------------------------------------------------- music
def _pick_music():
    """Cycle through assets/music/ files by day-of-year so each video gets a
    different track."""
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
def build(scene_visuals, scene_audios, scene_words, durations, hook, out):
    """scene_visuals: list of (path_or_None, kind). Returns path of final mp4."""
    durations = [max(round(d * FPS), 2) / FPS for d in durations]

    with ThreadPoolExecutor(max_workers=min(4, len(durations))) as pool:
        norm = list(pool.map(
            lambda iv: _normalize(iv[1], durations[iv[0]],
                                  f"output/norm_{iv[0]}.mp4", iv[0]),
            enumerate(scene_visuals)))

    base_video = _concat(norm, "output/base.mp4")
    voice = _concat_audio(scene_audios, durations, "output/voice.wav")

    _write_srt(scene_words, durations, "output/subs.srt")

    style = ("Fontname=DejaVu Sans,Fontsize=26,Bold=1,"
             "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
             "BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=350")
    vf = f"subtitles=output/subs.srt:force_style='{style}'"

    font = _font()
    import re
    hook_txt = re.sub(r'[^\x20-\x7E]', '', (hook or "").replace(":", " ").replace("'", "").replace("\\", ""))
    if font and hook_txt:
        zoom_fs = "'if(lt(t,2.5),30+16*t,70)'"
        vf += (f",drawtext=fontfile='{_font_arg(font)}':text='{hook_txt}':"
               f"fontcolor=yellow:fontsize={zoom_fs}:"
               f"alpha='if(lt(t,0.4),t/0.4,1)':"
               f"borderw=5:bordercolor=black:"
               f"line_spacing=8:x=(w-text_w)/2:y=300:enable='lt(t,3)'")

    LOUD = "loudnorm=I=-16:TP=-1.5:LRA=11"
    music = _pick_music()
    cmd = ["ffmpeg", "-y", "-i", base_video, "-i", voice]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music,
                "-filter_complex",
                f"[0:v]{vf}[v];"
                f"[1:a]{LOUD}[vo];"
                f"[2:a]volume=0.12[m];"
                f"[vo][m]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", vf, "-af", LOUD, "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", out]
    _run(cmd)
    return out
