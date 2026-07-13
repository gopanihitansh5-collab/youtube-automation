"""
Daily AI YouTube pipeline -- orchestrator.

Design rule: THE VIDEO ALWAYS RENDERS. Every stage has a fallback chain
(cloud API -> local model -> offline), so even with zero secrets and no
internet the run finishes with output/final.mp4 + output/metadata.json.
Uploading to YouTube is best-effort on top of that.

  Google Sheet | topics.csv | built-in
    -> Groq | Gemini | OpenRouter | HuggingFace | local Qwen GGUF | template   (script)
    -> ElevenLabs | Kokoro local | edge-tts | espeak | silent                  (voice)
    -> Pexels | Pixabay | gradient                                              (visuals)
    -> FFmpeg (Ken Burns, word-captions, zoom-hook, music, mux)
    -> YouTube upload + comment pin + thumbnail generation
    -> Sheet write-back (status + script metadata)
    -> Analytics tracking
"""
import os
import sys
import json
import traceback


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if v and not os.environ.get(k):
                os.environ[k] = v


_load_dotenv()

from src import sheets, editor  # noqa: E402
from src.providers import llm, voice as voice_provider, visuals

# Optional modules -- silently skipped if missing or unconfigured
try:
    from src import thumbnail as thumb_mod
except ImportError:
    thumb_mod = None

try:
    from src import youtube_analytics as analytics_mod
except ImportError:
    analytics_mod = None


INTRO_DUR = 2.5  # seconds for the hook-first visual intro


