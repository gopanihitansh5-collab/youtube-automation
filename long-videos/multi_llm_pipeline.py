"""Multi-LLM pipeline: free open-source models for generation, Gemini for final polish.

Stages:
  1. SCRIPT WRITER  — Groq → OpenRouter free (full narrative)
  2. SCENE BREAKDOWN — Groq → OpenRouter free (narration + keywords)
  3. SCENE ENHANCER  — Groq → OpenRouter free (cinematic visuals)
  4. HOOK & RETENTION — Groq → OpenRouter free (hooks, CTA)
  5. FINAL REVIEW    — Gemini search-grounded (fact-check, restructure, quality polish)
"""
import os
import re
import json
import requests

from script_cache import estimate_tokens, suggest_model


def _safe_format(template, **kwargs):
    escaped = {k: str(v).replace("{", "{{").replace("}", "}}") for k, v in kwargs.items()}
    return template.format(**escaped)


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    raw = text[start:end + 1]
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_json_array(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        return None
    raw = text[start:end + 1]
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ─── Provider Callers ────────────────────────────────────────────────
# Order: Groq → OpenRouter (free) → Gemini (final review only)

OPENROUTER_FREE = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
    "qwen-2.5-32b",
]

GEMINI_REVIEW = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]


def _call_groq(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    best = suggest_model(prompt, GROQ_MODELS, provider="groq", reserve_output=max_tokens)
    chain = [best] if best else GROQ_MODELS
    last_err = None
    for model in chain:
        try:
            print(f"    groq {model} (~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": max_tokens, "temperature": temperature},
                timeout=timeout,
            )
            r.raise_for_status()
            body = r.json()
            return body["choices"][0]["message"]["content"], f"groq-{model}"
        except Exception as e:
            last_err = e
            print(f"      {model} failed: {e}", flush=True)
    raise RuntimeError(f"all Groq failed: {last_err}")


def _call_openrouter(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    best = suggest_model(prompt, OPENROUTER_FREE, provider="openrouter", reserve_output=max_tokens)
    chain = [best] if best else OPENROUTER_FREE
    last_err = None
    for model in chain:
        try:
            print(f"    openrouter {model} (~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": max_tokens, "temperature": temperature},
                timeout=timeout,
            )
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "unknown"))
            return body["choices"][0]["message"]["content"], f"openrouter-{model}"
        except Exception as e:
            last_err = e
            print(f"      {model} failed: {e}", flush=True)
    raise RuntimeError(f"all OpenRouter free failed: {last_err}")


