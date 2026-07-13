"""Script/plan generation with a graceful provider chain.

Every script is structurally unique -- an intelligent diversity layer
randomises format, voice, tone, hook style, CTA, and scene count before
any provider generates content.

Order:
  1. Groq               (GROQ_API_KEY -- Llama 3.3 70B at 500+ tok/s, free tier)
  2. Gemini Flash (REST)   (GEMINI_API_KEY, free tier)
  3. OpenRouter            (OPENROUTER_API_KEY -- ":free" models ONLY, $0 cost)
  4. Hugging Face router   (HF_TOKEN, free tier, OpenAI-compatible chat API)
  5. Local llama.cpp model (LOCAL_LLM=1 -- Qwen2.5-3B GGUF downloaded onto the
                            runner itself; no API needed, CPU-only)
  6. Offline script builder (no network / no keys -- always succeeds)

Every provider returns the same validated plan dict:
  {title, description, tags[], hook, scenes[{narration, keyword}]}
"""
import os
import re
import json

import requests

from .prompt_builder import build_prompt, build_offline_script


def _offline(topic):
    return build_offline_script(topic)

# Free-tier friendly instruct models on the HF router, best first.
HF_MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
]

# OpenRouter: ONLY ":free" models -- these cost $0.
OPENROUTER_MODELS = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
    "qwen-2.5-32b",
]

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

# Temperature range -- randomised per video so outputs vary even from the
# same provider and topic.
_TEMP_RANGE = (0.65, 0.95)


def _rand_temp(rng):
    return round(rng.uniform(*_TEMP_RANGE), 2)


def _openrouter_free_models():
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


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model reply")
    raw = text[start:end + 1]
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    raw = re.sub(r'[\u0080-\u009f]', '', raw)
    return json.loads(raw)


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


def _groq(topic, prompt, temperature):
    key = os.environ["GROQ_API_KEY"]
    last_err = None
    for model in GROQ_MODELS:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1400,
                    "temperature": temperature,
                },
                timeout=120,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    Groq model {model} failed: {e}")
    raise RuntimeError(f"all Groq models failed: {last_err}")


def _gemini(topic, prompt, temperature):
    key = os.environ["GEMINI_API_KEY"]
    last_err = None
    for model in GEMINI_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json",
                                         "temperature": temperature},
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


def _openrouter(topic, prompt, temperature):
    token = os.environ["OPENROUTER_API_KEY"]
    last_err = None
    for model in _openrouter_free_models():
        if not model.endswith(":free"):
            continue
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1400,
                    "temperature": temperature,
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


def _huggingface(topic, prompt, temperature):
    token = os.environ["HF_TOKEN"]
    last_err = None
    for model in HF_MODELS:
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1400,
                    "temperature": temperature,
                },
                timeout=120,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    HF model {model} failed: {e}")
    raise RuntimeError(f"all HF models failed: {last_err}")


def _local(topic, prompt, temperature):
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
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1400,
        temperature=temperature,
    )
    content = out["choices"][0]["message"]["content"]
    return _validate(_extract_json(content), topic)


def generate_plan(topic, extra_context=None):
    """Return (plan, provider_name, meta). Never raises -- offline always succeeds.

    Every call builds a structurally unique prompt via ``build_prompt``,
    so scripts from the same topic vary in format, voice, tone, hook, CTA,
    pacing, and scene count.

    extra_context: optional dict with sheet-provided {title, hook, desc} to
                   steer scene generation while keeping curated metadata.
    """
    import random

    dyn_prompt, meta = build_prompt(topic, extra_context=extra_context)
    rng = random.Random()
    temp = _rand_temp(rng)

    print(f"  script style: {meta['format']} | voice: {meta['voice']} | "
          f"tone: {meta['tone']} | hook: {meta['hook_style']} | "
          f"cta: {meta['cta']} | scenes: {meta['num_scenes']} | temp: {temp}")

    chain = []
    if os.environ.get("GROQ_API_KEY"):
        chain.append(("groq-llama3.3-70b", lambda: _groq(topic, dyn_prompt, temp)))
    if os.environ.get("GEMINI_API_KEY"):
        chain.append(("gemini-flash", lambda: _gemini(topic, dyn_prompt, temp)))
    if os.environ.get("OPENROUTER_API_KEY"):
        chain.append(("openrouter-free", lambda: _openrouter(topic, dyn_prompt, temp)))
    if os.environ.get("HF_TOKEN"):
        chain.append(("huggingface-router", lambda: _huggingface(topic, dyn_prompt, temp)))
    if os.environ.get("LOCAL_LLM", "").lower() in ("1", "true", "yes"):
        chain.append(("local-qwen2.5-3b", lambda: _local(topic, dyn_prompt, temp)))
    chain.append(("offline-builder", lambda: build_offline_script(topic, meta)))

    for name, fn in chain:
        try:
            plan = fn()
            print(f"  script provider: {name}")
            return plan, name, meta
        except Exception as e:
            print(f"  script provider {name} unavailable: {e}")
    plan = build_offline_script(topic, meta)
    return plan, "offline-builder", meta
