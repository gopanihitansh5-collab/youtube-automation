"""Long-form video orchestrator — 8-15min landscape YouTube videos.

Reuses provider infrastructure from src/providers/ but with chapter-based
prompts, search-grounded Gemini, Imagen 4 thumbnails, and landscape rendering.

Provider chain for scripts: Groq → Gemini (search-grounded) → OpenRouter → HF → offline
"""
import os
import sys
import csv
import json
import re
import datetime
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv(path=".env"):
    full = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    if not os.path.exists(full):
        return
    with open(full, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if v and not os.environ.get(k):
                os.environ[k] = v


_load_dotenv()

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

from src import sheets
from src.providers import voice as voice_provider, visuals

LONG_CSV = os.path.join(os.path.dirname(__file__), "topics_long.csv")

LONG_FALLBACK = [
    {"topic": "How Bitcoin Mining Actually Works — Full Breakdown",
     "voice": "en-US-AriaNeural", "privacy": "unlisted"},
    {"topic": "The Psychology of Money: 10 Timeless Lessons",
     "voice": "en-US-GuyNeural", "privacy": "unlisted"},
    {"topic": "Why Most Startups Fail in the First Year",
     "voice": "en-US-AriaNeural", "privacy": "unlisted"},
]


def _get_topic():
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and os.environ.get("SHEET_ID"):
        try:
            item = sheets._from_sheet()
            if item:
                return item
        except Exception as e:
            print(f"Sheet unavailable ({e}) -> long CSV", flush=True)
    if os.path.exists(LONG_CSV):
        try:
            with open(LONG_CSV, newline="", encoding="utf-8-sig") as f:
                rows = [r for r in csv.DictReader(f) if (r.get("topic") or "").strip()]
            if rows:
                pick = rows[datetime.date.today().timetuple().tm_yday % len(rows)]
                return {"row_idx": None, "source": "topics_long.csv", **pick}
        except Exception as e:
            print(f"long CSV error ({e}) -> built-in", flush=True)
    pick = LONG_FALLBACK[
        datetime.date.today().timetuple().tm_yday % len(LONG_FALLBACK)]
    return {"row_idx": None, "source": "built-in", **pick}
from longform_prompt import build_long_prompt, build_offline_long_script
from editor_long import build as editor_build, probe_duration
from thumbnail import make as make_thumbnail

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
    "qwen-2.5-32b",
]

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]

OPENROUTER_MODELS = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

HF_MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
]


def _validate_long(data, topic):
    chapters = data.get("chapters") or []
    valid_chapters = []
    for ch in chapters:
        scenes = ch.get("scenes") or []
        scenes = [s for s in scenes
                  if isinstance(s, dict) and s.get("narration") and s.get("keyword")]
        if scenes:
            valid_chapters.append({
                "title": str(ch.get("title") or "Chapter")[:80],
                "timestamp_sec": max(0, int(ch.get("timestamp_sec", 0))),
                "scenes": scenes[:12],
            })
    if len(valid_chapters) < 2:
        raise ValueError(f"only {len(valid_chapters)} valid chapters")
    total_scenes = sum(len(ch["scenes"]) for ch in valid_chapters)
    if total_scenes < 8:
        raise ValueError(f"only {total_scenes} total scenes across chapters")
    return {
        "title": str(data.get("title") or topic)[:120],
        "description": str(data.get("description") or ""),
        "tags": [str(t)[:60] for t in (data.get("tags") or [])][:15],
        "hook": str(data.get("hook") or "Watch till the end")[:120],
        "comment": str(data.get("comment") or "What did you think?")[:300],
        "virality_score": max(0.0, min(1.0, float(data.get("virality_score", 0)))),
        "attention_score": max(0.0, min(1.0, float(data.get("attention_score", 0)))),
        "chapters": valid_chapters,
    }


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


