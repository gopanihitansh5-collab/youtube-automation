"""Per-scene visuals with unique-image guarantee across runs.

Order:
  1. Pexels stock video    (PEXELS_API_KEY, free)
  2. Pixabay stock video   (PIXABAY_API_KEY, free, optional)
  3. HF FLUX.1-schnell     (HF_TOKEN, free tier — AI-generated image,
                            the editor animates it with a Ken Burns zoom)
  4. None                  (editor paints an animated gradient — never dies)

Every provider randomises its results so consecutive runs never reuse the same
footage.  The used-visuals log in output/used_visuals.json persists across runs
via the GitHub Actions artifact — see main.py restore/upload logic.
"""
import os
import json
import hashlib
from datetime import date

import requests


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


# ------------------------------------------------------------------- seeding
def _search_seed(keyword):
    """Append a daily-varying suffix so the same keyword returns different
    fresh results every day."""
    seeds = [
        "cinematic lighting", "professional", "modern", "clean", "dramatic",
        "minimalist", "dark moody", "bright vibrant", "high contrast",
        "aesthetic", "soft focus", "golden hour", "urban", "natural",
        "studio quality", "deep colors", "editorial style",
    ]
    idx = (date.today().toordinal() + len(keyword)) % len(seeds)
    return f"{keyword} {seeds[idx]}"


# ------------------------------------------------------------------- download
def _download(url, out_path, timeout=180):
    with requests.get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for block in r.iter_content(chunk_size=1 << 16):
                f.write(block)
    if os.path.getsize(out_path) < 10_000:
        raise RuntimeError("downloaded file suspiciously small")
    return out_path


# ---------------------------------------------------------------- pexels
def _pexels(keyword, out_path):
    key = os.environ["PEXELS_API_KEY"]
    used = _load_used()
    seeded = _search_seed(keyword)
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": seeded, "per_page": 40, "orientation": "portrait"},
        timeout=30,
    )
    r.raise_for_status()
    candidates = []
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("link")]
        for f in files:
            if (f.get("height") or 0) >= 1080 and f["link"] not in used:
                candidates.append(f)
    if not candidates:
        raise RuntimeError(f"no fresh Pexels result for {seeded!r}")
    import random
    pick = random.choice(candidates)
    _record_used(pick["link"])
    return _download(pick["link"], out_path)


# ---------------------------------------------------------------- pixabay
def _pixabay(keyword, out_path):
    key = os.environ["PIXABAY_API_KEY"]
    used = _load_used()
    seeded = _search_seed(keyword)
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": seeded, "per_page": 40, "safesearch": "true"},
        timeout=30,
    )
    r.raise_for_status()
    candidates = []
    for hit in r.json().get("hits", []):
        vids = hit.get("videos", {})
        for size in ("large", "medium", "small"):
            url = (vids.get(size) or {}).get("url")
            if url and url not in used:
                candidates.append(url)
    if not candidates:
        raise RuntimeError(f"no fresh Pixabay result for {seeded!r}")
    import random
    pick = random.choice(candidates)
    _record_used(pick)
    return _download(pick, out_path)


# --------------------------------------------------------------- hf image
def _hf_image(keyword, out_path):
    """Generate a vertical AI image with FLUX.1-schnell — unique every time."""
    token = os.environ["HF_TOKEN"]
    # Vary the prompt with a random style modifier
    import random
    styles = [
        "cinematic, dramatic lighting, highly detailed, professional photography",
        "warm tones, soft lighting, dreamy atmosphere, editorial quality",
        "high contrast, sharp focus, moody atmosphere, film grain",
        "vibrant colors, natural lighting, crisp details, lifestyle photography",
    ]
    style = styles[random.randrange(len(styles))]
    prompt = f"{keyword}, vertical composition, {style}, 9:16 aspect ratio"
    r = requests.post(
        "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {token}", "x-wait-for-model": "true"},
        json={"inputs": prompt, "parameters": {"width": 768, "height": 1344}},
        timeout=300,
    )
    r.raise_for_status()
    if not (r.headers.get("content-type") or "").startswith("image"):
        raise RuntimeError(f"HF returned non-image: {r.text[:200]}")
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


# ----------------------------------------------------------------- public
def get_visual(keyword, out_base):
    """Return (path_or_None, kind, provider_name). Never raises."""
    chain = []
    if os.environ.get("PEXELS_API_KEY"):
        chain.append(("pexels", _pexels, out_base + ".mp4", "video"))
    if os.environ.get("PIXABAY_API_KEY"):
        chain.append(("pixabay", _pixabay, out_base + ".mp4", "video"))
    if os.environ.get("HF_TOKEN"):
        chain.append(("hf-flux-image", _hf_image, out_base + ".jpg", "image"))

    for name, fn, path, kind in chain:
        try:
            fn(keyword, path)
            return path, kind, name
        except Exception as e:
            print(f"    visual provider {name} failed for {keyword!r}: {e}")

    return None, None, "gradient-fallback"
