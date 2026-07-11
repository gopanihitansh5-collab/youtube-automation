"""Download-once helpers for models that run ON the runner (CPU).

Models land in ./models (cached between workflow runs by actions/cache):
  - LLM  : Qwen2.5-3B-Instruct GGUF Q4_K_M (~2.0 GB), runs via llama-cpp-python
  - Voice: Piper en_US-amy-medium (~63 MB), neural TTS, fully offline
"""
import os

MODELS_DIR = os.environ.get("MODELS_DIR", "models")

# Override via env to run a different GGUF on the runner, e.g. Gemma 3n/4 E4B:
#   LOCAL_LLM_REPO=unsloth/gemma-3n-E4B-it-GGUF
#   LOCAL_LLM_FILE=gemma-3n-E4B-it-Q4_K_M.gguf
# NOTE: raw transformers repos (e.g. google/gemma-*-it safetensors) are NOT
# runnable on a CPU runner — always pick a GGUF quantization. Google's Gemma
# repos are also license-gated: accept the license on HF and set HF_TOKEN.
LLM_REPO = os.environ.get("LOCAL_LLM_REPO", "Qwen/Qwen2.5-3B-Instruct-GGUF")
LLM_FILE = os.environ.get("LOCAL_LLM_FILE", "qwen2.5-3b-instruct-q4_k_m.gguf")

PIPER_REPO = "rhasspy/piper-voices"
PIPER_FILE = "en/en_US/amy/medium/en_US-amy-medium.onnx"


def _download(repo_id, filename):
    from huggingface_hub import hf_hub_download
    os.makedirs(MODELS_DIR, exist_ok=True)
    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=MODELS_DIR,
        token=os.environ.get("HF_TOKEN") or None,  # both models are ungated; token optional
    )


def ensure_llm():
    """Return local path to the GGUF, downloading it on first use."""
    return _download(LLM_REPO, LLM_FILE)


def ensure_piper_voice():
    """Return (onnx_path, json_path) for the Piper voice."""
    onnx = _download(PIPER_REPO, PIPER_FILE)
    cfg = _download(PIPER_REPO, PIPER_FILE + ".json")
    return onnx, cfg
