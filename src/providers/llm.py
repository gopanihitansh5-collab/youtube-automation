"""Script/plan generation with a graceful provider chain.

Order:
  1. Gemini Flash (REST)   (GEMINI_API_KEY, free tier)
  2. OpenRouter            (OPENROUTER_API_KEY — ":free" models ONLY, $0 cost)
  3. Hugging Face router   (HF_TOKEN, free tier, OpenAI-compatible chat API)
  4. Local llama.cpp model (LOCAL_LLM=1 — Qwen2.5-3B GGUF downloaded onto the
                            runner itself; no API needed, CPU-only)
  5. Offline template      (no network / no keys — always succeeds)

Every provider returns the same validated plan dict:
  {title, description, tags[], hook, scenes[{narration, keyword}]}
"""
import os
import re
import json

import requests

PROMPT = """You are a top faceless YouTube Shorts scriptwriter.
Topic: "{topic}"

Return ONLY a JSON object with EXACTLY these keys:
{{
  "title": "clickable YouTube title, <= 70 characters, no quotes",
  "description": "2-3 punchy lines about the video, then 5 relevant #hashtags on a new line",
  "tags": ["12", "lowercase", "keyword", "strings", "relevant", "to", "the", "topic", "and", "niche", "for", "seo"],
  "hook": "a punchy 4-7 word on-screen hook shown in the first 3 seconds",
  "scenes": [
    {{"narration": "one energetic spoken sentence", "keyword": "2-4 word stock-video search terms"}}
  ]
}}

Rules:
- 5 to 7 scenes.
- Total narration ~130-160 words (about 40-55 seconds spoken).
- First scene's narration must open with a strong hook that stops the scroll.
- "keyword" must be concrete, visual, and searchable on a stock-video site.
- No emojis inside "narration". Plain text only. Valid JSON only.
"""

# Free-tier friendly instruct models on the HF router, best first.
HF_MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
]

# OpenRouter: ONLY ":free" models — these cost $0. IDs rotate over time, so we
# ask OpenRouter's live catalog first and fall back to this static list.
OPENROUTER_MODELS = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]


def _openrouter_free_models():
    """Live list of currently-available $0 models, biggest first."""
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
        r.raise_for_status()
        free = []
        for m in r.json().get("data", []):
            pricing = m.get("pricing", {})
            if (m.get("id", "").endswith(":free")
                    and float(pricing.get("prompt", 1)) == 0
                    and float(pricing.get("completion", 1)) == 0):
                free.append((m.get("context_length") or 0, m["id"]))
        free.sort(reverse=True)
        return [mid for _, mid in free[:6]] or OPENROUTER_MODELS
    except Exception as e:
        print(f"    OpenRouter catalog fetch failed ({e}) -> static list")
        return OPENROUTER_MODELS

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]


