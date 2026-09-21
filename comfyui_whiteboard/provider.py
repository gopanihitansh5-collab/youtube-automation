"""Config-driven ComfyUI client for whiteboard scene illustrations.

No model is downloaded and no remote call is made unless COMFYUI_BASE_URL and
COMFYUI_API_KEY are both set. The caller owns stock/gradient fallbacks.
"""
from __future__ import annotations

import copy
import json
import os
import random
import time
import urllib.parse
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def _load_json(name: str) -> dict:
    with (HERE / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_config() -> dict:
    config = _load_json("config.json")
    for key, env_name in (
        ("base_url", config["base_url_env"]),
        ("api_key", config["api_key_env"]),
    ):
        config[key] = os.environ.get(env_name, "").strip()
    return config


def is_configured() -> bool:
    config = load_config()
    return bool(config["base_url"] and config["api_key"])


def build_scene_prompt(scene_text: str, keyword: str = "") -> str:
    """Create a compact, style-fixed prompt from narration and scene keyword."""
    style = _load_json("prompt_styles.json")["whiteboard"]["positive_prefix"]
    subject = " ".join((scene_text or keyword).split())[:600]
    focus = " ".join(keyword.split())[:120]
    detail = f" Main concept: {focus}." if focus else ""
    return f"{style}. Explain visually: {subject}.{detail} No readable text."


def _replace(value, substitutions):
    if isinstance(value, dict):
        return {key: _replace(item, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, substitutions) for item in value]
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        return substitutions[value[2:-2]]
    return value


def build_workflow(scene_text: str, keyword: str = "", seed: int | None = None) -> dict:
    config = load_config()
    styles = _load_json("prompt_styles.json")["whiteboard"]
    workflow = _load_json(config["workflow_path"])
    values = {
        "positive_prompt": build_scene_prompt(scene_text, keyword),
        "negative_prompt": styles["negative_prompt"],
        "seed": seed if seed is not None else random.SystemRandom().randint(1, 2**63 - 1),
        "steps": config["steps"],
        "cfg": config["cfg"],
        "width": config["width"],
        "height": config["height"],
        "checkpoint": config["checkpoint"],
    }
    return _replace(copy.deepcopy(workflow), values)


def _headers(config: dict) -> dict:
    return {
        "Content-Type": "application/json",
        config["api_key_header"]: config["api_key_prefix"] + config["api_key"],
    }


def render_scene(scene_text: str, keyword: str, out_path: str, seed: int | None = None) -> str:
    """Run one API-format workflow, wait for its image, and save it locally."""
    config = load_config()
    if not (config["base_url"] and config["api_key"]):
        raise RuntimeError("ComfyUI is disabled: endpoint or API key is missing")
    if config["checkpoint"].startswith("REPLACE_"):
        raise RuntimeError("ComfyUI checkpoint is not configured")

    base = config["base_url"].rstrip("/")
    headers = _headers(config)
    timeout = config["request_timeout_seconds"]
    response = requests.post(
        f"{base}/prompt",
        json={"prompt": build_workflow(scene_text, keyword, seed)},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    prompt_id = response.json()["prompt_id"]

    deadline = time.monotonic() + config["job_timeout_seconds"]
    output = None
    while time.monotonic() < deadline:
        history = requests.get(
            f"{base}/history/{prompt_id}", headers=headers, timeout=timeout
        )
        history.raise_for_status()
        job = history.json().get(prompt_id, {})
        for node in job.get("outputs", {}).values():
            if node.get("images"):
                output = node["images"][0]
                break
        if output:
            break
        time.sleep(config["poll_interval_seconds"])
    if not output:
        raise TimeoutError(f"ComfyUI job {prompt_id} produced no image before timeout")

    query = urllib.parse.urlencode(
        {
            "filename": output["filename"],
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        }
    )
    image = requests.get(f"{base}/view?{query}", headers=headers, timeout=timeout)
    image.raise_for_status()
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image.content)
    return str(target)
