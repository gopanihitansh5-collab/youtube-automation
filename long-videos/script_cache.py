"""Script cache for the long-form pipeline.

Saves the last generated script plan to disk so the pipeline can resume
from the most recent step if it crashes (avoids re-running the LLM).
Also provides context-window estimation for auto model switching.
"""
import os
import json
import datetime

_CACHE_DIR = "output_long"
_CACHE_FILE = os.path.join(_CACHE_DIR, "script_cache.json")
_RUN_STATE_FILE = os.path.join(_CACHE_DIR, "run_state.json")

# Rough token estimation: 1 token ≈ 4 chars for English text
_CHARS_PER_TOKEN = 4

# Context windows (max input tokens) for each model family
MODEL_CONTEXTS = {
    "groq": {
        "openai/gpt-oss-120b": 131072,
        "openai/gpt-oss-20b": 131072,
        "llama-3.3-70b-versatile": 131072,
        "llama-4-scout-17b-16e-instruct": 1048576,
        "llama-3.1-8b-instant": 131072,
        "qwen-2.5-32b": 131072,
        "__default__": 131072,
    },
    "gemini": {
        "gemini-3.5-flash": 1048576,
        "gemini-3.1-flash-lite": 1048576,
        "gemini-3-flash-preview": 1048576,
        "gemini-2.5-flash": 1048576,
        "gemini-2.5-pro": 1048576,
        "gemini-flash-latest": 1048576,
        "__default__": 1048576,
    },
    "openrouter": {
        "nvidia/nemotron-3-super-120b-a12b:free": 262144,
        "google/gemma-4-31b-it:free": 262144,
        "qwen/qwen3.8-27b:free": 262144,
        "nvidia/nemotron-3-ultra-550b-a55b:free": 1000000,
        "meta-llama/llama-3.3-70b-instruct:free": 131072,
        "google/gemma-3-27b-it:free": 131072,
        "qwen/qwen-2.5-72b-instruct:free": 131072,
        "__default__": 131072,
    },
    "huggingface": {
        "meta-llama/Llama-3.1-8B-Instruct": 131072,
        "Qwen/Qwen2.5-7B-Instruct": 32768,
        "mistralai/Mistral-7B-Instruct-v0.3": 32768,
        "__default__": 32768,
    },
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars for English."""
    return len(text) // _CHARS_PER_TOKEN + 1


def get_model_context(model_name: str, provider: str = "gemini") -> int:
    """Get the max input context for a given model."""
    family = MODEL_CONTEXTS.get(provider, {})
    return family.get(model_name, family.get("__default__", 131072))


def fits_in_context(prompt: str, model_name: str, provider: str = "gemini",
                    reserve_output: int = 8192) -> bool:
    """Check if a prompt fits in the model's context window (with output reserve)."""
    tokens = estimate_tokens(prompt)
    max_ctx = get_model_context(model_name, provider)
    available = max_ctx - reserve_output
    return tokens <= available


def suggest_model(prompt: str, models: list, provider: str = "gemini",
                  reserve_output: int = 8192) -> str | None:
    """Find the first model whose context can fit the prompt."""
    for model in models:
        if fits_in_context(prompt, model, provider, reserve_output):
            return model
    return None


# ─── Script Caching ──────────────────────────────────────────────────

def cache_script(plan: dict, topic: str, llm_used: str):
    """Save the generated script plan to disk. Offline plans are never cached."""
    if "offline" in str(llm_used).lower():
        print("  script cache: skipped (offline plan)", flush=True)
        return
    os.makedirs(_CACHE_DIR, exist_ok=True)
    data = {
        "topic": topic,
        "llm_used": llm_used,
        "cached_at": datetime.datetime.now().isoformat(),
        "plan": plan,
    }
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  script cached: {_CACHE_FILE}", flush=True)


def load_cached_script() -> dict | None:
    """Load the most recently cached script plan."""
    if not os.path.exists(_CACHE_FILE):
        return None
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_cache():
    """Remove the script cache file."""
    if os.path.exists(_CACHE_FILE):
        os.remove(_CACHE_FILE)


# ─── Run State Tracking ──────────────────────────────────────────────

RUN_STEPS = [
    "topic_selected",
    "script_generated",
    "voices_synthesized",
    "visuals_downloaded",
    "video_rendered",
    "thumbnail_generated",
    "uploaded",
]


def save_run_state(step: str, data: dict = None):
    """Save which step the pipeline has completed so far."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    state = {"last_step": step, "updated_at": datetime.datetime.now().isoformat()}
    if data:
        state["data"] = data
    try:
        if os.path.exists(_RUN_STATE_FILE):
            with open(_RUN_STATE_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            existing.update(state)
            state = existing
    except (json.JSONDecodeError, OSError):
        pass
    with open(_RUN_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print(f"  run state: {step}", flush=True)


def get_run_state() -> dict:
    """Get the current run state."""
    if not os.path.exists(_RUN_STATE_FILE):
        return {"last_step": "", "data": {}}
    try:
        with open(_RUN_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_step": "", "data": {}}


def clear_run_state():
    """Clear the run state file."""
    if os.path.exists(_RUN_STATE_FILE):
        os.remove(_RUN_STATE_FILE)


def is_step_completed(step: str) -> bool:
    """Check if a given step has been completed."""
    state = get_run_state()
    steps = RUN_STEPS
    last_idx = steps.index(state["last_step"]) if state["last_step"] in steps else -1
    target_idx = steps.index(step) if step in steps else -1
    return target_idx <= last_idx



# ─── Per-stage checkpoints ───────────────────────────────────────────
# Each LLM stage saves its JSON output keyed by topic, so a re-run (or a
# retried job restored from actions/cache) skips stages that already
# succeeded and spends no quota on them.

import hashlib

_CKPT_DIR = os.path.join(_CACHE_DIR, "checkpoints")


def _ckpt_path(stage: str, topic: str) -> str:
    key = hashlib.sha1(topic.strip().lower().encode("utf-8")).hexdigest()[:12]
    return os.path.join(_CKPT_DIR, f"{key}--{stage}.json")


def save_stage(stage: str, topic: str, data, model: str = ""):
    """Checkpoint one stage's output. Offline outputs are not saved."""
    if "offline" in str(model).lower():
        return
    os.makedirs(_CKPT_DIR, exist_ok=True)
    payload = {"stage": stage, "topic": topic, "model": model,
               "saved_at": datetime.datetime.now().isoformat(), "data": data}
    with open(_ckpt_path(stage, topic), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print(f"  checkpoint saved: {stage}", flush=True)


def load_stage(stage: str, topic: str):
    """Return (data, model) for a saved stage, or (None, None)."""
    path = _ckpt_path(stage, topic)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("topic", "").strip().lower() != topic.strip().lower():
            return None, None
        print(f"  checkpoint hit: {stage} ({payload.get('model','')})", flush=True)
        return payload.get("data"), payload.get("model", "") + "(ckpt)"
    except (json.JSONDecodeError, OSError):
        return None, None


def clear_stages(topic: str):
    """Remove all checkpoints for a topic (after a successful upload)."""
    if not os.path.isdir(_CKPT_DIR):
        return
    prefix = os.path.basename(_ckpt_path("x", topic)).split("--")[0]
    for name in os.listdir(_CKPT_DIR):
        if name.startswith(prefix + "--"):
            os.remove(os.path.join(_CKPT_DIR, name))
