"""Per-scene visuals with a graceful provider chain.

Order:
  1. Pexels stock video    (PEXELS_API_KEY, free)
  2. Pixabay stock video   (PIXABAY_API_KEY, free, optional)
  3. HF FLUX.1-schnell     (HF_TOKEN, free tier — AI-generated image,
                            the editor animates it with a Ken Burns zoom)
  4. None                  (editor paints an animated gradient — never dies)

Returns (path_or_None, kind, provider) where kind is "video" | "image" | None.
"""
import os

import requests


def _download(url, out_path, timeout=180):
    with requests.get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for block in r.iter_content(chunk_size=1 << 16):
                f.write(block)
    if os.path.getsize(out_path) < 10_000:
        raise RuntimeError("downloaded file suspiciously small")
    return out_path


def _pexels(keyword, out_path):
    key = os.environ["PEXELS_API_KEY"]
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": keyword, "per_page": 5, "orientation": "portrait"},
        timeout=30,
    )
    r.raise_for_status()
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("link")]
        if not files:
            continue
        # smallest file that still covers 1080x1920 — 4K originals waste
        # minutes of download + scaling time for zero visible gain
        good = sorted((f for f in files if (f.get("height") or 0) >= 1920),
                      key=lambda f: f.get("height") or 0)
        pick = good[0] if good else max(files, key=lambda f: f.get("height") or 0)
        return _download(pick["link"], out_path)
    raise RuntimeError(f"no Pexels results for {keyword!r}")


def _pixabay(keyword, out_path):
    key = os.environ["PIXABAY_API_KEY"]
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": keyword, "per_page": 5, "safesearch": "true"},
        timeout=30,
    )
    r.raise_for_status()
    for hit in r.json().get("hits", []):
        vids = hit.get("videos", {})
        for size in ("large", "medium", "small"):
            url = (vids.get(size) or {}).get("url")
            if url:
                return _download(url, out_path)
    raise RuntimeError(f"no Pixabay results for {keyword!r}")


def _hf_image(keyword, out_path):
    """Generate a vertical AI image with FLUX.1-schnell on the free HF API."""
    token = os.environ["HF_TOKEN"]
    prompt = (f"{keyword}, cinematic vertical composition, dramatic lighting, "
              f"highly detailed, professional photography, 9:16")
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