def _groq_long(topic, prompt, temperature):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    last_err = None
    for model in GROQ_MODELS:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8192,
                    "temperature": temperature,
                },
                timeout=180,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate_long(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    Groq model {model} failed: {e}")
    raise RuntimeError(f"all Groq models failed: {last_err}")


def _gemini_search_long(topic, prompt, temperature):
    """Gemini with search grounding for factually accurate scripts."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    last_err = None
    for model in GEMINI_MODELS:
        try:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": temperature,
                    "maxOutputTokens": 8192,
                },
                "tools": [{"googleSearchRetrieval": {}}],
            }
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=180,
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            grounding = r.json().get("candidates", [{}])[0].get("groundingMetadata")
            if grounding:
                sources = grounding.get("groundingChunks", [])
                print(f"      search grounded with {len(sources)} sources", flush=True)
            return _validate_long(_extract_json(text), topic)
        except Exception as e:
            last_err = e
            print(f"    Gemini search model {model} failed: {e}")
    raise RuntimeError(f"all Gemini models failed: {last_err}")


def _openrouter_long(topic, prompt, temperature):
    token = os.environ.get("OPENROUTER_API_KEY")
    if not token:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    last_err = None
    for model in OPENROUTER_MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8192,
                    "temperature": temperature,
                },
                timeout=180,
            )
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "unknown error"))
            content = body["choices"][0]["message"]["content"]
            return _validate_long(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    OpenRouter model {model} failed: {e}")
    raise RuntimeError(f"all OpenRouter free models failed: {last_err}")


def _huggingface_long(topic, prompt, temperature):
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN not set")
    last_err = None
    for model in HF_MODELS:
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8192,
                    "temperature": temperature,
                },
                timeout=180,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate_long(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    HF model {model} failed: {e}")
    raise RuntimeError(f"all HF models failed: {last_err}")


def _generate_long_plan(topic):
    import random
    dyn_prompt, meta = build_long_prompt(topic)
    rng = random.Random()
    temp = round(rng.uniform(0.65, 0.95), 2)

    print(f"  arc: {meta['arc']} | chapters: {meta['num_chapters']} | "
          f"scenes/ch: {meta['scenes_per_chapter']} | temp: {temp}", flush=True)

    chain = []
    if os.environ.get("GROQ_API_KEY"):
        chain.append(("groq-llama3.3-70b", lambda: _groq_long(topic, dyn_prompt, temp)))
    if os.environ.get("GEMINI_API_KEY"):
        chain.append(("gemini-search", lambda: _gemini_search_long(topic, dyn_prompt, temp)))
    if os.environ.get("OPENROUTER_API_KEY"):
        chain.append(("openrouter-free", lambda: _openrouter_long(topic, dyn_prompt, temp)))
    if os.environ.get("HF_TOKEN"):
        chain.append(("huggingface-router", lambda: _huggingface_long(topic, dyn_prompt, temp)))
    chain.append(("offline-builder", lambda: build_offline_long_script(topic, meta)))

    for name, fn in chain:
        try:
            plan = fn()
            print(f"  script provider: {name}", flush=True)
            print(f"  chapters: {len(plan['chapters'])} | "
                  f"total scenes: {sum(len(c['scenes']) for c in plan['chapters'])}",
                  flush=True)
            return plan, name, meta
        except Exception as e:
            print(f"  script provider {name} unavailable: {e}", flush=True)
    plan = build_offline_long_script(topic, meta)
    return plan, "offline-builder", meta





def _chapter_timestamps(chapters):
    lines = []
    for ch in chapters:
        sec = ch.get("timestamp_sec", 0)
        minutes = sec // 60
        seconds = sec % 60
        ts = f"{minutes}:{seconds:02d}"
        lines.append(f"{ts} - {ch['title']}")
    return "\n".join(lines)


def main():
    print("=== Long-Form Video Pipeline (8-15 min, landscape 1920x1080) ===",
          flush=True)
    os.makedirs("output_long", exist_ok=True)
    report = {"providers": {}, "chapters": []}

    item = _get_topic()
    if item is None:
        return 0
    topic = str(item.get("topic", "")).strip()
    voice_name = str(item.get("voice") or "en-US-AriaNeural").strip()
    privacy = str(item.get("privacy") or "unlisted").strip().lower()
    report["providers"]["topic_source"] = item["source"]
    print(f"Topic [{item['source']}]: {topic!r} | voice={voice_name} | privacy={privacy}",
          flush=True)

    plan, llm_used, meta = _generate_long_plan(topic)
    report["providers"]["script"] = llm_used
    chapters = plan["chapters"]
    hook = plan["hook"]
    print(f"Title: {plan['title']}\nHook: {hook}\nChapters: {len(chapters)}"
          f"\nTotal scenes: {sum(len(c['scenes']) for c in chapters)}", flush=True)

    v = plan.get("virality_score", 0)
    a = plan.get("attention_score", 0)
    if v < 0.65 or a < 0.65:
        print(f"  WARNING: scores ({v:.2f}, {a:.2f}) below 0.65 threshold",
              flush=True)

    sheets.write_script_metadata(item, plan)

    all_scenes = []
    for ch in chapters:
        for sc in ch["scenes"]:
            all_scenes.append(sc)

    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
    _VOICE_TIMEOUT = 120
    _VISUAL_TIMEOUT = 120

    def _voice_job(i_sc):
        i, sc = i_sc
        return voice_provider.synth(sc["narration"], voice_name,
                                    f"output_long/aud_{i}.mp3")

    def _visual_job(i_sc):
        i, sc = i_sc
        return visuals.get_visual(sc["keyword"], f"output_long/vis_{i}",
                                  scene_index=i, orientation="landscape")

    voice_results = [None] * len(all_scenes)
    visual_results = [None] * len(all_scenes)

    with ThreadPoolExecutor(max_workers=6) as pool:
        voice_futs = {pool.submit(_voice_job, iv): iv for iv in enumerate(all_scenes)}
        visual_futs = {pool.submit(_visual_job, iv): iv for iv in enumerate(all_scenes)}

        for fut in as_completed(voice_futs, timeout=_VOICE_TIMEOUT * len(all_scenes)):
            i, _ = voice_futs[fut]
            try:
                voice_results[i] = fut.result(timeout=10)
            except FuturesTimeout:
                print(f"  WARNING: voice scene {i} timed out", flush=True)
                voice_results[i] = (None, [], 0.0, "silent")
            except Exception as e:
                print(f"  WARNING: voice scene {i} failed: {e}", flush=True)
                voice_results[i] = (None, [], 0.0, "silent")

        for fut in as_completed(visual_futs, timeout=_VISUAL_TIMEOUT * len(all_scenes)):
            i, _ = visual_futs[fut]
            try:
                visual_results[i] = fut.result(timeout=10)
            except FuturesTimeout:
                print(f"  WARNING: visual scene {i} timed out", flush=True)
                visual_results[i] = (None, None, "gradient-fallback")
            except Exception as e:
                print(f"  WARNING: visual scene {i} failed: {e}", flush=True)
                visual_results[i] = (None, None, "gradient-fallback")

    scene_audios, scene_words, durations, voice_used = [], [], [], set()
    for i, res in enumerate(voice_results):
        path, words, used = (res[0], res[1], res[3]) if len(res) >= 4 else (res[0], res[1], "kokoro")
        dur = probe_duration(path) if path else 5.0
        if dur < 2.0:
            dur = 5.0
        scene_audios.append(path)
        scene_words.append(words or [])
        durations.append(dur)
        voice_used.add(used)
        print(f"  scene {i}: {dur:.1f}s voice={used}", flush=True)
    report["providers"]["voice"] = sorted(voice_used)

    scene_visuals = []
    for i, (path, kind, used) in enumerate(visual_results):
        scene_visuals.append((path, kind, used))
        report["scenes"].append({"keyword": all_scenes[i]["keyword"],
                                 "visual": used})
        print(f"  scene {i}: visual={used}", flush=True)

    chapter_durations = []
    scene_idx = 0
    for ch in chapters:
        ch_durs = []
        for _ in ch["scenes"]:
            if scene_idx < len(durations):
                ch_durs.append(durations[scene_idx])
            else:
                ch_durs.append(5.0)
            scene_idx += 1
        chapter_durations.append(ch_durs)

    ch_ts = _chapter_timestamps(chapters)
    full_desc = plan.get("description", "")
    if ch_ts:
        full_desc += f"\n\n{ch_ts}"

    final = editor_build(
        chapters, scene_visuals, scene_audios, scene_words,
        chapter_durations, hook, "output_long/final.mp4",
        title=plan.get("title", ""),
        description=full_desc,
        tags=plan.get("tags", []),
    )
    dur = probe_duration(final) if final and os.path.exists(final) else 0
    print(f"\nRendered: {final} ({dur:.1f}s)", flush=True)

    thumb_path = "output_long/thumbnail.jpg"
    try:
        print("  generating enhanced thumbnail ...", flush=True)
        make_thumbnail(
            title=plan.get("title", ""),
            hook=hook,
            video_path=final,
            out_path=thumb_path,
            style="bold_split",
        )
    except Exception as e:
        print(f"  thumbnail generation failed: {e}", flush=True)

    report.update({
        "topic": topic, "title": plan["title"],
        "description": full_desc, "tags": plan["tags"],
        "hook": hook, "duration_sec": round(dur, 1),
        "privacy": privacy, "youtube_url": None,
        "thumbnail": thumb_path if os.path.exists(thumb_path) else None,
    })
    with open("output_long/metadata.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    yt_ready = all(os.environ.get(k) for k in
                   ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if os.environ.get("SKIP_UPLOAD", "").lower() in ("1", "true", "yes"):
        print("SKIP_UPLOAD set -- video kept in output_long/ only.", flush=True)
    elif not yt_ready:
        print("YouTube secrets not configured -- video kept in output_long/ only.",
              flush=True)
    else:
        try:
            from src import youtube_upload
            url = youtube_upload.upload(
                final, plan["title"], full_desc, plan["tags"], privacy,
                hook=plan.get("hook"), comment=plan.get("comment"),
            )
            report["youtube_url"] = url
            with open("output_long/metadata.json", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"Uploaded: {url}", flush=True)
            sheets.mark_done(item, url)
        except Exception as e:
            print(f"WARNING: upload failed ({e}) -- video in output_long/",
                  flush=True)

    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
