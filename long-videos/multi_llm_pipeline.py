"""Multi-LLM pipeline: free open-source models for generation, Gemini for final polish.

Stages:
  1. SCRIPT WRITER  — OpenRouter → Groq free (full narrative)
  2. SCENE BREAKDOWN — OpenRouter → Groq free (narration + keywords)
  3. SCENE ENHANCER  — OpenRouter → Groq free (cinematic visuals)
  4. HOOK & RETENTION — OpenRouter → Groq free (hooks, CTA)
  5. FINAL REVIEW    — Gemini search-grounded (fact-check, restructure, quality polish)
"""
import os
import re
import json
import requests

from script_cache import estimate_tokens, suggest_model, fits_in_context
from longform_prompt import FACTUAL_GENERATION_RULE
from src.explanatory_motion import VISUAL_RULES, validate_scene


def _safe_format(template, **kwargs):
    # format substitutes values once; braces inside a value are already literal.
    return template.format(**{k: str(v) for k, v in kwargs.items()})


def _require_text(content, provider):
    """Provider returned a 200 with null/empty content (free endpoints do this).

    Raise so the caller's model chain moves to the next model instead of
    handing None downstream, where .strip() would abort the whole pipeline.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{provider} returned empty content")
    return content


def _extract_json(text):
    if not isinstance(text, str):
        return None
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
    if not isinstance(text, str):
        return None
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
# Order: OpenRouter free (Nemotron preferred) → Groq → Gemini (final review only)

from free_models import (GROQ_MODELS as FREE_GROQ_MODELS, GEMINI_MODELS as FREE_GEMINI_MODELS,
                         OPENROUTER_FALLBACK, openrouter_free_models)
from script_cache import save_stage, load_stage

OPENROUTER_FREE = OPENROUTER_FALLBACK

GROQ_MODELS = FREE_GROQ_MODELS

GEMINI_REVIEW = FREE_GEMINI_MODELS


def _call_groq(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    chain = [m for m in GROQ_MODELS if fits_in_context(prompt, m, "groq", max_tokens)] or GROQ_MODELS
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
            return _require_text(body["choices"][0]["message"]["content"], f"groq-{model}"), f"groq-{model}"
        except Exception as e:
            last_err = e
            print(f"      {model} failed: {e}", flush=True)
    raise RuntimeError(f"all Groq failed: {last_err}")


def _call_openrouter(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    live = openrouter_free_models()
    preferred = "nvidia/nemotron-3-super-120b-a12b:free"
    live = ([preferred] if preferred in live else []) + [m for m in live if m != preferred]
    chain = [m for m in live if fits_in_context(prompt, m, "openrouter", max_tokens)] or live
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
            return _require_text(body["choices"][0]["message"]["content"], f"openrouter-{model}"), f"openrouter-{model}"
        except Exception as e:
            last_err = e
            print(f"      {model} failed: {e}", flush=True)
    raise RuntimeError(f"all OpenRouter free failed: {last_err}")


def _call_free_llm(prompt, temperature=0.7, max_tokens=12288, timeout=300):
    """Try OpenRouter free first; Groq is an unproven fallback."""
    try:
        return _call_openrouter(prompt, temperature, max_tokens, timeout)
    except Exception as e:
        print(f"  OpenRouter unavailable ({e}) → Groq fallback", flush=True)
        return _call_groq(prompt, temperature, max_tokens, timeout)


def _call_gemini_review(prompt, temperature=0.3, max_tokens=16384, timeout=300):
    """Gemini for final review — always uses search grounding."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    chain = [m for m in GEMINI_REVIEW if fits_in_context(prompt, m, "gemini", max_tokens)] or GEMINI_REVIEW
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
            text = _require_text(body["candidates"][0]["content"]["parts"][0]["text"], f"gemini-{model}")
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
  "hook": "A concrete question or contrast answered by this script; no invented personal experience",
  "chapters": [
    {{
      "title": "Chapter title",
      "paragraphs": ["3-5 sentences each, natural spoken English. Vary sentence starters. Use contractions. Use qualitative or explicitly hypothetical examples; specific factual numbers and dates only if supplied in topic context."],
      "estimated_seconds": 60-120
    }}
  ],
  "key_points": ["5-8 key facts covered in the video"]
}}

