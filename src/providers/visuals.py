"""Per-scene visuals -- maximally unique across every run.

Every provider, seed, style, and prompt is randomised per-scene so that
consecutive runs (even with the same topic or keyword) produce completely
different visuals.  Used URLs are tracked in output/used_visuals.json and
persisted across GitHub Actions runs via the artifact.

Provider chain:
  1. Pexels       -- stock video API (if PEXELS_API_KEY configured)
  2. Pixabay      -- stock video API (if PIXABAY_API_KEY configured)
  3. Gradient     -- animated fallback (always available)

Each provider has retry logic, per-provider timeout, and a session-level
failed-keyword cache to avoid retrying a provider that already failed
for the same keyword within this run."""

import os
import json
import time
import hashlib
import random
from datetime import date, datetime

import requests


# Session-level failure cache: keywords that already failed for each provider.
_FAILED_KEYWORDS = {}  # provider_name -> set(keyword)


def _mark_failed(provider, keyword):
    _FAILED_KEYWORDS.setdefault(provider, set()).add(keyword)


def _has_failed(provider, keyword):
    return keyword in _FAILED_KEYWORDS.get(provider, set())


# ------------------------------------------------------------------- helpers
def _used_path():
    return "output/used_visuals.json"


def _load_used():
    try:
        with open(_used_path()) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _record_used(url):
    used = _load_used()
    used.add(url)
    os.makedirs("output", exist_ok=True)
    with open(_used_path(), "w") as f:
        json.dump(sorted(used), f)


# ---------------------------------------------------------------- unique seed
def _run_offset():
    """Deterministic offset unique to this exact run (date + hour + minute)."""
    n = datetime.now()
    return date.today().toordinal() * 1440 + n.hour * 60 + n.minute


_SEED_MODIFIERS = [
    "cinematic lighting", "professional", "modern", "clean", "dramatic",
    "minimalist", "dark moody", "bright vibrant", "high contrast",
    "aesthetic", "soft focus", "golden hour", "urban", "natural",
    "studio quality", "deep colors", "editorial style",
    "close up", "macro", "wide angle", "slow motion", "bokeh",
    "texture", "pattern", "reflection", "silhouette", "vintage",
    "neon", "pastel", "monochrome", "warm glow", "cold tone",
    "underwater", "aerial view", "abstract", "grunge", "ethereal",
    "dramatic shadow", "backlight", "double exposure", "motion blur",
    "tilt shift", "fisheye", "panoramic", "infrared", "lens flare",
    "time lapse", "stop motion", "glitch art", "pixel art", "low poly",
    "hand drawn", "watercolor", "oil painting", "sketch", "3D render",
]

_KEYWORD_PREFIXES = [
    "close up of", "wide shot of", "aerial view of", "abstract",
    "concept of", "dramatic", "detailed view of", "extreme close up of",
    "beautiful", "stunning", "intense", "calm", "dynamic",
]

_KEYWORD_SUFFIXES = [
    "in motion", "in action", "at night", "in daylight",
    "in slow motion", "in focus", "from above", "from below",
]


def _augment_keyword(keyword, scene_index):
    """Morph the keyword so the same keyword produces vastly different search
    queries across scenes and runs."""
    kh = int(hashlib.md5(keyword.encode()).hexdigest()[:8], 16)
    off = _run_offset() + scene_index * 7 + kh
    rng = random.Random(off)

    prefix = rng.choice(_KEYWORD_PREFIXES)
    modifier = rng.choice(_SEED_MODIFIERS)
    suffix = rng.choice(_KEYWORD_SUFFIXES) if rng.random() < 0.4 else ""

    if rng.random() < 0.3:
        return f"{prefix} {keyword} {modifier} {suffix}".strip()
    elif rng.random() < 0.5:
        return f"{keyword} {modifier}, {prefix}".strip()
    else:
        return f"{modifier} {keyword} {suffix}".strip()


# ------------------------------------------------------------- mood detection
_MOOD_POSITIVE = {"success", "happy", "victory", "beautiful", "peace",
                  "calm", "love", "growth", "bright", "sunrise", "achievement"}
_MOOD_NEGATIVE = {"dark", "fear", "struggle", "pain", "failure", "war",
                  "danger", "stress", "anxiety", "sad", "lonely", "crisis"}
