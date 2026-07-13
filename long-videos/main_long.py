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
import random
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
from done_tracker import is_done, mark_done, filter_undone
from web_search_tool import (search_web, get_daily_briefing, get_trending_news,
                             get_multi_region_trends, search_web_by_region,
                             get_india_major_events,
                             REGIONS, PRIORITY_REGIONS)
from topic_context import (TopicContext, parse_topic_context, store_context,
                           build_script_context_block, build_thumbnail_context,
                           build_transcript_context, integrate_context_into_pipeline)
from script_cache import (cache_script, load_cached_script, clear_cache,
                          save_run_state, get_run_state, is_step_completed,
                          clear_run_state, estimate_tokens, suggest_model)
from caption_emphasis import tag_all_scenes
from multi_llm_pipeline import run_full_pipeline

# Module-level cache for trending context (populated by _get_topic, consumed by _generate_long_plan)
_TRENDING_CTX = {"region_data": [], "best_video_topic": None, "global_pulse": ""}
_TOPIC_CTX: TopicContext | None = None  # parsed topic context, used by all pipeline stages

LONG_CSV = os.path.join(os.path.dirname(__file__), "topics_long.csv")

LONG_FALLBACK = [
    {"topic": "How Bitcoin Mining Actually Works — Full Breakdown",
     "voice": "en-US-AriaNeural", "privacy": "unlisted"},
    {"topic": "The Psychology of Money: 10 Timeless Lessons",
     "voice": "en-US-GuyNeural", "privacy": "unlisted"},
    {"topic": "Why Most Startups Fail in the First Year",
     "voice": "en-US-AriaNeural", "privacy": "unlisted"},
]


def _sheet_available():
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and os.environ.get("SHEET_ID"))


def _from_sheet_long():
    """Get next undone topic from sheet, filtering for long-form type if column exists."""
    ws = sheets._worksheet()
    for i, rec in enumerate(ws.get_all_records()):
        status = str(rec.get("status", "")).strip().lower()
        if status not in ("", "pending", "todo", "queue", "queued"):
            continue
        rec = {str(k).lower(): v for k, v in rec.items()}
        typ = str(rec.get("type", "")).strip().lower()
        if typ and typ not in ("long", "long-form", "longform", "video"):
            continue
        return {"row_idx": i + 2, "source": "google-sheet", **rec}
    return None


def _fetch_regional_trends():
    """Fetch trending topics across USA, Australia, UK, India, etc. via web search.
    
    Populates the module-level _TRENDING_CTX cache.
    """
    global _TRENDING_CTX
    if not os.environ.get("GEMINI_API_KEY"):
        print("  no Gemini key — skipping region trend search", flush=True)
        return

    print("  fetching trending topics across regions (US, AU, UK, IN, CA, SG)...", flush=True)
    try:
        briefing = get_daily_briefing(region_codes=["us", "au", "uk", "in", "ca", "sg"])
        if briefing.get("status") == "ok":
            _TRENDING_CTX["region_data"] = briefing.get("regions", [])
            best = briefing.get("recommended_video_topic", {})
            _TRENDING_CTX["best_video_topic"] = best
            _TRENDING_CTX["global_pulse"] = briefing.get("cross_region_trends", "")
            regions_found = len(_TRENDING_CTX["region_data"])
            print(f"  region trends: {regions_found} regions sourced | "
                  f"best: {best.get('topic','')[:60]!r}", flush=True)
        else:
            print(f"  region trend search failed: {briefing.get('error')}", flush=True)
    except Exception as e:
        print(f"  region trend search error: {e}", flush=True)
        # Corrigendum — if get_daily_briefing fails, try multi-region
        try:
            alt = get_multi_region_trends()
            if alt.get("status") == "ok":
                _TRENDING_CTX["region_data"] = alt.get("regions", [])
                best = alt.get("best_video_topic", {})
                _TRENDING_CTX["best_video_topic"] = best
                _TRENDING_CTX["global_pulse"] = alt.get("global_pulse", "")
                print(f"  alt region trends: {len(_TRENDING_CTX['region_data'])} regions",
                      flush=True)
        except Exception as e2:
            print(f"  alt region search also failed: {e2}", flush=True)


