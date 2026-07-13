# AI YouTube Video Pipeline

Generates faceless shorts and posts them to YouTube — runs entirely on GitHub
Actions. Every stage has fallbacks: even with zero API keys, the run finishes
with a watchable `output/final.mp4` you can download from the workflow artifact.

```
STAGE      FIRST CHOICE     FALLBACK 1        FALLBACK 2        LAST RESORT
─────────  ───────────────  ────────────────  ────────────────  ───────────────────
Topic      Google Sheet     topics.csv        built-in list     —
Script     Groq (free)      Gemini Flash      OpenRouter free   local Qwen GGUF
                              (free)             models             → offline builder
Voice      Kokoro (local,  edge-tts (neural)  espeak-ng         silent + captions
             82M params)
Visuals    Pexels videos    Pixabay videos    gradient shapes   animated background
                                              (energy-based)
Render     FFmpeg — crossfade transitions, ASS subtitles with rotating colors,
           parallax zoom, energy palettes, SD denoise, 1080×1920 H.264
Upload     YouTube API (only if secrets set; otherwise artifact only)
```

## Secrets — add what you have

Repo → **Settings → Secrets and variables → Actions**:

| Secret | What it gives |
|---|---|
| `GROQ_API_KEY` | Fastest script generation (Llama 3.3 70B) — get one free at console.groq.com |
| `GEMINI_API_KEY` | Fallback script provider — aistudio.google.com/apikey |
| `OPENROUTER_API_KEY` | Second fallback (free models only) — openrouter.ai |
| `HF_TOKEN` | Third fallback + Hugging Face model downloads — huggingface.co/settings/tokens |
| `PEXELS_API_KEY` | Stock video B-roll — pexels.com/api |
| `PIXABAY_API_KEY` | Backup stock video — pixabay.com/api/docs |
| `SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` | Topic management via Google Sheet (see below) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Auto-upload to YouTube |
| `ELEVENLABS_API_KEY` | Premium voice (falls back to Kokoro/edge-tts if unset) |

**No secrets?** The pipeline still renders a full video — download it from the
run's **video-output artifact**.

## Google Sheet (optional)

Header row: `topic | voice | privacy | status | youtube_url | date_posted`

- Blank `status` = pending. After posting it becomes `done` + the video URL.
- `voice`: `en-US-GuyNeural`, `en-US-AriaNeural`, etc.
- `privacy`: `unlisted` while testing.
- Setup: Cloud Console → enable **Sheets API** + **Drive API** → create a
  **service account** → download JSON → paste whole JSON into
  `GOOGLE_SERVICE_ACCOUNT_JSON` secret → **share the sheet with the service
  account's `client_email` as Editor**.

No sheet? Edit **`topics.csv`** in the repo instead.

## Script diversity

Every video gets a unique structure — the prompt builder randomises:
- **8 narrative arcs** (hero's journey, problem-solution, countdown, comparison, etc.)
- **16 script formats** (storytelling, educational, controversial, etc.)
- **5 hook styles**, **6 CTA types**, **4 tones**
- **3–8 scenes** with per-scene energy levels that affect visuals and pacing

Same topic → different script every time.

## Local models (auto-downloaded)

On first run, the pipeline downloads these to the runner and caches them:

| Model | Size | Purpose |
|---|---|---|
| Qwen2.5-7B-Q3_K_M GGUF | ~3 GB | Offline script generation |
| Kokoro TTS | ~82 MB | Offline neural voice |

After caching, script + voice work with **no internet**.

## Schedule

Runs every 3 hours: `cron: "30 */3 * * *"`. Trigger manually from the Actions
tab anytime.

## Run locally

```bash
pip install -r requirements.txt
python main.py
```

Output: `output/final.mp4`, `output/metadata.json`, `output/subs.ass`.

## Notes

- First run downloads ~3 GB of models (cached for subsequent runs).
- GitHub cron can drift; schedules pause after 60 days of repo inactivity.
- Keep `privacy: unlisted` until you trust the output — automated `public`
  posting risks strikes.