_MOOD_INTENSE = {"action", "explosion", "race", "fight", "speed",
                  "power", "dramatic", "urgent", "intense"}


def _detect_mood(keyword):
    kw_lower = keyword.lower()
    words = set(kw_lower.split())
    if words & _MOOD_INTENSE:
        return "intense"
    if words & _MOOD_NEGATIVE:
        return "dark"
    if words & _MOOD_POSITIVE:
        return "bright"
    return "neutral"


# ------------------------------------------------------------------- download
_DOWNLOAD_TIMEOUTS = {
    "pexels": 180,
    "pixabay": 180,
}


def _download(url, out_path, timeout=180):
    """Download a file with streaming and size validation.
    Retries once on failure (transient network errors).
    Validates that the downloaded file is >10KB (not an error page).
    """
    last_err = None
    for attempt in range(2):
        if attempt > 0:
            time.sleep(3)
        try:
            t0 = time.time()
            with requests.get(url, timeout=timeout, stream=True) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for block in r.iter_content(chunk_size=1 << 16):
                        f.write(block)
            size_kb = os.path.getsize(out_path) / 1024
            elapsed = time.time() - t0
            print(
                f"      downloaded {os.path.basename(out_path)} "
                f"({size_kb:.0f}KB) in {elapsed:.1f}s",
                flush=True,
            )
            if size_kb < 10:
                raise RuntimeError(
                    f"downloaded file suspiciously small ({size_kb:.0f}KB)"
                )
            return out_path
        except requests.exceptions.Timeout:
            last_err = f"timeout after {timeout}s"
            print(
                f"      download timeout ({timeout}s), "
                f"{'retrying...' if attempt == 0 else 'giving up'}",
                flush=True,
            )
        except requests.exceptions.ConnectionError as e:
            last_err = f"connection error: {e}"
            print(
                f"      download connection error, "
                f"{'retrying...' if attempt == 0 else 'giving up'}",
                flush=True,
            )
        except Exception as e:
            last_err = str(e)
            if attempt == 0:
                print(f"      download failed ({e}), retrying...", flush=True)
            else:
                print(f"      download failed again ({e}), giving up", flush=True)

    raise RuntimeError(f"download failed: {last_err}")


# ---------------------------------------------------------------- pexels
_PEXELS_PER_PAGE = 80


def _pexels(keyword, scene_index, out_path):
    key = os.environ["PEXELS_API_KEY"]
    used = _load_used()

    print(
        f"    Pexels: searching for {keyword!r} (scene {scene_index})",
        flush=True,
    )

    for attempt in range(3):
        if attempt > 0:
            wait = 3 * attempt
            print(f"      waiting {wait}s before retry ...", flush=True)
            time.sleep(wait)

        seeded = _augment_keyword(keyword, scene_index + attempt * 100)
        print(
            f"      attempt {attempt + 1}/3: query={seeded!r}",
            flush=True,
        )

        t0 = time.time()
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": key},
                params={
                    "query": seeded,
                    "per_page": _PEXELS_PER_PAGE,
                    "orientation": "portrait",
                },
                timeout=30,
            )
            r.raise_for_status()
            elapsed = time.time() - t0
            data = r.json()

            candidates = []
            total_results = len(data.get("videos", []))
            print(
                f"      received {total_results} results in {elapsed:.1f}s",
                flush=True,
            )

            for v in data.get("videos", []):
                files = [
                    f for f in v.get("video_files", [])
                    if f.get("link") and f["link"] not in used
                ]
                for f in files:
                    height = f.get("height") or 0
                    if height >= 720:
                        candidates.append(f)

            if candidates:
                candidates.sort(key=lambda f: -(f.get("height") or 0))
                pick = candidates[0]
                print(
                    f"      selected {pick.get('height')}p video: "
                    f"{pick['link'][:80]}...",
                    flush=True,
                )
                _record_used(pick["link"])
                timeout = _DOWNLOAD_TIMEOUTS.get("pexels", 180)
                return _download(pick["link"], out_path, timeout=timeout)
            else:
                print(
                    f"      no fresh candidates after filtering "
                    f"(used={len(used)})",
                    flush=True,
                )

        except requests.exceptions.Timeout:
            print(f"      Pexels API timeout (30s), retrying...", flush=True)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            print(
                f"      Pexels API HTTP {status}, "
                f"{'retrying...' if attempt < 2 else 'giving up'}",
                flush=True,
            )
            if status == 429:
                print("      rate limited, sleeping 10s...", flush=True)
                time.sleep(10)
        except Exception as e:
            print(f"      Pexels error: {e}", flush=True)

    raise RuntimeError(f"Pexels: no fresh result after 3 attempts")


