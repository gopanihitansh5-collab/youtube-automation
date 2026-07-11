# 🎬 Auto AI YouTube Pipeline — provider-chain edition

Generates **1 faceless AI short per day** and posts it to YouTube — entirely on
GitHub Actions. No server, no GPU, and **it degrades gracefully**: every stage
has a chain of fallbacks, so even with **zero secrets and every API down**, a
run still finishes with a watchable `output/final.mp4` (downloadable from the
workflow's artifact).

```
STAGE      1st choice          2nd choice           3rd choice            last resort
─────────  ──────────────────  ───────────────────  ────────────────────  ─────────────────
Topic      Google Sheet        topics.csv (repo)    built-in list         —
Script     Gemini 2.0 Flash    HF router (Llama/    LOCAL Qwen2.5-3B      offline template
                               Qwen/Mistral)        GGUF on the runner
Voice      edge-tts (neural)   Piper (LOCAL         espeak-ng             silent + captions
                               neural, offline)
Visuals    Pexels videos       Pixabay videos       HF FLUX.1 AI images   animated gradient
                                                    (+ Ken Burns zoom)
Render     FFmpeg — always runs: captions, hook overlay, music, 1080x1920 H.264
Post       YouTube API (only if secrets set; otherwise video stays in output/ + artifact)
```

The **local models** (Qwen2.5-3B-Instruct GGUF ~2 GB + Piper voice ~63 MB) are
downloaded from Hugging Face **onto the Actions runner itself** on first run
and cached with `actions/cache` — after that, script + voice work with **no
external API at all**.

---

## 1. Push to GitHub

Push this folder to a new repo (root must contain `main.py`, `src/`,
`requirements.txt`, `.github/workflows/daily-video.yml`).

> Public repo = unlimited free Actions minutes. Private = 2,000 min/month free.

## 2. Add secrets — ALL OPTIONAL, add what you have

Repo → **Settings → Secrets and variables → Actions**:

| Secret | Gets you | Where |
|---|---|---|
| `GEMINI_API_KEY` | Best scripts | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `HF_TOKEN` | HF cloud LLMs + FLUX AI images | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (free account, "read" token) |
| `PEXELS_API_KEY` | Real stock B-roll | [pexels.com/api](https://www.pexels.com/api/) |
| `PIXABAY_API_KEY` | Backup stock B-roll | [pixabay.com/api/docs](https://pixabay.com/api/docs/) |
| `SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheet-driven topics + status write-back | see §3 |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Auto-posting | run `scripts/get_youtube_token.py` once locally |

**With zero secrets** the pipeline still renders a full video every day
(local/offline chain) — it just can't post it, so grab it from the run's
**video-output artifact**.

## 3. Google Sheet (optional but recommended)

Header row (row 1): `topic | voice | privacy | status | youtube_url | date_posted`

- Blank `status` = pending. After posting, the row gets `done` + the video URL.
- `voice`: any edge-tts voice (`en-US-AriaNeural`, `en-US-GuyNeural`, `en-IN-NeerjaNeural`…).
- `privacy`: use `unlisted` while testing.

Setup: Cloud Console → enable **Sheets API** + **Drive API** → create a
**service account** → download JSON key → paste whole JSON into the
`GOOGLE_SERVICE_ACCOUNT_JSON` secret → **share the sheet with the service
account's `client_email` as Editor** (the step everyone forgets).

No sheet? Edit **`topics.csv`** in the repo — it rotates one row per day.

## 4. Extras

- **Background music**: drop an `.mp3` into `assets/music/` — it's auto-mixed
  under the voice at 12% volume. (Use royalty-free tracks, e.g. YouTube Audio Library.)
- **Schedule**: `cron: "30 3 * * *"` (= 09:00 IST) in the workflow file.
- **Test now**: Actions tab → *Daily AI YouTube Video* → **Run workflow**.
- **Force no-upload test**: set env `SKIP_UPLOAD: "1"` in the workflow.

## 5. Run locally (Windows/Mac/Linux)

```bash
pip install -r requirements.txt   # plus ffmpeg on your PATH
python main.py                    # with no env vars -> full offline render
```
Output lands in `output/final.mp4` + `output/metadata.json` (which records
exactly which provider was used at every stage — check it when debugging).

## Notes & limits
- First Actions run downloads ~2 GB of local models (cached afterwards); a
  cached offline run takes roughly 10–20 min including local LLM inference.
- GitHub cron can drift a few minutes; schedules pause after 60 days of repo inactivity.
- YouTube API default quota comfortably covers 1 upload/day.
- Auto-posting `public` with zero review risks strikes — stay `unlisted` until you trust it.