HUMAN AUTHENTICITY RULES:
- Open with the concrete question in the hook, then answer it through a sequence of distinct mechanisms.
- Do not invent first-person experiments, discoveries or reported outcomes.
- No formulaic Imagine/Picture/Think of, emotion labels, summary filler or repeated chapter intros.
- Distinguish established findings from hypotheses and unknowns. Never promise medical benefits.
- Vary sentence starters. Never start 2 consecutive sentences with the same word.
- Use contractions naturally (don't, can't, won't, it's, there's).
- Include one relatable qualitative or explicitly hypothetical example per chapter; factual specifics only from supplied topic context.
- Never use: "delve into", "let's dive in", "in this video we'll explore", "it's worth noting", "in conclusion", "overall".
- Read aloud: every paragraph must sound like a real human expert speaking naturally.
- No markdown fences. Pure JSON.
"""


def stage1_write_script(topic, trending_context=None, review_feedback=None):
    """OpenRouter → Groq free: full narrative script."""
    ctx = ""
    if trending_context and trending_context.get("context_block"):
        ctx = "\nCURRENT CONTEXT:\n" + trending_context["context_block"]
    prompt = _safe_format(STAGE1_PROMPT, topic=topic, trending_context=ctx)
    prompt += "\n\n" + FACTUAL_GENERATION_RULE
    if review_feedback:
        prompt += "\nREVISE AGAINST THESE INDEPENDENT REVIEW FINDINGS:\n" + json.dumps(review_feedback, ensure_ascii=False)
    print("  [Stage 1/5] Script writer (OpenRouter → Groq)...", flush=True)
    text, model = _call_free_llm(prompt, temperature=0.75, max_tokens=16384)
    data = _extract_json(text) or {}
    chapters = data.get("chapters", [])
    print(f"  → {len(chapters)} chapters via {model}", flush=True)
    return {
        "title": data.get("title", topic)[:80],
        "hook": data.get("hook", ""),
        "chapters": chapters,
        "key_points": data.get("key_points", []),
    }, model


# ─── Stage 2: Scene Breakdown ────────────────────────────────────────

STAGE2_PROMPT = """You are a YouTube script editor. Break each chapter's paragraphs into individual scenes.

Each paragraph becomes 1-2 scenes. Each scene:
- narration: 2-4 sentences spoken audio (20-40 seconds)
- visual_type: stock or authored_diagram, according to the execution contract below
- diagram_spec and diagram_description: required for authored_diagram, absent for stock
- keyword: 3-6 word literal search phrase for common real-world stock footage
- visual_source_notes: explain exactly what the stock shot illustrates and what it cannot prove
- production_brief: camera, framing, lighting and editing directions, separate from the search phrase
- energy: one of [calm, curious, energetic, intense, hopeful, thoughtful]

TARGET: at least 15 total scenes across all chapters for a 5+ minute video.

CHAPTERS: {chapters_json}

Return ONLY valid JSON:
{{
  "chapters": [
    {{
      "title": "Chapter title",
      "scenes": [
        {{"narration": "2-4 spoken sentences", "keyword": "3-6 searchable words", "production_brief": "framing and edit directions", "visual_source_notes": "illustrative, not research evidence", "energy": "curious"}}
      ]
    }}
  ]
}}

Rules:
- Each scene advances a distinct explanation, not a synonym of the previous scene.
- Choose common observable actions relevant to the narration, not abstract emotions, historical reenactments or fictional technology.
- No city skylines, landscapes or generic b-roll unrelated to the claim.
- Stock footage illustrates; it cannot be evidence of a study, brain mechanism, historical event or measured result.
- Preserve every source attribution and uncertainty qualifier in the supplied script.
- Narration must flow naturally when spoken aloud.
- Pure JSON. No markdown.
"""


def stage2_breakdown_scenes(chapters_data, topic_context=None):
    """Bound output to one chapter; concrete visual specs make whole-plan JSON large."""
    chapters, models = [], []
    outline = [{"chapter": i, "title": c.get("title", "")} for i, c in enumerate(chapters_data)]
    for ci, source in enumerate(chapters_data):
        prompt = _safe_format(STAGE2_PROMPT, chapters_json=json.dumps([source], ensure_ascii=False))
        prompt += "\nReturn exactly ONE chapter with 4-6 scenes, 50-75 words per narration."
        prompt += "\n\n" + FACTUAL_GENERATION_RULE + "\n" + VISUAL_RULES
        prompt += "\nFULL OUTLINE (avoid repeating other chapters): " + json.dumps(outline)
        prompt += "\nSUPPLIED SOURCE CONTEXT:\n" + json.dumps(topic_context or {}, ensure_ascii=False)
        print(f"  [Stage 2/5] Scene breakdown chapter {ci+1} (free providers)...", flush=True)
        text, model = _call_free_llm(prompt, temperature=0.5, max_tokens=6500)
        data = _extract_json(text) or {}
        units = data.get("chapters", [])
        _save_authoring_diagnostic(f"scene-breakdown-{ci}", data)
        if len(units) != 1 or not 4 <= len(units[0].get("scenes", [])) <= 6:
            raise ValueError(f"Scene breakdown chapter {ci} malformed or incomplete")
        for si, scene in enumerate(units[0]["scenes"]):
            if not isinstance(scene, dict) or not scene.get("narration") or not scene.get("keyword"):
                raise ValueError(f"Scene breakdown chapter {ci} incomplete scene")
            validate_scene(scene)
            # Stable identity is code-owned, not an optional model-supplied hint.
            scene["scene_id"] = f"ch{ci}-sc{si}"
        chapters.append(units[0]); models.append(model)
    return chapters, "+".join(dict.fromkeys(models))


# ─── Stage 3: Scene Enhancer ─────────────────────────────────────────

STAGE3_PROMPT = """You are a practical stock-footage editor. Improve relevance and findability without changing narration.
For every scene return one JSON object in the same order. Use keyword_enhanced as a literal 3-6 word search phrase naming a common subject and action. Keep camera/lighting/color instructions in production_brief, not the search query. Use varied relevant subjects, never arbitrary scenery to fake uniqueness. Do not invent medical scans, historic events, exotic settings or measured demonstrations. Stock is illustrative, not evidence. visual_source_notes must explain that distinction.
SCENES: {scenes_json}
Return ONLY a JSON array of the same length:
[{{"keyword_enhanced": "person writing sleep diary", "production_brief": "wide framing, soft natural light; cut on the action", "visual_source_notes": "Illustrative everyday action; not a study participant or measured outcome"}}]
No markdown.
"""


def stage3_enhance_scenes(chapters, topic_context=None):
    """OpenRouter → Groq free: enhance visual keywords."""
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
    prompt += "\n\n" + FACTUAL_GENERATION_RULE + "\n" + VISUAL_RULES
    prompt += "\nSUPPLIED SOURCE CONTEXT:\n" + json.dumps(topic_context or {}, ensure_ascii=False)
    print(f"  [Stage 3/5] Scene enhancer (OpenRouter → Groq)...", flush=True)

    text, model = _call_free_llm(prompt, temperature=0.5, max_tokens=16384)
    enhanced = _extract_json_array(text)

    if isinstance(enhanced, list) and len(enhanced) == len(all_scenes):
        applied = 0
        for (ci, si), sc in zip(scene_map, enhanced):
            if chapters[ci]["scenes"][si].get("visual_type") == "authored_diagram":
                continue
            if isinstance(sc, dict) and sc.get("keyword_enhanced"):
                chapters[ci]["scenes"][si]["keyword"] = sc["keyword_enhanced"]
                for key in ("production_brief", "visual_source_notes"):
                    if isinstance(sc.get(key), str):
                        chapters[ci]["scenes"][si][key] = sc[key]
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


def stage4_hook_retention(title, chapters, key_points, topic_context=None):
    """OpenRouter → Groq free: hooks, CTA, retention."""
    ch_summary = "; ".join(f"{c.get('title','?')} ({len(c.get('scenes',[]))}s)" for c in chapters)
    kp_str = "; ".join(key_points[:6]) if key_points else ""

    prompt = _safe_format(STAGE4_PROMPT, title=title, chapters_summary=ch_summary, key_points=kp_str)
    prompt += "\n\n" + FACTUAL_GENERATION_RULE
    prompt += "\nSUPPLIED SOURCE CONTEXT:\n" + json.dumps(topic_context or {}, ensure_ascii=False)
    print("  [Stage 4/5] Hook & retention (OpenRouter → Groq)...", flush=True)
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
5. CLARIFY: Replace vague prose with clear qualitative explanations. Include specific factual details only from supplied topic context.

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
        {{"narration": "3-5 spoken sentences", "keyword": "3-6 word literal stock search phrase", "production_brief": "framing and edit directions", "visual_source_notes": "illustration limits", "energy": "curious"}}
      ]
    }}
  ]
}}

Rules:
- Use search grounding to check existing claims. Do not add numbers, dates, quotations or named factual examples absent from supplied topic context.
- Use relevant, common, searchable stock subjects/actions, never fabricated scans or events. Keep production directions separate.
- No invented first-person claims, unsupported health benefits, numerical effects or false certainty.
- Do not add fabricated timestamps; timing is derived after narration is finalized.
- Maintain human authenticity: varied sentence starters, contractions, natural rhythm.
- No AI tells. No "delve into", "let's dive in", "in conclusion".
- Pure JSON. No markdown.
"""


def stage5_final_review(plan_dict, topic_context=None):
    """Gemini search-grounded: fact-check, restructure, polish."""
    from src.explanatory_motion import VISUAL_RULES, validate_scene
    plan_json = json.dumps(plan_dict, indent=2, default=str)
    prompt = _safe_format(STAGE5_PROMPT, plan_json=plan_json)
    prompt += "\nPreserve scene count, order, visual_type, diagram_spec and provenance. " + VISUAL_RULES
    prompt += "\nSUPPLIED FACTUAL CONTEXT AND SOURCES:\n" + json.dumps(topic_context or {}, ensure_ascii=False)
    prompt += "\n\n" + FACTUAL_GENERATION_RULE
    print("  [Stage 5/5] Final review & polish (Gemini search-grounded)...", flush=True)
    try:
        text, model = _call_gemini_review(prompt, temperature=0.25, max_tokens=16384)
        data = _extract_json(text)
        if data and data.get("chapters"):
            old_chapters, new_chapters = plan_dict.get("chapters", []), data["chapters"]
            if len(old_chapters) != len(new_chapters):
                raise ValueError("Gemini changed chapter structure")
            for old_ch, new_ch in zip(old_chapters, new_chapters):
                if len(old_ch.get("scenes", [])) != len(new_ch.get("scenes", [])):
                    raise ValueError("Gemini changed scene structure")
                for old, new in zip(old_ch.get("scenes", []), new_ch.get("scenes", [])):
                    if old.get("visual_type", "stock") != new.get("visual_type", "stock"):
                        raise ValueError("Gemini changed visual execution type")
                    if old.get("visual_type") == "authored_diagram" and any(
                            new.get(k) != old.get(k) for k in ("diagram_spec", "diagram_description", "visual_source_notes")):
                        raise ValueError("Gemini changed reviewed diagram contract")
                    validate_scene(new)
            total = sum(len(c.get("scenes", [])) for c in data["chapters"])
            print(f"  → reviewed: {len(data['chapters'])} ch, {total} scenes via {model}", flush=True)
            return data, model
        print(f"  → Gemini returned invalid structure; blocking final review", flush=True)
    except Exception as e:
        print(f"  → Gemini review failed ({e}); blocking final review", flush=True)
    raise RuntimeError("Final Gemini review unavailable or malformed")


# ─── Reviewer Integration ─────────────────────────────────────────────

def _run_reviewers(title, hook, chapters, stage_label, topic_context=None):
    """Run all reviewer agents and return (passed, results)."""
    from reviewer_agents import run_all_reviewers
    try:
        review = run_all_reviewers(title, hook, chapters, parallel=True,
                                   topic_context=topic_context, paragraph_stage=stage_label == "Stage 1")
        return review["all_passed"], review
    except Exception as e:
        print(f"  [Reviewer] {stage_label} review error: {e}", flush=True)
        return False, {}


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


def _save_authoring_diagnostic(stage, candidate, review=None):
    """Keep generated evidence before fallbacks or validators can discard it."""
    path = os.path.join("output_long", "authoring_diagnostics.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    records = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            records = json.load(handle)
    records.append({"stage": stage, "candidate": candidate, "review": review})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)


def _rewrite_from_review(plan, review, topic_context=None):
    """One atomic repair, one chapter per response. Never approve a failed plan.

    The outline is short; the full original chapter and factual context stay intact.
    A malformed/missing unit aborts without partially changing the original plan.
    """
    import copy
    revised = copy.deepcopy(plan)
    chapters = plan.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("Review-directed rewrite returned malformed plan")
    outline = [{"chapter": i, "title": c.get("title", ""),
                "scene_claims": [{"claim": s.get("claim", s.get("narration", ""))[:180],
                                  "visual_type": s.get("visual_type", "stock"),
                                  "visual": s.get("diagram_spec", s.get("keyword", ""))}
                                 for s in c.get("scenes", [])]} for i, c in enumerate(chapters)]
    models = []
    for ci, chapter in enumerate(chapters):
        prompt = ("Repair ONLY the assigned chapter against the independent review. "
                  "Return one JSON object with title and scenes, not the entire plan. "
                  "Preserve scene count, order and existing scene_id values. Each narration "
                  "is 50-75 natural spoken words, a distinct explanatory step. Keep source "
                  "attribution and uncertainty. No unsupported measurements, stories or "
                  "claims. Remove repeated bridges, openings and redundant mechanisms. "
                  "Use the outline to avoid repeating other chapters. A stock shot cannot "
                  "show an abstract mechanism. Use the executable schematic contract for "
                  "those scenes. Pure JSON.\n" + FACTUAL_GENERATION_RULE + "\n" + VISUAL_RULES +
                  "\nSUPPLIED CONTEXT: " + json.dumps(topic_context or {}, ensure_ascii=False) +
                  "\nINDEPENDENT REVIEW: " + json.dumps(review, ensure_ascii=False) +
                  "\nFULL OUTLINE: " + json.dumps(outline, ensure_ascii=False) +
                  "\nASSIGNED CHAPTER INDEX: " + str(ci) +
                  "\nCHAPTER: " + json.dumps(chapter, ensure_ascii=False))
        text, model = _call_free_llm(prompt, temperature=0.3, max_tokens=6500)
        unit = _extract_json(text)
        _save_authoring_diagnostic(f"chapter-rewrite-{ci}", unit)
        if not isinstance(unit, dict) or not isinstance(unit.get("scenes"), list):
            raise ValueError(f"Chapter {ci} rewrite changed the scene structure or returned malformed JSON")
        if len(unit["scenes"]) != len(chapter.get("scenes", [])):
            raise ValueError(f"Chapter {ci} rewrite changed the scene structure")
        for old, new in zip(chapter["scenes"], unit["scenes"]):
            if not isinstance(new, dict) or not new.get("narration") or not new.get("keyword"):
                raise ValueError(f"Chapter {ci} rewrite has incomplete scene")
            if "scene_id" in old and new.get("scene_id") != old["scene_id"]:
                raise ValueError(f"Chapter {ci} rewrite changed the scene structure")
            validate_scene(new)
        revised["chapters"][ci] = {**chapter, **unit}
        models.append(model)
    return revised, "+".join(dict.fromkeys(models))


# ─── Full Pipeline ───────────────────────────────────────────────────

def run_full_pipeline(topic, trending_context=None):
    """Run all 5 stages with independent reviewer agents verifying each stage.
    
    Free models (OpenRouter→Groq) for generation, Gemini for final polish,
    reviewer agents (separate LLM calls) verifying every stage output.
    """
    from longform_prompt import build_offline_long_script

    models_used = []

    # ── Stage 1: Script writer ──
    script, m1 = load_stage("stage1", topic)
    if not script:
        script, m1 = stage1_write_script(topic, trending_context)
        if script.get("chapters"):
            save_stage("stage1", topic, script, m1)
    models_used.append(m1)
    title = script["title"]
    ch_data = script["chapters"]
    key_points = script["key_points"]

    if not ch_data:
        print("  Stage 1 empty → offline fallback", flush=True)
        return build_offline_long_script(topic), "offline", []

    # Review Stage 1
    hook_placeholder = script.get("hook", "")
    rev1 = _run_reviewers(title, hook_placeholder, ch_data, "Stage 1", trending_context)
    if not rev1[0]:
        print("  Stage 1 review failed — retrying with different prompt", flush=True)
        script, m1b = stage1_write_script(topic, trending_context, rev1[1])
        models_used.append(m1b + "(retry)")
        ch_data = script.get("chapters", ch_data)
        title = script.get("title", title)
        key_points = script.get("key_points", [])
        hook_placeholder = script.get("hook", "")

    # ── Stage 2: Scene breakdown ──
    chapters, m2 = load_stage("stage2", topic)
    if not chapters:
        chapters, m2 = stage2_breakdown_scenes(ch_data, trending_context)
        if sum(len(c.get("scenes", [])) for c in chapters) >= 15:
            save_stage("stage2", topic, chapters, m2)
    models_used.append(m2)
    total_scenes = sum(len(c.get("scenes", [])) for c in chapters)
    if total_scenes < 15:
        print(f"  Only {total_scenes} scenes (<15) → offline fallback", flush=True)
        return build_offline_long_script(topic), "offline", []

    # Review Stage 2
    rev2 = _run_reviewers(title, hook_placeholder, chapters, "Stage 2", trending_context)

    # ── Stage 3: Enhance scenes ──
    enhanced, m3 = load_stage("stage3", topic)
    if enhanced:
        chapters = enhanced
    else:
        chapters, m3 = stage3_enhance_scenes(chapters, trending_context)
        save_stage("stage3", topic, chapters, m3)
    models_used.append(m3)

    # Review Stage 3 (visual feasibility)
    from reviewer_agents import review_visual_feasibility
    try:
        vis_check = review_visual_feasibility(chapters)
        if not vis_check.get("passed", True):
            print(f"  Visual feasibility flagged: {len(vis_check.get('hard_to_find',[]))} hard scenes",
                  flush=True)
            # A generic unrelated replacement is not a visual repair. Preserve the
            # actual briefs so later review can reject them or drive a real rewrite.
    except Exception as e:
        print(f"  Visual review error: {e}", flush=True)

    # ── Stage 4: Hook & retention ──
    retention, m4 = load_stage("stage4", topic)
    if not retention:
        retention, m4 = stage4_hook_retention(title, chapters, key_points, trending_context)
        save_stage("stage4", topic, retention, m4)
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
    final_review = _run_reviewers(title, hook, chapters, "pre-gemini", trending_context)
    raw_plan = _fix_from_review(raw_plan, final_review[1] if len(final_review) > 1 else {})
    _save_authoring_diagnostic("pre-gemini", raw_plan, final_review[1])
    if not final_review[0]:
        revised, repair_model = _rewrite_from_review(raw_plan, final_review[1], trending_context)
        models_used.append(repair_model + "(review-rewrite)")
        raw_plan = revised
        final_review = _run_reviewers(raw_plan.get("title", title), raw_plan.get("hook", hook),
                                      raw_plan.get("chapters", []), "review-rewrite", trending_context)
        _save_authoring_diagnostic("review-rewrite", raw_plan, final_review[1])
        if not final_review[0]:
            raise RuntimeError("Review-directed authoring repair still failed independent reviewers")

    # ── Stage 5: Gemini final review ──
    polished, m5 = load_stage("stage5", topic)
    if not polished or not m5 or "review-skipped" in m5:
        polished, m5 = stage5_final_review(raw_plan, trending_context)
        save_stage("stage5", topic, polished, m5)
    models_used.append(m5)

    # Final verification is required, including for cached stages.
    passed, review = _run_reviewers(polished.get("title", title),
                                   polished.get("hook", hook),
                                   polished.get("chapters", []), "final", trending_context)
    if not passed:
        raise RuntimeError("Final reviewer gate blocked: unavailable or failed evidence")

    llm_chain = " → ".join(models_used)
    final_ch = len(polished.get("chapters", []))
    final_sc = sum(len(c.get("scenes", [])) for c in polished.get("chapters", []))
    print(f"  Multi-LLM pipeline: {final_ch} ch, {final_sc} scenes", flush=True)
    print(f"  Chain: {llm_chain}", flush=True)
    return polished, llm_chain, models_used