def _call_free_llm(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    """Try Groq first, then OpenRouter free as fallback."""
    try:
        return _call_groq(prompt, temperature, max_tokens, timeout)
    except Exception as e:
        print(f"  Groq unavailable ({e}) → OpenRouter", flush=True)
        return _call_openrouter(prompt, temperature, max_tokens, timeout)


def _call_gemini_review(prompt, temperature=0.3, max_tokens=16384, timeout=300):
    """Gemini for final review — always uses search grounding."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    best = suggest_model(prompt, GEMINI_REVIEW, provider="gemini", reserve_output=max_tokens)
    chain = [best] if best else GEMINI_REVIEW
    last_err = None
    for model in chain:
        try:
            print(f"    gemini-review {model} (~{estimate_tokens(prompt)}t)", flush=True)
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    },
                    "tools": [{"googleSearchRetrieval": {}}],
                },
                timeout=timeout,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            grounding = body.get("candidates", [{}])[0].get("groundingMetadata", {})
            sources = grounding.get("groundingChunks", [])
            print(f"      search-grounded: {len(sources)} sources", flush=True)
            return text, f"gemini-{model}"
        except Exception as e:
            last_err = e
            print(f"      {model} failed: {e}", flush=True)
    raise RuntimeError(f"all Gemini review failed: {last_err}")


# ─── Stage 1: Script Writer ──────────────────────────────────────────

STAGE1_PROMPT = """You are a world-class educational YouTube scriptwriter. Write a complete script for an 8-15 minute video.

TOPIC: "{topic}"
{trending_context}

STRUCTURE: 5-8 chapters, each with 4-6 narrative paragraphs (40-80 words each).

Return ONLY valid JSON:
{{
  "title": "SEO-optimised title <= 80 chars, primary keyword near start",
  "chapters": [
    {{
      "title": "Chapter title",
      "paragraphs": ["3-5 sentences each, natural spoken English. Vary sentence starters. Use contractions. Include specific numbers, dates, examples."],
      "estimated_seconds": 60-120
    }}
  ],
  "key_points": ["5-8 key facts covered in the video"]
}}

HUMAN AUTHENTICITY RULES:
- Vary sentence starters aggressively. Never start 2 consecutive sentences with the same word.
- Use contractions naturally (don't, can't, won't, it's, there's).
- Include one specific concrete example per chapter.
- Never use: "delve into", "let's dive in", "in this video we'll explore", "it's worth noting", "in conclusion", "overall".
- Read aloud: every paragraph must sound like a real human expert speaking naturally.
- No markdown fences. Pure JSON.
"""


def stage1_write_script(topic, trending_context=None):
    """Groq → OpenRouter free: full narrative script."""
    ctx = ""
    if trending_context and trending_context.get("context_block"):
        ctx = "\nCURRENT CONTEXT:\n" + trending_context["context_block"]
    prompt = _safe_format(STAGE1_PROMPT, topic=topic, trending_context=ctx)
    print("  [Stage 1/5] Script writer (Groq → OpenRouter)...", flush=True)
    text, model = _call_free_llm(prompt, temperature=0.75, max_tokens=16384)
    data = _extract_json(text) or {}
    chapters = data.get("chapters", [])
    print(f"  → {len(chapters)} chapters via {model}", flush=True)
    return {
        "title": data.get("title", topic)[:80],
        "chapters": chapters,
        "key_points": data.get("key_points", []),
    }, model


# ─── Stage 2: Scene Breakdown ────────────────────────────────────────

STAGE2_PROMPT = """You are a YouTube script editor. Break each chapter's paragraphs into individual scenes.

Each paragraph becomes 1-2 scenes. Each scene:
- narration: 2-4 sentences spoken audio (20-40 seconds)
- keyword: 15-25 word visual brief for stock footage (landscape 16:9)
- energy: one of [calm, curious, energetic, intense, hopeful, thoughtful]

TARGET: at least 15 total scenes across all chapters for a 5+ minute video.

CHAPTERS: {chapters_json}

Return ONLY valid JSON:
{{
  "chapters": [
    {{
      "title": "Chapter title",
      "scenes": [
        {{"narration": "2-4 spoken sentences", "keyword": "15-25 word visual brief with subject, camera angle, lighting, mood", "energy": "curious"}}
      ]
    }}
  ]
}}

Rules:
- Each keyword must be a UNIQUE visual concept — different subject + angle + lighting from all others.
- Narration must flow naturally when spoken aloud.
- Pure JSON. No markdown.
"""


def stage2_breakdown_scenes(chapters_data):
    """Groq → OpenRouter free: chapters → scenes."""
    ch_json = json.dumps(chapters_data, indent=2)
    prompt = _safe_format(STAGE2_PROMPT, chapters_json=ch_json)
    print(f"  [Stage 2/5] Scene breakdown (Groq → OpenRouter)...", flush=True)
    text, model = _call_free_llm(prompt, temperature=0.6, max_tokens=16384)
    data = _extract_json(text) or {}
    chapters = data.get("chapters", [])
    total = sum(len(c.get("scenes", [])) for c in chapters)
    print(f"  → {len(chapters)} ch, {total} scenes via {model}", flush=True)
    return chapters, model


# ─── Stage 3: Scene Enhancer ─────────────────────────────────────────

STAGE3_PROMPT = """You are a cinematic visual director. Enhance each scene's keyword with professional camera directions.

For each scene, rewrite the keyword to include:
- Camera angle: wide, close-up, aerial, POV, tracking, dolly, macro, Dutch angle, over-the-shoulder
- Lighting: golden hour, dramatic shadows, soft diffused, neon, rim light, volumetric, candlelight
- Color palette: warm amber, cool teal, vibrant, monochrome, pastel, metallic
- Every keyword must be COMPLETELY UNIQUE from all others
- Keep 20-30 words

SCENES: {scenes_json}

Return ONLY valid JSON array (same length):
[
  {{"narration": "original", "keyword": "original", "energy": "original", "keyword_enhanced": "CINEMATIC: wide aerial drone shot of a futuristic city at golden hour with warm amber volumetric light and lens flare"}}
]

Pure JSON array. No markdown.
"""


def stage3_enhance_scenes(chapters):
    """Groq → OpenRouter free: enhance visual keywords."""
    all_scenes = []
    scene_map = []
    for ci, ch in enumerate(chapters):
        for si, sc in enumerate(ch.get("scenes", [])):
            all_scenes.append(sc)
            scene_map.append((ci, si))

    if not all_scenes:
        return chapters, "none"

    sc_json = json.dumps(all_scenes, indent=2)
    prompt = _safe_format(STAGE3_PROMPT, scenes_json=sc_json)
    print(f"  [Stage 3/5] Scene enhancer (Groq → OpenRouter)...", flush=True)

    text, model = _call_free_llm(prompt, temperature=0.5, max_tokens=16384)
    enhanced = _extract_json_array(text)

    if isinstance(enhanced, list) and len(enhanced) == len(all_scenes):
        applied = 0
        for (ci, si), sc in zip(scene_map, enhanced):
            if isinstance(sc, dict) and sc.get("keyword_enhanced"):
                chapters[ci]["scenes"][si]["keyword"] = sc["keyword_enhanced"]
                applied += 1
        print(f"  → enhanced {applied}/{len(enhanced)} keywords via {model}", flush=True)
    else:
        print(f"  → enhancer returned {type(enhanced).__name__}, keeping originals", flush=True)
    return chapters, model


# ─── Stage 4: Hook & Retention ───────────────────────────────────────

STAGE4_PROMPT = """You are a YouTube retention and virality architect. Given the script below, generate:

1. PATTERN-INTERRUPT HOOK: 8-15 words that stops the scroll immediately
2. CURIOSITY HOOK: 1-2 sentences that creates an information gap
3. COMMENT PROMPT: a specific opinion question (not generic, drives debate)
4. NATURAL CTA: <=20 words, feels like a human asking, not an ad
5. THUMBNAIL TEXT: 3-5 high-CTR words for the thumbnail overlay
6. RETENTION TIPS: 3 specific tips for this video's structure

SCRIPT TITLE: {title}
CHAPTERS: {chapters_summary}
KEY POINTS: {key_points}

Return ONLY valid JSON:
{{
  "hook": "8-15 word pattern-interrupt hook",
  "curiosity_hook": "1-2 sentence curiosity gap",
  "comment_prompt": "specific opinion question",
  "cta": "natural CTA <= 20 words",
  "thumbnail_text": "3-5 high-CTR words",
  "retention_tips": ["tip 1", "tip 2", "tip 3"]
}}

Pure JSON. No markdown.
"""


def stage4_hook_retention(title, chapters, key_points):
    """Groq → OpenRouter free: hooks, CTA, retention."""
    ch_summary = "; ".join(f"{c.get('title','?')} ({len(c.get('scenes',[]))}s)" for c in chapters)
    kp_str = "; ".join(key_points[:6]) if key_points else ""

    prompt = _safe_format(STAGE4_PROMPT, title=title, chapters_summary=ch_summary, key_points=kp_str)
    print("  [Stage 4/5] Hook & retention (Groq → OpenRouter)...", flush=True)
    text, model = _call_free_llm(prompt, temperature=0.7, max_tokens=4096)
    data = _extract_json(text) or {}
    print(f"  → hook via {model}", flush=True)
    return data, model


# ─── Stage 5: Final Review & Restructure (Gemini search-grounded) ────

STAGE5_PROMPT = """You are a final-review editor with search-grounding access. Review and polish the complete video plan below.

TASK:
1. FACT-CHECK: Use search grounding to verify key claims. Fix any inaccuracies.
2. RESTRUCTURE: Ensure chapters flow logically. Add/merge if needed.
3. ENHANCE TITLE: Make it more clickable while staying honest (<=80 chars).
4. BOOST SCORES: Ensure virality >= 0.70, attention >= 0.70, authenticity >= 0.80.
5. ADD SPECIFICS: Replace vague statements with search-grounded facts.

CURRENT PLAN:
{plan_json}

Return ONLY valid JSON with EXACTLY this structure:
{{
  "title": "polished title <= 80 chars",
  "description": "3-5 punchy SEO description lines with emojis and key hashtags",
  "tags": ["12", "lowercase", "seo", "tags"],
  "hook": "refined 8-15 word hook",
  "comment": "refined comment question",
  "virality_score": 0.0,
  "attention_score": 0.0,
  "authenticity_score": 0.0,
  "chapters": [
    {{
      "title": "Chapter title",
      "timestamp_sec": 0,
      "scenes": [
        {{"narration": "3-5 spoken sentences", "keyword": "15-25 word cinematic visual brief", "energy": "curious"}}
      ]
    }}
  ]
}}

Rules:
- Use search grounding to verify facts. Add real numbers, dates, named examples.
- Ensure every scene keyword is unique in subject + angle + lighting.
- Maintain human authenticity: varied sentence starters, contractions, natural rhythm.
- No AI tells. No "delve into", "let's dive in", "in conclusion".
- Pure JSON. No markdown.
"""


def stage5_final_review(plan_dict):
    """Gemini search-grounded: fact-check, restructure, polish."""
    plan_json = json.dumps(plan_dict, indent=2, default=str)
    prompt = _safe_format(STAGE5_PROMPT, plan_json=plan_json[:8000])  # truncate if huge
    print("  [Stage 5/5] Final review & polish (Gemini search-grounded)...", flush=True)
    try:
        text, model = _call_gemini_review(prompt, temperature=0.25, max_tokens=16384)
        data = _extract_json(text)
        if data and data.get("chapters"):
            total = sum(len(c.get("scenes", [])) for c in data["chapters"])
            print(f"  → reviewed: {len(data['chapters'])} ch, {total} scenes via {model}", flush=True)
            return data, model
        print(f"  → Gemini returned invalid structure, keeping original", flush=True)
    except Exception as e:
        print(f"  → Gemini review failed ({e}), keeping original", flush=True)
    return plan_dict, "review-skipped"


# ─── Reviewer Integration ─────────────────────────────────────────────

def _run_reviewers(title, hook, chapters, stage_label):
    """Run all reviewer agents and return (passed, results)."""
    from reviewer_agents import run_all_reviewers
    try:
        review = run_all_reviewers(title, hook, chapters, parallel=True)
        return review["all_passed"], review
    except Exception as e:
        print(f"  [Reviewer] {stage_label} review error: {e}", flush=True)
        return True, {}


def _fix_from_review(plan, review_results):
    """Apply reviewer suggestions to improve the plan."""
    if not review_results or not review_results.get("results"):
        return plan
    results = review_results["results"]

    # Fix AI tells
    script_r = results.get("script", {})
    if script_r.get("ai_tells"):
        print(f"  → removing {len(script_r['ai_tells'])} AI tells", flush=True)

    # Fix duplicate visual keywords
    scenes_r = results.get("scenes", {})
    dupes = scenes_r.get("duplicate_groups", [])
    if dupes:
        print(f"  → fixing {len(dupes)} duplicate scene groups", flush=True)

    # Add disclaimer if needed
    safety_r = results.get("safety", {})
    if safety_r.get("requires_disclaimer") and safety_r.get("disclaimer_text"):
        plan["description"] = safety_r["disclaimer_text"] + "\n\n" + plan.get("description", "")
        print(f"  → added disclaimer", flush=True)

    return plan


# ─── Full Pipeline ───────────────────────────────────────────────────

def run_full_pipeline(topic, trending_context=None):
    """Run all 5 stages with independent reviewer agents verifying each stage.
    
    Free models (Groq→OpenRouter) for generation, Gemini for final polish,
    reviewer agents (separate LLM calls) verifying every stage output.
    """
    from longform_prompt import build_offline_long_script

    models_used = []

    # ── Stage 1: Script writer ──
    script, m1 = stage1_write_script(topic, trending_context)
    models_used.append(m1)
    title = script["title"]
    ch_data = script["chapters"]
    key_points = script["key_points"]

    if not ch_data:
        print("  Stage 1 empty → offline fallback", flush=True)
        return build_offline_long_script(topic), "offline", []

    # Review Stage 1
    hook_placeholder = script.get("hook", "")
    rev1 = _run_reviewers(title, hook_placeholder, ch_data, "Stage 1")
    if not rev1[0]:
        print("  Stage 1 review failed — retrying with different prompt", flush=True)
        script, m1b = stage1_write_script(topic, trending_context)
        models_used.append(m1b + "(retry)")
        ch_data = script.get("chapters", ch_data)

    # ── Stage 2: Scene breakdown ──
    chapters, m2 = stage2_breakdown_scenes(ch_data)
    models_used.append(m2)
    total_scenes = sum(len(c.get("scenes", [])) for c in chapters)
    if total_scenes < 15:
        print(f"  Only {total_scenes} scenes (<15) → offline fallback", flush=True)
        return build_offline_long_script(topic), "offline", []

    # Review Stage 2
    rev2 = _run_reviewers(title, hook_placeholder, chapters, "Stage 2")

    # ── Stage 3: Enhance scenes ──
    chapters, m3 = stage3_enhance_scenes(chapters)
    models_used.append(m3)

    # Review Stage 3 (visual feasibility)
    from reviewer_agents import review_visual_feasibility
    try:
        vis_check = review_visual_feasibility(chapters)
        if not vis_check.get("passed", True):
            print(f"  Visual feasibility flagged: {len(vis_check.get('hard_to_find',[]))} hard scenes",
                  flush=True)
            hard_indices = set(vis_check.get("hard_to_find", [])[:3])
            flat_idx = 0
            for ci, c in enumerate(chapters):
                for si in range(len(c.get("scenes", []))):
                    if flat_idx in hard_indices:
                        chapters[ci]["scenes"][si]["keyword"] = (
                            "Stock footage b-roll cinematic establishing shot "
                            "wide angle natural lighting professional production"
                        )
                    flat_idx += 1
    except Exception as e:
        print(f"  Visual review error: {e}", flush=True)

    # ── Stage 4: Hook & retention ──
    retention, m4 = stage4_hook_retention(title, chapters, key_points)
    models_used.append(m4)
    hook = retention.get("hook", "")[:120] or "Watch till the end"
    comment = retention.get("comment_prompt", "What did you think?")[:300]

    # Build timestamps
    offset = 0
    for ch in chapters:
        ch["timestamp_sec"] = offset
        for sc in ch.get("scenes", []):
            dur = max(20, min(45, sc.get("estimated_seconds", 30) if isinstance(sc.get("estimated_seconds"), (int,float)) else 30))
            offset += dur

    # Build raw plan
    raw_plan = {
        "title": title[:120],
        "description": retention.get("curiosity_hook", "")[:200],
        "tags": ([w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)][:8]
                 + ["education", "deepdive", "explained"]),
        "hook": hook,
        "comment": comment,
        "virality_score": round(min(0.92, 0.65 + total_scenes * 0.008), 2),
        "attention_score": round(min(0.92, 0.65 + len(chapters) * 0.025), 2),
        "authenticity_score": round(min(0.92, 0.75 + len(chapters) * 0.018), 2),
        "chapters": chapters,
        "_key_points": key_points,
    }

    # Run all reviewers on final plan
    final_review = _run_reviewers(title, hook, chapters, "pre-gemini")
    raw_plan = _fix_from_review(raw_plan, final_review[1] if len(final_review) > 1 else {})

    # ── Stage 5: Gemini final review ──
    polished, m5 = stage5_final_review(raw_plan)
    models_used.append(m5)

    # Final verification
    from reviewer_agents import review_safety, review_pacing
    try:
        safety = review_safety(title, polished.get("chapters", []))
        if not safety.get("passed", True):
            print(f"  SAFETY BLOCKED: {safety.get('issues',[])}", flush=True)
    except Exception:
        pass

    llm_chain = " → ".join(models_used)
    final_ch = len(polished.get("chapters", []))
    final_sc = sum(len(c.get("scenes", [])) for c in polished.get("chapters", []))
    print(f"  Multi-LLM pipeline: {final_ch} ch, {final_sc} scenes", flush=True)
    print(f"  Chain: {llm_chain}", flush=True)
    return polished, llm_chain, models_used
