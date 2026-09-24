"""Free model IDs for the long-form pipeline.

Groq: its Llama models moved to Enterprise-only (API returns 404 for free
keys), so the free chain uses the GPT-OSS models.
OpenRouter: the ":free" catalogue changes often, so the live list is
fetched at run time and the static list is only a fallback.
"""
import requests

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-pro",
]

OPENROUTER_FALLBACK = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]

_MIN_CONTEXT = 100_000
_live_cache = None


def openrouter_free_models(limit=6):
    """Live ':free' text models with a large context, best-known first."""
    global _live_cache
    if _live_cache is not None:
        return _live_cache
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
        r.raise_for_status()
        live = []
        for m in r.json().get("data", []):
            mid = m.get("id", "")
            if not mid.endswith(":free"):
                continue
            if "safety" in mid or "code" in mid:
                continue
            if int(m.get("context_length") or 0) < _MIN_CONTEXT:
                continue
            live.append(mid)
        preferred = [m for m in OPENROUTER_FALLBACK if m in live]
        rest = [m for m in live if m not in preferred]
        _live_cache = (preferred + rest)[:limit] or list(OPENROUTER_FALLBACK)
    except Exception as e:
        print(f"  OpenRouter model list unavailable ({e}) -- using static list",
              flush=True)
        _live_cache = list(OPENROUTER_FALLBACK)
    return _live_cache
