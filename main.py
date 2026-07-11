"""
Daily AI YouTube pipeline — orchestrator.

Design rule: THE VIDEO ALWAYS RENDERS. Every stage has a fallback chain
(cloud API -> local model -> offline), so even with zero secrets and no
internet the run finishes with output/final.mp4 + output/metadata.json.
Uploading to YouTube is best-effort on top of that.

  Google Sheet | topics.csv | built-in
    -> Gemini | HF router | local Qwen GGUF | template     (script/hook/tags)
    -> edge-tts | Piper local | espeak | silent            (voice + timings)
    -> Pexels | Pixabay | HF FLUX image | gradient         (visuals)
    -> FFmpeg (Ken Burns, captions, hook, music, mux)
    -> YouTube upload (optional) -> sheet write-back (optional)
"""
import os
import sys
import json
import traceback


def _load_dotenv(path=".env"):
    """Tiny zero-dependency .env loader for local runs (no-op on Actions)."""
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

from src import sheets, editor  # noqa: E402  (env must load first)
from src.providers import llm, voice as voice_provider, visuals


def main():
    print("=== Daily AI Video Pipeline (provider-chain edition) ===", flush=True)
    os.makedirs("output", exist_ok=True)
    report = {"providers": {}, "scenes": []}

    # ---- 1) topic --------------------------------------------------------
    item = sheets.get_next_item()
    if item is None:
        return 0  # sheet says: nothing pending today
    topic = str(item.get("topic", "")).strip()
    voice_name = str(item.get("voice") or "en-US-AriaNeural").strip()
    privacy = str(item.get("privacy") or "unlisted").strip().lower()
    report["providers"]["topic_source"] = item["source"]
    print(f"Topic [{item['source']}]: {topic!r} | voice={voice_name} | privacy={privacy}",
          flush=True)

    # ---- 2) content plan -------------------------------------------------
    plan, llm_used = llm.generate_plan(topic)
    report["providers"]["script"] = llm_used
    scenes = plan["scenes"]
    print(f"Title: {plan['title']}\nHook : {plan['hook']}\nScenes: {len(scenes)}",
          flush=True)

    # ---- 3+4) voiceover and visuals per scene, all in parallel ------------
    from concurrent.futures import ThreadPoolExecutor

    def _voice_job(i_sc):
        i, sc = i_sc
        return voice_provider.synth(sc["narration"], voice_name, f"output/aud_{i}.mp3")

    def _visual_job(i_sc):
        i, sc = i_sc
        return visuals.get_visual(sc["keyword"], f"output/vis_{i}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        voice_results = pool.map(_voice_job, enumerate(scenes))
        visual_results = pool.map(_visual_job, enumerate(scenes))
        voice_results = list(voice_results)
        visual_results = list(visual_results)

    scene_audios, scene_words, durations, voice_used = [], [], [], set()
    for i, (path, words, used) in enumerate(voice_results):
        real = editor.probe_duration(path)
        scene_audios.append(path)
        scene_words.append(words)
        durations.append(real)
        voice_used.add(used)
        print(f"  scene {i}: {real:.1f}s voice={used} ({scenes[i]['keyword']})",
              flush=True)
    report["providers"]["voice"] = sorted(voice_used)

    scene_visuals = []
    for i, (path, kind, used) in enumerate(visual_results):
        scene_visuals.append((path, kind))
        report["scenes"].append({"keyword": scenes[i]["keyword"], "visual": used})
        print(f"  scene {i}: visual={used}", flush=True)

    # ---- 5) render (this ALWAYS happens) ----------------------------------
    final = editor.build(scene_visuals, scene_audios, scene_words,
                         durations, plan["hook"], "output/final.mp4")
    dur = editor.probe_duration(final)
    print(f"\nRendered: {final} ({dur:.1f}s)", flush=True)

    # ---- 6) save metadata next to the video -------------------------------
    report.update({"topic": topic, "title": plan["title"],
                   "description": plan["description"], "tags": plan["tags"],
                   "hook": plan["hook"], "duration_sec": round(dur, 1),
                   "privacy": privacy, "youtube_url": None})
    with open("output/metadata.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ---- 7) upload (best-effort) ------------------------------------------
    yt_ready = all(os.environ.get(k) for k in
                   ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if os.environ.get("SKIP_UPLOAD", "").lower() in ("1", "true", "yes"):
        print("SKIP_UPLOAD set — video kept in output/ only.")
    elif not yt_ready:
        print("YouTube secrets not configured — video kept in output/ only.")
    else:
        try:
            from src import youtube_upload
            url = youtube_upload.upload(final, plan["title"],
                                        plan["description"], plan["tags"], privacy)
            report["youtube_url"] = url
            with open("output/metadata.json", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"Uploaded: {url}", flush=True)
            sheets.mark_done(item, url)
        except Exception as e:
            print(f"WARNING: upload failed ({e}) — the rendered video is still "
                  f"in output/final.mp4 and in the workflow artifact.")

    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
