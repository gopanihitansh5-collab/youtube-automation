"""Download-once helpers for models that run ON the runner (CPU).

Models land in ./models (cached between workflow runs by actions/cache):
  - LLM  : Qwen2.5-3B-Instruct GGUF Q4_K_M (~2.0 GB), runs via llama-cpp-python
  - Voice: Kokoro-82M (~350 MB), 82M-param neural TTS, fully offline
"""
import os

MODELS_DIR = os.environ.get("MODELS_DIR", "models")

LLM_REPO = os.environ.get("LOCAL_LLM_REPO", "Qwen/Qwen2.5-3B-Instruct-GGUF")
LLM_FILE = os.environ.get("LOCAL_LLM_FILE", "qwen2.5-3b-instruct-q4_k_m.gguf")


def _download(repo_id, filename):
    from huggingface_hub import hf_hub_download
    os.makedirs(MODELS_DIR, exist_ok=True)
    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=MODELS_DIR,
        token=os.environ.get("HF_TOKEN") or None,
    )


def ensure_llm():
    return _download(LLM_REPO, LLM_FILE)


def ensure_kokoro():
    from huggingface_hub import snapshot_download
    model_dir = os.path.join(MODELS_DIR, "kokoro")
    if not os.path.isdir(model_dir):
        os.makedirs(model_dir, exist_ok=True)
        snapshot_download(
            repo_id="hexgrad/Kokoro-82M",
            local_dir=model_dir,
            token=os.environ.get("HF_TOKEN") or None,
        )
    from kokoro import KPipeline
    return KPipeline(lang_code="a")