def main():
    print("=== Daily AI Video Pipeline (full-feature edition) ===", flush=True)
    os.makedirs("output", exist_ok=True)
    report = {"providers": {}, "scenes": []}

    # ---- 0) pre-download models for caching (best-effort) -----------------
    try:
        from src.providers.local_models import ensure_kokoro, ensure_llm
        print("  downloading Kokoro TTS model (~350 MB) ...", flush=True)
        ensure_kokoro()
        if os.environ.get("LOCAL_LLM", "").strip() in ("1", "true", "yes"):
            print("  downloading local LLM model (~2 GB) ...", flush=True)
            ensure_llm()
    except Exception as e:
        print(f"  model pre-download skipped: {e}", flush=True)

    # ---- 0) analytics pre-check (optional) --------------------------------
    if analytics_mod:
        try:
            prior_urls = sheets.get_recent_urls(limit=3)
            analytics_mod.check_and_flag(prior_urls)
        except Exception as e:
            print(f"  analytics pre-check skipped: {e}", flush=True)

    # ---- 1) topic --------------------------------------------------------
    item = sheets.get_next_item()
    if item is None:
        return 0
    topic = str(item.get("topic", "")).strip()
    voice_name = str(item.get("voice") or "en-US-AriaNeural").strip()
    privacy = str(item.get("privacy") or "unlisted").strip().lower()
    report["providers"]["topic_source"] = item["source"]
    print(f"Topic [{item['source']}]: {topic!r} | voice={voice_name} | privacy={privacy}",
          flush=True)

    # ---- 2) content plan -------------------------------------------------
    meta = None
    pre_written = str(item.get("script_title") or "").strip()
    if pre_written and str(item.get("script_desc") or "").strip():
        sheet_ctx = {
            "title": pre_written,
            "hook": str(item.get("script_hook") or "Watch till the end").strip(),
            "desc": str(item.get("script_desc", "")).strip(),
        }
        plan, llm_used, meta = llm.generate_plan(topic, extra_context=sheet_ctx)
        plan["title"] = pre_written
        plan["hook"] = sheet_ctx["hook"]
        plan["description"] = sheet_ctx["desc"]
        plan["tags"] = [t.strip() for t in str(item.get("script_tags", "")).split(",") if t.strip()]
        llm_used = f"sheet+{llm_used}"
        print(f"  Sheet context -> {llm_used}", flush=True)
    else:
        plan, llm_used, meta = llm.generate_plan(topic)

    if not plan.get("scenes"):
        offline = llm._offline(plan["title"])
        plan["scenes"] = offline["scenes"]
        if not llm_used.startswith("sheet+"):
            llm_used = "offline-fallback"

    report["providers"]["script"] = llm_used
    scenes = plan["scenes"]
    hook = plan["hook"]
    print(f"Title: {plan['title']}\nHook : {hook}\nScenes: {len(scenes)}",
          flush=True)
    sheets.write_script_metadata(item, plan)

    # ---- 3) prepend hook-intro scene --------------------------------------
    intro_scene = {
        "narration": hook,
        "keyword": (
            "Dynamic intro scene with bold animated text overlay, "
            "abstract geometric background, vibrant neon colors, "
            "fast-paced cinematic motion blur, professional title card"
        ),
    }
    scenes.insert(0, intro_scene)

    # ---- 4) voiceover and visuals per scene, all in parallel --------------
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

    _VOICE_TIMEOUT = 120
    _VISUAL_TIMEOUT = 600

    def _voice_job(i_sc):
        i, sc = i_sc
        return voice_provider.synth(sc["narration"], voice_name, f"output/aud_{i}.mp3")

    def _visual_job(i_sc):
        i, sc = i_sc
        return visuals.get_visual(sc["keyword"], f"output/vis_{i}", scene_index=i)

    voice_results = [None] * len(scenes)
    visual_results = [None] * len(scenes)

    with ThreadPoolExecutor(max_workers=6) as pool:
        voice_futs = {pool.submit(_voice_job, iv): iv for iv in enumerate(scenes)}
        visual_futs = {pool.submit(_visual_job, iv): iv for iv in enumerate(scenes)}

        for fut in as_completed(voice_futs, timeout=_VOICE_TIMEOUT * len(scenes)):
            i, _ = voice_futs[fut]
            try:
                voice_results[i] = fut.result(timeout=10)
            except FuturesTimeout:
                print(f"  WARNING: voice scene {i} timed out after {_VOICE_TIMEOUT}s", flush=True)
                voice_results[i] = (None, [], 0.0, "silent")
            except Exception as e:
                print(f"  WARNING: voice scene {i} failed: {e}", flush=True)
                voice_results[i] = (None, [], 0.0, "silent")

        for fut in as_completed(visual_futs, timeout=_VISUAL_TIMEOUT * len(scenes)):
            i, _ = visual_futs[fut]
            try:
                visual_results[i] = fut.result(timeout=10)
            except FuturesTimeout:
                print(f"  WARNING: visual scene {i} timed out after {_VISUAL_TIMEOUT}s", flush=True)
                visual_results[i] = (None, None, "gradient-fallback")
            except Exception as e:
                print(f"  WARNING: visual scene {i} failed: {e}", flush=True)
                visual_results[i] = (None, None, "gradient-fallback")

    scene_audios, scene_words, durations, voice_used = [], [], [], set()
    for i, (path, words, used) in enumerate(voice_results):
        real = editor.probe_duration(path)
        if i == 0 and real < INTRO_DUR:
            print(f"  padding intro audio {real:.1f}s -> {INTRO_DUR}s", flush=True)
            padded = path.replace(".mp3", "_padded.mp3")
            editor._run(["ffmpeg", "-y", "-i", path,
                         "-af", f"apad=pad_dur={INTRO_DUR - real:.1f}",
                         "-t", f"{INTRO_DUR:.2f}",
                         "-c:a", "libmp3lame", "-b:a", "128k", padded])
            path, real = padded, INTRO_DUR
            if words:
                last_w = words[-1]
                words[-1] = (last_w[0], last_w[1], max(last_w[2], INTRO_DUR))
        scene_audios.append(path)
        scene_words.append(words)
        durations.append(real)
        voice_used.add(used)
        print(f"  scene {i}: {real:.1f}s voice={used} ({scenes[i]['keyword']})",
              flush=True)
    report["providers"]["voice"] = sorted(voice_used)

    scene_visuals = []
    for i, (path, kind, used) in enumerate(visual_results):
        scene_visuals.append((path, kind, used))
        report["scenes"].append({"keyword": scenes[i]["keyword"], "visual": used})
        print(f"  scene {i}: visual={used}", flush=True)

    # ---- 5) render -------------------------------------------------------
    scene_energies = meta.get("scene_energies") if meta else None
    final = editor.build(scene_visuals, scene_audios, scene_words,
                         durations, hook, "output/final.mp4",
                         scene_energies=scene_energies)
    dur = editor.probe_duration(final)
    print(f"\nRendered: {final} ({dur:.1f}s)", flush=True)

    # ---- 6) thumbnail (best-effort) --------------------------------------
    thumb_path = "output/thumbnail.png"
    try:
        if thumb_mod:
            thumb_mod.make(hook, final, thumb_path)
            print(f"Thumbnail: {thumb_path}", flush=True)
        else:
            print("  thumbnail module not available", flush=True)
    except Exception as e:
        print(f"  thumbnail generation failed: {e}", flush=True)

    # ---- 7) save metadata next to the video -------------------------------
    report.update({"topic": topic, "title": plan["title"],
                   "description": plan["description"], "tags": plan["tags"],
                   "hook": hook, "duration_sec": round(dur, 1),
                   "privacy": privacy, "youtube_url": None,
                   "thumbnail": thumb_path if os.path.exists(thumb_path) else None})
    with open("output/metadata.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ---- 8) upload (best-effort) -----------------------------------------
    yt_ready = all(os.environ.get(k) for k in
                   ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if os.environ.get("SKIP_UPLOAD", "").lower() in ("1", "true", "yes"):
        print("SKIP_UPLOAD set -- video kept in output/ only.")
    elif not yt_ready:
        print("YouTube secrets not configured -- video kept in output/ only.")
    else:
        try:
            from src import youtube_upload
            url = youtube_upload.upload(final, plan["title"],
                                        plan["description"], plan["tags"], privacy,
                                        hook=plan.get("hook"))
            report["youtube_url"] = url
            with open("output/metadata.json", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"Uploaded: {url}", flush=True)
            sheets.mark_done(item, url)
        except Exception as e:
            print(f"WARNING: upload failed ({e}) -- the rendered video is still "
                  f"in output/final.mp4 and in the workflow artifact.")

    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