def _region_trends_summary():
    """Build a human-readable summary of the cached regional trending context."""
    ctx = _TRENDING_CTX
    lines = []
    best = ctx.get("best_video_topic", {})
    if best and best.get("topic"):
        lines.append(f"BEST VIDEO TOPIC GLOBALLY: \"{best['topic']}\"")
        lines.append(f"  Region: {best.get('region', 'global')} | Reason: {best.get('reason', '')}")
    pulse = ctx.get("global_pulse", "")
    if pulse:
        lines.append(f"GLOBAL PULSE: {pulse}")
    for region in ctx.get("region_data", []):
        rname = region.get("region_name", region.get("region_code", "")).upper()
        top = region.get("top_trending", "")
        ideas = region.get("video_ideas", [])
        if top:
            lines.append(f"[{rname}] Trending: {top}")
        if ideas:
            for idea in ideas[:2]:
                lines.append(f"  Video idea: {idea}")
        briefings = region.get("briefings", [])
        for b in briefings:
            cat = b.get("category", "general")
            hl = b.get("headlines", [])
            if hl:
                lines.append(f"  {cat.upper()}: {' | '.join(hl[:2])}")
    return "\n".join(lines)


def _pick_topic_from_trends():
    """LLM picks ONE specific topic from live trends and researches it with full context.
    
    Returns a dict with the selected topic + full research context, or None.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    region_summary = _region_trends_summary()
    if not region_summary:
        return None

    print("  LLM picking ONE specific topic from live trends...", flush=True)

    prompt = (
        "CRITICAL: Use search-grounding for LIVE data. Only THIS WEEK's news.\n\n"
        f"Today is {datetime.date.today().isoformat()}.\n\n"
        f"Below are LIVE trending topics across USA, Australia, UK, India, Canada, Singapore:\n\n"
        f"{region_summary}\n\n"
        "TASK: Pick EXACTLY ONE topic for a long-form educational YouTube video (8-15 min).\n"
        "Then search the web LIVE for DETAILED information about that ONE topic:\n"
        "- Latest news, developments, key facts\n"
        "- Specific data points, statistics, recent studies\n"
        "- Real examples, names, dates, sources\n"
        "- Why this matters RIGHT NOW\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        "  \"selected_topic\": \"the exact video title (60-80 chars)\",\n"
        "  \"target_region\": \"us/au/uk/in/...\",\n"
        "  \"reason_picked\": \"why THIS topic over all others\",\n"
        "  \"hook\": \"one-sentence hook that opens the video\",\n"
        "  \"topic_context\": {\n"
        "    \"what_happened\": \"2-3 sentences on the specific event/news driving this topic\",\n"
        "    \"why_now\": \"why this is relevant THIS WEEK\",\n"
        "    \"key_facts\": [\"fact 1 with specific numbers/dates\", \"fact 2\", \"fact 3\"],\n"
        "    \"news_headlines\": [\"recent headline 1\", \"recent headline 2\"],\n"
        "    \"sources\": [\"source URL or publication\"]\n"
        "  },\n"
        "  \"video_angle\": \"the specific angle/narrative for this video\"\n"
        "}\n\n"
        "Be decisive. Pick ONE. No markdown. Pure JSON."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 4096,
        },
        "tools": [{"googleSearchRetrieval": {}}],
    }

    for model in GEMINI_MODELS[:3]:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=90,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            sources = body.get("candidates", [{}])[0].get("groundingMetadata", {}).get("groundingChunks", [])
            data = _extract_json(text)
            topic = (data.get("selected_topic") or "").strip()
            if not topic:
                continue
            ctx = data.get("topic_context", {})
            print(f"  LLM picked: {topic!r} | region={data.get('target_region','')} | "
                  f"{len(ctx.get('key_facts',[]))} facts | {len(sources)} sources", flush=True)
            return {
                "topic": topic,
                "voice": "en-US-AriaNeural",
                "privacy": "unlisted",
                "source": f"trending-pick-{data.get('target_region','global')}",
                "row_idx": None,
                "_hook": data.get("hook", ""),
                "_reason": data.get("reason_picked", ""),
                "_region": data.get("target_region", ""),
                "_video_angle": data.get("video_angle", ""),
                "_topic_context": ctx,
            }
        except Exception as e:
            print(f"    Gemini pick model {model} failed: {e}", flush=True)
    return None


def _gemini_trending_eval(candidate_topic):
    """Use Gemini w/ search grounding + regional context to check topic.
    
    Returns (is_trending: bool, suggested_topic: str | None, source: str).
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return False, None, "no-gemini-key"

    region_summary = _region_trends_summary()

    prompt = (
        f"CRITICAL: You MUST use search-grounding to fetch LIVE, REAL-TIME data. "
        f"Do NOT rely on your training data. Only consider information published "
        f"within the LAST 7 DAYS.\n\n"
        f"You are a YouTube trends analyst monitoring the USA, Australia, UK, India, "
        f"Canada, and Singapore markets.\n\n"
        f"A long-form educational channel has this topic in its backlog:\n"
        f"\"{candidate_topic}\"\n\n"
        f"CURRENT REGIONAL TRENDS (LIVE from web search):\n"
        f"{region_summary if region_summary else '(No regional data available)'}\n\n"
        f"Task:\n"
        f"1. Search LIVE — is \"{candidate_topic}\" TRENDING RIGHT NOW (this week) "
        f"in ANY of these regions (USA, Australia, UK, India, Canada, Singapore)?\n"
        f"2. If YES → {{\"trending\": true, \"reason\": \"...which region(s) and why this week\"}}\n"
        f"3. If NO → {{\"trending\": false, \"reason\": \"...why stale this week\", "
        f"\"suggested_topic\": \"...a FRESH trending topic from THIS WEEK's data\", "
        f"\"target_region\": \"us/au/uk/in/...\", "
        f"\"trend_evidence\": \"...LIVE news headline proving it's hot this week\"}}\n\n"
        f"Rules:\n"
        f"- Only consider REAL news/events from THIS WEEK\n"
        f"- Prefer topics already trending across MULTIPLE regions\n"
        f"- Topic must be worthy of an 8-15 minute educational deep dive\n"
        f"- suggested_topic should be a compelling YouTube title (60-80 chars)\n"
        f"- Return ONLY valid JSON, no markdown, no extra text."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 1024,
        },
        "tools": [{"googleSearchRetrieval": {}}],
    }
    for model in GEMINI_MODELS[:3]:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=60,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            sources = body.get("candidates", [{}])[0].get("groundingMetadata", {}).get("groundingChunks", [])
            data = _extract_json(text)
            is_t = data.get("trending", False)
            suggested = data.get("suggested_topic", "").strip() or None
            region_tag = data.get("target_region", "global")
            print(f"  trending eval: {'TRENDING' if is_t else 'STALE'} | region={region_tag} | "
                  f"{data.get('reason','')[:60]} | {len(sources)} sources", flush=True)
            return is_t, suggested, f"gemini-{model}-{region_tag}-eval"
        except Exception as e:
            print(f"    Gemini eval model {model} failed: {e}", flush=True)
    return False, None, "gemini-eval-failed"