# ---------------------------------------------------------------- pixabay
_PIXABAY_PER_PAGE = 80


def _pixabay(keyword, scene_index, out_path):
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        raise RuntimeError("PIXABAY_API_KEY not set")

    used = _load_used()
    print(
        f"    Pixabay: searching for {keyword!r} (scene {scene_index})",
        flush=True,
    )

    for attempt in range(3):
        if attempt > 0:
            wait = 3 * attempt
            print(f"      waiting {wait}s before retry ...", flush=True)
            time.sleep(wait)

        seeded = _augment_keyword(keyword, scene_index + attempt * 100 + 50)
        print(
            f"      attempt {attempt + 1}/3: query={seeded!r}",
            flush=True,
        )

        t0 = time.time()
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": key,
                    "q": seeded,
                    "per_page": _PIXABAY_PER_PAGE,
                    "safesearch": "true",
                },
                timeout=30,
            )
            r.raise_for_status()
            elapsed = time.time() - t0
            data = r.json()

            total_results = len(data.get("hits", []))
            print(
                f"      received {total_results} results in {elapsed:.1f}s",
                flush=True,
            )

            candidates = []
            for hit in data.get("hits", []):
                vids = hit.get("videos", {})
                for size in ("large", "medium", "small"):
                    url = (vids.get(size) or {}).get("url")
                    if url and url not in used:
                        candidates.append((url, size))
                        break

            if candidates:
                pick_url, pick_size = candidates[0]
                print(
                    f"      selected {pick_size} video: {pick_url[:80]}...",
                    flush=True,
                )
                _record_used(pick_url)
                timeout = _DOWNLOAD_TIMEOUTS.get("pixabay", 180)
                return _download(pick_url, out_path, timeout=timeout)
            else:
                print(
                    f"      no fresh candidates after filtering "
                    f"(used={len(used)})",
                    flush=True,
                )

        except requests.exceptions.Timeout:
            print(f"      Pixabay API timeout (30s), retrying...", flush=True)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            print(
                f"      Pixabay API HTTP {status}, "
                f"{'retrying...' if attempt < 2 else 'giving up'}",
                flush=True,
            )
        except Exception as e:
            print(f"      Pixabay error: {e}", flush=True)

    raise RuntimeError(f"Pixabay: no fresh result after 3 attempts")


# ----------------------------------------------------------------- public
def get_visual(keyword, out_base, scene_index=0):
    """Return (path, kind, provider_name). Never raises -- gradient always works.

    Walks the provider chain in order, caching failures per keyword so we
    don't retry a provider for the same keyword within a single run.
    """
    chain = []

    if os.environ.get("PEXELS_API_KEY") and not _has_failed("pexels", keyword):
        chain.append((
            "pexels",
            lambda kw, p: _pexels(kw, scene_index, p),
            out_base + ".mp4",
            "video",
        ))

    if os.environ.get("PIXABAY_API_KEY") and not _has_failed("pixabay", keyword):
        chain.append((
            "pixabay",
            lambda kw, p: _pixabay(kw, scene_index, p),
            out_base + ".mp4",
            "video",
        ))

    print(
        f"  Visual chain for scene {scene_index} ({keyword!r}): "
        + " -> ".join(name for name, _, _, _ in chain)
        + " -> gradient",
        flush=True,
    )

    for name, fn, path, kind in chain:
        try:
            t0 = time.time()
            fn(keyword, path)
            elapsed = time.time() - t0
            print(
                f"  Scene {scene_index}: {name} -> {kind} "
                f"({os.path.basename(path)}) in {elapsed:.1f}s",
                flush=True,
            )
            return path, kind, name
        except Exception as e:
            elapsed = time.time() - t0 if 't0' in dir() else 0
            print(
                f"  Scene {scene_index}: {name} failed "
                f"(after {elapsed:.1f}s): {e}",
                flush=True,
            )
            _mark_failed(name, keyword)

    print(
        f"  Scene {scene_index}: all providers failed -> gradient fallback",
        flush=True,
    )
    return None, None, "gradient-fallback"
