"""LLM-based word-level emphasis tagging for captions.

Each word from TTS is tagged as one of:
  - keyword  → bold + brand color (key terms, names, numbers)
  - emphasis → italic (tone shifts, emotional words)
  - normal   → no special styling

PREFERRED PROVIDER ORDER: Groq → OpenRouter → offline fallback
"""
import os
import json
import re
import requests

_EMPHASIS_CACHE = {}


def _call_llm_tag(prompt, max_retries=2):
    """Fast lightweight LLM call — Groq first, then OpenRouter."""
    if os.environ.get("GROQ_API_KEY"):
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": "Tag each word as keyword, emphasis, or normal. Return JSON array."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 4096,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"], "groq-llama3.3-70b"
            except Exception:
                continue

    if os.environ.get("OPENROUTER_API_KEY"):
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "google/gemma-3-12b-it:free",
                        "messages": [
                            {"role": "system", "content": "Tag each word as keyword, emphasis, or normal. Return JSON array."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 4096,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"], "openrouter-gemma-3-12b"
            except Exception:
                continue

    return None, None


def _build_tag_prompt(words):
    """Build a prompt to tag each word in a scene."""
    text = " | ".join(w[0].strip() if isinstance(w, (list, tuple)) else str(w).strip() for w in words)
    text = text[:3000]
    return (
        f"Tag each word below as 'keyword', 'emphasis', or 'normal'.\n"
        f"  keyword = important term, name, number, concept the viewer should remember\n"
        f"  emphasis = emotional word, tone shift, surprising word\n"
        f"  normal = filler, transition, common words\n\n"
        f"Words: {text}\n\n"
        f"Return ONLY a JSON array of tags in the same order, like: "
        f"[\"normal\", \"keyword\", \"emphasis\", \"normal\"]\n"
        f"Pure JSON. No markdown."
    )


def _parse_tags(text):
    """Parse LLM response into a list of tags."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        tags = json.loads(text)
        if isinstance(tags, list):
            return [t.lower() for t in tags if isinstance(t, str)]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def tag_words_for_scene(words, scene_keyword=""):
    """Tag each word in a scene with emphasis type.
    
    Returns list of (word_text, start_sec, end_sec, tag) tuples.
    Falls back to all-'normal' on failure.
    """
    cache_key = "|".join(w[0].strip()[:20] if isinstance(w, (list, tuple)) else str(w)[:20] for w in words[:10])
    if cache_key in _EMPHASIS_CACHE:
        return _EMPHASIS_CACHE[cache_key]

    prompt = _build_tag_prompt(words)
    result, model = _call_llm_tag(prompt)

    if result:
        tags = _parse_tags(result)
        if tags and len(tags) >= len(words):
            tagged = []
            for i, w in enumerate(words):
                raw = w[0].strip() if isinstance(w, (list, tuple)) else str(w).strip()
                start = w[1] if isinstance(w, (list, tuple)) and len(w) >= 2 else 0.0
                end = w[2] if isinstance(w, (list, tuple)) and len(w) >= 3 else start + 0.3
                tag = tags[i] if i < len(tags) else "normal"
                if tag not in ("keyword", "emphasis"):
                    tag = "normal"
                tagged.append((raw, start, end, tag))
            _EMPHASIS_CACHE[cache_key] = tagged
            return tagged

    # Fallback: tag all as normal
    tagged = []
    for w in words:
        raw = w[0].strip() if isinstance(w, (list, tuple)) else str(w).strip()
        start = w[1] if isinstance(w, (list, tuple)) and len(w) >= 2 else 0.0
        end = w[2] if isinstance(w, (list, tuple)) and len(w) >= 3 else start + 0.3
        tagged.append((raw, start, end, "normal"))
    _EMPHASIS_CACHE[cache_key] = tagged
    return tagged


def tag_all_scenes(scene_words):
    """Tag words across all scenes with LLM emphasis.

    Args:
        scene_words: list of lists, each inner list is [(word, start, end), ...]

    Returns:
        list of lists, same structure with tags: [(word, start, end, tag), ...]
    """
    if not scene_words:
        return scene_words

    print(f"  Tagging {len(scene_words)} scenes with emphasis LLM ...", flush=True)
    tagged = []
    for si, words in enumerate(scene_words):
        if not words:
            tagged.append([])
            continue
        scene_tagged = tag_words_for_scene(words)
        if si % 5 == 0:
            print(f"    scene {si}: {len(words)} words tagged", flush=True)
        tagged.append(scene_tagged)
    return tagged