def _llm_suggest_trending_topic():
    """Ask Gemini search-grounded to generate a fresh trending topic from regional data."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    region_summary = _region_trends_summary()

    prompt = (
        "CRITICAL: You MUST use search-grounding to fetch LIVE, REAL-TIME data. "
        "Do NOT rely on your training data. Only consider THIS WEEK's news.\n\n"
        "You are a YouTube trends researcher monitoring USA, Australia, UK, India, "
        "Canada, and Singapore markets.\n\n"
        f"CURRENT REGIONAL TRENDS (LIVE):\n"
        f"{region_summary if region_summary else '(search the web live yourself)'}\n\n"
        "Search LIVE for ONE topic that is TRENDING THIS WEEK across multiple countries "
        "and worthy of an 8-15 minute educational deep-dive video on YouTube.\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        "  \"topic\": \"...compelling video title (60-80 chars)\",\n"
        "  \"target_region\": \"us/au/uk/in/...\",\n"
        "  \"reason\": \"...why it's trending THIS WEEK in that region\",\n"
        "  \"trend_evidence\": \"...LIVE news headline or source from this week\",\n"
        "  \"hook\": \"...a 1-sentence hook to open the video\"\n"
        "}\n\n"
        "No markdown. No extra text. Pure JSON."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.5,
            "maxOutputTokens": 1024,
        },
        "tools": [{"googleSearchRetrieval": {}}],
    }
    for model in GEMINI_MODELS[:3]:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=60,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            data = _extract_json(text)
            topic = data.get("topic", "").strip()
            if not topic:
                continue
            sources = body.get("candidates", [{}])[0].get("groundingMetadata", {}).get("groundingChunks", [])
            region = data.get("target_region", "global")
            print(f"  trending-LLM suggested: {topic!r} | region={region} | "
                  f"{len(sources)} sources", flush=True)
            return {"topic": topic, "voice": "en-US-AriaNeural", "privacy": "unlisted",
                    "source": f"trending-llm-{region}", "row_idx": None,
                    "_hook": data.get("hook", ""), "_reason": data.get("reason", ""),
                    "_region": region}
        except Exception as e:
            print(f"    Gemini trending model {model} failed: {e}", flush=True)
    return None


def _get_topic():
    global _TOPIC_CTX
    has_sheet = _sheet_available()

    candidate_item = None
    candidate_source = None

    # --- 1. Try sheet ---
    if has_sheet:
        try:
            candidate_item = _from_sheet_long()
            if candidate_item:
                candidate_source = "google-sheet"
                print(f"Sheet candidate: {candidate_item.get('topic','')!r}", flush=True)
            else:
                print("Sheet reachable: all long rows done", flush=True)
        except Exception as e:
            print(f"Sheet unavailable ({e})", flush=True)
    else:
        print("No sheet credentials", flush=True)

    # --- 2. Try CSV ---
    if not candidate_item and os.path.exists(LONG_CSV):
        try:
            with open(LONG_CSV, newline="", encoding="utf-8-sig") as f:
                rows = [r for r in csv.DictReader(f) if (r.get("topic") or "").strip()]
            undone = filter_undone(rows)
            if undone:
                pick = random.Random(datetime.date.today().isoformat()).choice(undone)
                candidate_item = pick
                candidate_source = "topics_long.csv"
                print(f"CSV candidate: {pick.get('topic','')!r}", flush=True)
            else:
                print("CSV topics all done", flush=True)
        except Exception as e:
            print(f"CSV error ({e})", flush=True)

    # --- 3. Try built-in ---
    if not candidate_item:
        undone_fallback = filter_undone(LONG_FALLBACK)
        if undone_fallback:
            pick = random.Random(datetime.date.today().isoformat()).choice(undone_fallback)
            candidate_item = pick
            candidate_source = "built-in"
            print(f"Built-in candidate: {pick.get('topic','')!r}", flush=True)

    # --- 4. LLM trending evaluation + suggestion from trends ---
    gemini_eval_possible = bool(os.environ.get("GEMINI_API_KEY"))

    if gemini_eval_possible:
        # Fetch live regional trends first
        _fetch_regional_trends()

        # Try to pick a decisive topic from LIVE trends
        picked = _pick_topic_from_trends()
        if picked:
            print(f"  → LLM picked from LIVE trends: {picked.get('topic','')!r}", flush=True)
            _TOPIC_CTX = parse_topic_context(picked, "trending-pick")
            store_context(_TOPIC_CTX)
            return {"row_idx": None, "source": picked.get("source", "trending-pick"), **picked}

        # Trends unavailable — evaluate candidate topic
        if candidate_item:
            topic = candidate_item.get("topic", "").strip()
            if topic:
                is_trending, suggested_topic, eval_source = _gemini_trending_eval(topic)
                if not is_trending and suggested_topic:
                    print(f"  → stale: LLM suggests FRESH topic: {suggested_topic!r}", flush=True)
                    candidate_item = {"topic": suggested_topic,
                                      "voice": candidate_item.get("voice", "en-US-AriaNeural"),
                                      "privacy": candidate_item.get("privacy", "unlisted")}
                    candidate_source = f"{candidate_source}+trending-boost"

    if candidate_item:
        item = {"row_idx": None, "source": candidate_source, **candidate_item}
        _TOPIC_CTX = parse_topic_context(item, candidate_source)
        store_context(_TOPIC_CTX)
        return item

    # --- 5. All static sources exhausted — LLM live generation ---
    if gemini_eval_possible:
        print("All static topics exhausted → asking LLM to generate LIVE trending topic...", flush=True)
        llm_item = _llm_suggest_trending_topic()
        if llm_item:
            _TOPIC_CTX = parse_topic_context(llm_item, "trending-llm-live")
            store_context(_TOPIC_CTX)
            return llm_item

    raise RuntimeError("ALL topic sources exhausted (sheet + CSV + built-in + LLM). "
                       "Add new topics or reset done_topics.json")
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
    "gemini-3-flash-preview",
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
    if total_scenes < 15:
        raise ValueError(f"only {total_scenes} total scenes across chapters (need ≥15 for 5+ min)")
    return {
        "title": str(data.get("title") or topic)[:120],
        "description": str(data.get("description") or ""),
        "tags": [str(t)[:60] for t in (data.get("tags") or [])][:15],
        "hook": str(data.get("hook") or "Watch till the end")[:120],
        "comment": str(data.get("comment") or "What did you think?")[:300],
        "virality_score": max(0.0, min(1.0, float(data.get("virality_score", 0)))),
        "attention_score": max(0.0, min(1.0, float(data.get("attention_score", 0)))),
        "authenticity_score": max(0.0, min(1.0, float(data.get("authenticity_score", 0)))),
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
    best_model = suggest_model(prompt, GROQ_MODELS, provider="groq", reserve_output=8192)
    models_to_try = [best_model] if best_model else GROQ_MODELS
    for model in models_to_try:
        try:
            print(f"    Groq trying {model} (prompt ~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 12288,
                    "temperature": temperature,
                },
                timeout=300,
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
    best_model = suggest_model(prompt, GEMINI_MODELS, provider="gemini", reserve_output=12288)
    models_to_try = [best_model] if best_model else GEMINI_MODELS
    for model in models_to_try:
        try:
            print(f"    Gemini trying {model} (prompt ~{estimate_tokens(prompt)}t)", flush=True)
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": temperature,
                    "maxOutputTokens": 12288,
                },
                "tools": [{"googleSearchRetrieval": {}}],
            }
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            grounding = body.get("candidates", [{}])[0].get("groundingMetadata")
            if grounding:
                sources = grounding.get("groundingChunks", [])
                print(f"      search grounded with {len(sources)} sources", flush=True)
                search_suggestions = grounding.get("groundingSupports", [])
                if search_suggestions:
                    print(f"      grounding supports: {len(search_suggestions)} segments", flush=True)
            return _validate_long(_extract_json(text), topic)
        except requests.exceptions.Timeout:
            last_err = "timeout"
            print(f"    Gemini {model} timed out after 300s — trying next")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status == 429:
                print(f"    Gemini {model} rate limited (429) — trying next")
            elif status == 404:
                print(f"    Gemini {model} not found (404) — trying next")
            else:
                print(f"    Gemini {model} HTTP {status}: {e}")
            last_err = e
        except Exception as e:
            last_err = e
            print(f"    Gemini search model {model} failed: {e}")
    raise RuntimeError(f"all Gemini models failed: {last_err}")


def _openrouter_long(topic, prompt, temperature):
    token = os.environ.get("OPENROUTER_API_KEY")
    if not token:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    last_err = None
    best_model = suggest_model(prompt, OPENROUTER_MODELS, provider="openrouter", reserve_output=8192)
    models_to_try = [best_model] if best_model else OPENROUTER_MODELS
    for model in models_to_try:
        try:
            print(f"    OpenRouter trying {model} (prompt ~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 12288,
                    "temperature": temperature,
                },
                timeout=300,
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
    best_model = suggest_model(prompt, HF_MODELS, provider="huggingface", reserve_output=8192)
    models_to_try = [best_model] if best_model else HF_MODELS
    for model in models_to_try:
        try:
            print(f"    HF trying {model} (prompt ~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 12288,
                    "temperature": temperature,
                },
                timeout=300,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _validate_long(_extract_json(content), topic)
        except Exception as e:
            last_err = e
            print(f"    HF model {model} failed: {e}")
    raise RuntimeError(f"all HF models failed: {last_err}")


def _generate_long_plan(topic, topic_ctx=None):
    import random
    if topic_ctx is None:
        topic_ctx = _TOPIC_CTX
    meta = {}

    # Check if we already have a cached script
    cached = load_cached_script()
    if cached and cached.get("topic") == topic:
        print(f"  using cached script from {cached.get('cached_at','')}", flush=True)
        plan = cached["plan"]
        import jsonschema
        try:
            validated = _validate_long(plan, topic)
            print(f"  cached plan valid: {len(validated['chapters'])} ch, "
                  f"{sum(len(c['scenes']) for c in validated['chapters'])} scenes",
                  flush=True)
            return validated, cached.get("llm_used", "cached"), meta
        except Exception as e:
            print(f"  cached plan invalid ({e}) — regenerating", flush=True)
            clear_cache()

    trending_context = None
    if topic_ctx:
        context_block = build_script_context_block(topic_ctx)
        if context_block:
            trending_context = {"context_block": context_block,
                                "summary": topic_ctx.summary(),
                                "region": topic_ctx.target_region}

    # Primary: Multi-LLM pipeline with reviewer agents
    try:
        plan, llm_chain, models_used = run_full_pipeline(topic, trending_context)
        if plan and plan.get("chapters"):
            total_scenes = sum(len(c.get("scenes", [])) for c in plan["chapters"])
            if total_scenes >= 15:
                print(f"  multi-LLM pipeline: {len(plan['chapters'])} ch, "
                      f"{total_scenes} scenes via {llm_chain}", flush=True)
                cache_script(plan, topic, llm_chain)
                save_run_state("script_generated", {"topic": topic, "llm": llm_chain})
                return plan, llm_chain, plan.get("meta", {})
            print(f"  multi-LLM pipeline: only {total_scenes} scenes (<15), falling back",
                  flush=True)
    except Exception as e:
        print(f"  multi-LLM pipeline failed ({e}), falling back to single-provider", flush=True)

    # Fallback: single-provider chain
    dyn_prompt, meta = build_long_prompt(topic, trending_context=trending_context)
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
            cache_script(plan, topic, name)
            save_run_state("script_generated", {"topic": topic, "llm": name})
            return plan, name, meta
        except Exception as e:
            print(f"  script provider {name} unavailable: {e}", flush=True)
    plan = build_offline_long_script(topic, meta)
    cache_script(plan, topic, "offline-builder")
    save_run_state("script_generated", {"topic": topic, "llm": "offline-builder"})
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
    report = {"providers": {}, "chapters": [], "scenes": []}

    item = _get_topic()
    if item is None:
        return 0
    topic = str(item.get("topic", "")).strip()
    voice_name = str(item.get("voice") or "en-US-AriaNeural").strip()
    privacy = str(item.get("privacy") or "unlisted").strip().lower()
    report["providers"]["topic_source"] = item["source"]
    print(f"Topic [{item['source']}]: {topic!r} | voice={voice_name} | privacy={privacy}",
          flush=True)
    save_run_state("topic_selected", {"topic": topic, "source": item["source"]})

    plan, llm_used, meta = _generate_long_plan(topic, topic_ctx=_TOPIC_CTX)
    report["providers"]["script"] = llm_used
    chapters = plan["chapters"]
    hook = plan["hook"]
    print(f"Title: {plan['title']}\nHook: {hook}\nChapters: {len(chapters)}"
          f"\nTotal scenes: {sum(len(c['scenes']) for c in chapters)}", flush=True)

    v = plan.get("virality_score", 0)
    a = plan.get("attention_score", 0)
    auth = plan.get("authenticity_score", 0)
    if v < 0.65 or a < 0.65 or auth < 0.75:
        print(f"  WARNING: scores (v={v:.2f}, a={a:.2f}, auth={auth:.2f}) "
              f"below threshold", flush=True)

    sheets.write_script_metadata(item, plan)

    all_scenes = []
    for ch in chapters:
        for sc in ch["scenes"]:
            all_scenes.append(sc)

    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
    _VOICE_TIMEOUT = 300
    _VISUAL_TIMEOUT = 300

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

    tagged_scene_words = tag_all_scenes(scene_words)

    try:
        final = editor_build(
            chapters, scene_visuals, scene_audios, tagged_scene_words,
            chapter_durations, hook, "output_long/final.mp4",
            title=plan.get("title", ""),
            description=full_desc,
            tags=plan.get("tags", []),
        )
    except Exception as e:
        print(f"  WARNING: editor_build failed ({e}), retrying without captions", flush=True)
        import traceback
        traceback.print_exc()
        final = editor_build(
            chapters, scene_visuals, scene_audios, [[] for _ in scene_words],
            chapter_durations, hook, "output_long/final.mp4",
            title=plan.get("title", ""),
            description=full_desc,
            tags=plan.get("tags", []),
        )
    dur = probe_duration(final) if final and os.path.exists(final) else 0
    print(f"\nRendered: {final} ({dur:.1f}s)", flush=True)
    save_run_state("video_rendered", {"duration_sec": dur})

    if item.get("source") != "google-sheet":
        mark_done(topic, "rendered")
        print(f"  done-tracker: marked {topic!r} as done", flush=True)

    thumb_path = "output_long/thumbnail.jpg"
    try:
        print("  generating enhanced thumbnail ...", flush=True)
        thumb_ctx = build_thumbnail_context(_TOPIC_CTX) if _TOPIC_CTX else {}
        make_thumbnail(
            title=plan.get("title", ""),
            hook=thumb_ctx.get("hook") or hook,
            video_path=final,
            out_path=thumb_path,
            style="bold_split",
            extra_context=thumb_ctx,
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
    if _TOPIC_CTX:
        report["topic_context"] = _TOPIC_CTX.to_dict()
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