def _extract_json(text):
    """Pull the first JSON object out of a model reply (handles ```json fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1])


def _validate(data, topic):
    scenes = data.get("scenes") or []
    scenes = [s for s in scenes
              if isinstance(s, dict) and s.get("narration") and s.get("keyword")]
    if len(scenes) < 3:
        raise ValueError(f"only {len(scenes)} usable scenes")
    return {
        "title": str(data.get("title") or topic)[:100],
        "description": str(data.get("description") or topic),
        "tags": [str(t)[:60] for t in (data.get("tags") or [])][:15],
        "hook": str(data.get("hook") or "Watch till the end")[:60],
        "scenes": scenes[:8],
    }


def _gemini(topic):
    """Plain REST call — works with any key format, no SDK needed."""
    key = os.environ["GEMINI_API_KEY"]
    last_err = None
    for model in GEMINI_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": PROMPT.format(topic=topic)}]}],
                    "generationConfig": {"responseMimeType": "application/json",
                                         "temperature": 0.8},
                },
                timeout=120,
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _validate(_extract_json(text), topic)
        except Exception as e:
            last_err = e
            print(f"    Gemini model {model} failed: {e}")
    raise RuntimeError(f"all Gemini models failed: {last_err}")


def _openrouter(topic):
    """OpenRouter — restricted to ':free' models so it can never cost money."""
    token = os.environ["OPENROUTER_API_KEY"]
    last_err = None
    for model in _openrouter_free_models():
        if not model.endswith(":free"):
            continue  # hard guarantee: never call a paid model
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user",
                                  "content": PROMPT.format(topic=topic)}],
                    "max_tokens": 1400,
                    "temperature": 0.8,
                },
                timeout=120,
            )
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "unknown error"))
            content = body["choices"][0]["message"]["content"]
            return _validate(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    OpenRouter model {model} failed: {e}")
    raise RuntimeError(f"all OpenRouter free models failed: {last_err}")


def _huggingface(topic):
    token = os.environ["HF_TOKEN"]
    last_err = None
    for model in HF_MODELS:
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": PROMPT.format(topic=topic)}],
                    "max_tokens": 1400,
                    "temperature": 0.8,
                },
                timeout=120,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate(_extract_json(content), topic)
        except Exception as e:  # try the next model
            last_err = e
            print(f"    HF model {model} failed: {e}")
    raise RuntimeError(f"all HF models failed: {last_err}")


def _local(topic):
    """Run a quantized Qwen2.5-3B entirely on the runner's CPU (no API)."""
    from llama_cpp import Llama
    from .local_models import ensure_llm

    model_path = ensure_llm()
    llm = Llama(
        model_path=model_path,
        n_ctx=4096,
        n_threads=os.cpu_count() or 4,
        verbose=False,
    )
    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": PROMPT.format(topic=topic)}],
        max_tokens=1400,
        temperature=0.8,
    )
    content = out["choices"][0]["message"]["content"]
    return _validate(_extract_json(content), topic)


def _offline(topic):
    """Zero-network template script. Not viral-grade, but the pipeline never dies."""
    t = topic.strip().rstrip(".!?")
    words = [w for w in re.findall(r"[A-Za-z]+", t) if len(w) > 3][:3]
    kw = " ".join(words) if words else "abstract background"
    scenes = [
        {"narration": f"Here is what nobody tells you about {t}.",
         "keyword": f"{kw} dramatic"},
        {"narration": f"Most people get {t} completely wrong, and it costs them every single day.",
         "keyword": f"{kw} city people"},
        {"narration": "The first thing to understand is that small consistent actions beat big bursts of effort.",
         "keyword": "person writing sunrise"},
        {"narration": f"Second, the people who win with {t} focus on systems, not motivation.",
         "keyword": "chess strategy closeup"},
        {"narration": "Third, they track their progress, because what gets measured gets improved.",
         "keyword": "notebook checklist desk"},
        {"narration": f"Start applying this to {t} today, and follow for more insights like this.",
         "keyword": "sunrise mountain success"},
    ]
    return {
        "title": f"The Truth About {t.title()}"[:100],
        "description": f"What nobody tells you about {t}.\nFollow for daily insights.\n"
                       f"#shorts #{words[0].lower() if words else 'facts'} #motivation #learn #daily",
        "tags": ["shorts", "facts", "education", "motivation"] + [w.lower() for w in words],
        "hook": "Nobody tells you this",
        "scenes": scenes,
    }


def generate_plan(topic):
    """Return (plan, provider_name). Never raises — offline always succeeds."""
    chain = []
    if os.environ.get("GEMINI_API_KEY"):
        chain.append(("gemini-flash", _gemini))
    if os.environ.get("OPENROUTER_API_KEY"):
        chain.append(("openrouter-free", _openrouter))
    if os.environ.get("HF_TOKEN"):
        chain.append(("huggingface-router", _huggingface))
    if os.environ.get("LOCAL_LLM", "").lower() in ("1", "true", "yes"):
        chain.append(("local-qwen2.5-3b", _local))
    chain.append(("offline-template", _offline))

    for name, fn in chain:
        try:
            plan = fn(topic)
            print(f"  script provider: {name}")
            return plan, name
        except Exception as e:
            print(f"  script provider {name} unavailable: {e}")
    # unreachable — _offline cannot fail — but keep a hard fallback anyway
    return _offline(topic), "offline-template"
