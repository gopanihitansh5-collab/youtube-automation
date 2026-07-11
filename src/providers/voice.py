"""Voiceover with a graceful provider chain.

Order:
  1. edge-tts   (free Microsoft neural voices, needs internet, no key,
                 gives exact per-word timings for captions)
  2. Piper      (neural TTS running LOCALLY on the runner — model downloaded
                 once to ./models; word timings are estimated)
  3. espeak-ng  (robotic but fully offline; word timings estimated)
  4. silent     (caption-only video with background music — pipeline never dies)

All providers return: (audio_path_or_None, [(word, start, end), ...], provider_name)
Timings are relative to the start of this scene's audio.
"""
import os
import re
import shutil
import asyncio
import subprocess


def _words_of(text):
    return re.findall(r"[^\s]+", text.strip())


def _estimate_timings(text, duration):
    """Spread words evenly across the audio duration (fallback captions)."""
    words = _words_of(text)
    if not words:
        return []
    # weight by word length so long words get a bit more screen time
    total = sum(len(w) + 2 for w in words)
    out, t = [], 0.0
    for w in words:
        d = duration * (len(w) + 2) / total
        out.append((w, t, t + d))
        t += d
    return out


def _probe(path):
    import json as _json
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path])
    return float(_json.loads(raw)["format"]["duration"])


# ---------------------------------------------------------------- edge-tts
async def _edge_async(text, voice, out_path):
    import edge_tts
    words = []
    try:  # edge-tts >= 7 emits sentence boundaries unless asked for words
        communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    except TypeError:  # edge-tts 6.x has no `boundary` kwarg (words by default)
        communicate = edge_tts.Communicate(text, voice)
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7          # 100ns ticks -> seconds
                end = (chunk["offset"] + chunk["duration"]) / 1e7
                words.append((chunk["text"], start, end))
    if not words or os.path.getsize(out_path) < 1024:
        raise RuntimeError("edge-tts produced no audio")
    return words


def _edge(text, voice, out_path):
    words = asyncio.run(_edge_async(text, voice, out_path))
    return out_path, words


# ------------------------------------------------------------------- piper
def _piper(text, voice, out_path):
    from .local_models import ensure_piper_voice
    onnx, _cfg = ensure_piper_voice()
    wav = out_path + ".wav"
    exe = shutil.which("piper")
    if not exe:
        raise RuntimeError("piper CLI not installed (pip install piper-tts)")
    subprocess.run(
        [exe, "-m", onnx, "-f", wav],
        input=text.encode("utf-8"), check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(["ffmpeg", "-y", "-i", wav, "-b:a", "192k", out_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(wav)
    return out_path, _estimate_timings(text, _probe(out_path))


# --------------------------------------------------------------- espeak-ng
def _espeak(text, voice, out_path):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise RuntimeError("espeak-ng not installed")
    wav = out_path + ".wav"
    subprocess.run([exe, "-v", "en-us", "-s", "165", "-w", wav, text], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", wav, "-b:a", "192k", out_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(wav)
    return out_path, _estimate_timings(text, _probe(out_path))


# ------------------------------------------------------------------ silent
# -------------------------------------------------------------- elevenlabs
# Common ElevenLabs voice name → ID mapping. Add more as needed.
_ELEVEN_VOICES = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Josh": "TxGEqnHWrfWFTfGW9XjX",
    "Nicole": "pi3gcvgx4nDm2a6D3SKc",
    "Sam": "yoZ06aMxZJJ28mnd3zQ5",
    "Bella": "EXAVITQu4vrj8gSDl1bT",
    "Arnold": "VR6Ae3Lc6AqGiyTPs28c",
    "Charlie": "IKne3meq5aR9XaB1NJb3",
    "Dorothy": "ThT5K0dITNfqL1sCcy6p",
    "Eli": "MF1JmHy5SWM7X9hA5Uxv",
    "Emily": "LcfcdonarrXDG2hK4JfQ",
    "Ethan": "g5CIjZEefAph1n3v3Vl3",
    "Freya": "VRkARj3BzBcGgX6rZDZL",
    "Gigi": "jBDFV3SlX6J8o0mOiADK",
    "Michael": "flWY5Qz7h5K5z8v3y2v3",
}


def _eleven_voice_id(name):
    """Resolve a voice name to an ElevenLabs voice ID.
    Supports 'eleven:Name' prefix, bare voice names, and raw IDs."""
    if not name:
        return None
    raw = name.strip()
    if raw.startswith("eleven:"):
        raw = raw[7:].strip()
    # If it's already a UUID-like ID, return as-is
    if len(raw) == 20 and raw.isascii() and "-" not in raw:
        return raw
    # Try the name lookup
    return _ELEVEN_VOICES.get(raw)


def _elevenlabs(text, voice, out_path):
    """ElevenLabs TTS with word-level timestamps from the /with-timestamps endpoint."""
    import requests as _req
    import base64 as _b64

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    voice_id = _eleven_voice_id(voice) or "21m00Tcm4TlvDq8ikWAM"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.3, "similarity_boost": 0.7},
    }
    resp = _req.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    audio_bytes = _b64.b64decode(data["audio_base64"])
    with open(out_path, "wb") as f:
        f.write(audio_bytes)

    alignment = data.get("alignment", {})
    chars = alignment.get("characters", [])
    char_starts = alignment.get("char_start_times_seconds", [])
    char_ends = alignment.get("char_end_times_seconds", [])
    if not chars:
        return out_path, _estimate_timings(text, _probe(out_path))

    words, current_word = [], ""
    for ci, (ch, cs, ce) in enumerate(zip(chars, char_starts, char_ends)):
        current_word += ch
        if ch.isspace() and current_word.strip():
            w = current_word.strip()
            if w:
                words.append((w, cs, ce))
            current_word = ""
    if current_word.strip():
        words.append((current_word.strip(),
                      char_starts[-1] if char_starts else 0,
                      char_ends[-1] if char_ends else _probe(out_path)))

    return out_path, words if words else _estimate_timings(text, _probe(out_path))


def _silent(text, voice, out_path):
    """No audio at all: captions carry the video. ~0.38s per word of silence."""
    dur = max(2.5, 0.38 * len(_words_of(text)))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=44100:cl=stereo:d={dur:.2f}", "-b:a", "128k", out_path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path, _estimate_timings(text, dur)


def synth(text, voice, out_path):
    """Return (audio_path, [(word, start, end)...], provider_name). Never raises.

    If the `voice` parameter matches an ElevenLabs voice name (e.g. 'Rachel',
    'Adam', 'eleven:Rachel'), and ELEVENLABS_API_KEY is set, ElevenLabs is used
    directly as the only provider — giving premium quality for important topics.
    """
    # Check for explicit ElevenLabs voice
    eleven_id = _eleven_voice_id(voice) if voice else None
    if eleven_id and os.environ.get("ELEVENLABS_API_KEY"):
        try:
            path, words = _elevenlabs(text, voice, out_path)
            print(f"    voice provider: elevenlabs ({voice})")
            return path, words, f"elevenlabs-{voice}"
        except Exception as e:
            print(f"    elevenlabs failed for '{voice}': {e} — falling through chain")

    chain = [("elevenlabs", _elevenlabs), ("edge-tts", _edge),
             ("piper-local", _piper),
             ("espeak-ng", _espeak), ("silent", _silent)]
    last_err = None
    for name, fn in chain:
        try:
            path, words = fn(text, voice, out_path)
            return path, words, name
        except Exception as e:
            last_err = e
            print(f"    voice provider {name} unavailable: {e}")
    raise RuntimeError(f"even silent audio failed: {last_err}")  # ffmpeg missing
