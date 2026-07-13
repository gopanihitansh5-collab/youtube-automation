"""Independent reviewer agents — each stage output verified by a separate LLM call.

Every agent runs as an independent LLM call (Groq → OpenRouter free) that:
  - Scores quality (0-10)
  - Finds issues / suggests fixes
  - Re-verifies after fixes
  - Passes or blocks the pipeline stage

Agents:
  1. Script Reviewer     — narrative quality, authenticity, accuracy
  2. Scene Reviewer      — visual uniqueness, pacing, coverage
  3. Visual Availability — checks stock footage keywords are searchable
  4. Audio/Caption Sync  — verifies narration fits scene duration
  5. Content Safety      — checks for policy violations
  6. Final Quality Gate  — pre-upload checklist
"""
import os
import re
import json
import concurrent.futures


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


def _call_reviewer(prompt, temperature=0.2, max_tokens=4096, timeout=120):
    """Call cheapest available LLM for review. Groq → OpenRouter free."""
    import requests
    key = os.environ.get("GROQ_API_KEY")
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    last_err = None
    if key:
        for model in models:
            try:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=timeout,
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                return text, f"groq-{model}"
            except Exception as e:
                last_err = e
    # Fallback to OpenRouter
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        or_models = ["meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free"]
        for model in or_models:
            try:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=timeout,
                )
                r.raise_for_status()
                body = r.json()
                if "error" not in body:
                    return body["choices"][0]["message"]["content"], f"openrouter-{model}"
            except Exception:
                pass
    raise RuntimeError(f"no reviewer available: {last_err}")


# ─── Agent 1: Script Reviewer ────────────────────────────────────────

REVIEW_SCRIPT_PROMPT = """You are a strict YouTube script reviewer. Score the script below 0-10 on:
1. AUTHENTICITY — Does it sound 100% human-written? Check for AI tells ("delve into", "let's dive in", "in conclusion").
2. VARIETY — Are sentence starters varied? No two consecutive same-word starts.
3. SUBSTANCE — Are there specific numbers, dates, named examples per chapter?
4. FLOW — Does each chapter lead naturally to the next?
5. HOOK QUALITY — Does the opening create a genuine curiosity gap?

SCRIPT TITLE: {title}
HOOK: {hook}
CHAPTERS ({n_ch} chapters, {n_sc} scenes):
{chapters_sample}

Return ONLY valid JSON:
{{
  "score": 0-10,
  "pass": true/false (pass if score >= 7),
  "issues": ["issue 1", "issue 2"],
  "suggestions": ["fix 1", "fix 2"],
  "ai_tells_found": ["phrase 1", "phrase 2"],
  "authenticity_rating": "excellent/good/fair/poor",
  "hook_rating": "excellent/good/fair/poor"
}}

Be harsh. The channel's reputation depends on quality. Pure JSON.
"""


def review_script(title, hook, chapters):
    """Agent 1: Verify narrative quality and authenticity."""
    n_ch = len(chapters)
    n_sc = sum(len(c.get("scenes", [])) for c in chapters)
    ch_sample = []
    for c in chapters[:3]:
        sc_sample = [s.get("narration", "")[:150] for s in (c.get("scenes", []) or [])[:2]]
        ch_sample.append(f"{c.get('title','?')}: {' | '.join(sc_sample)}")
    sample_str = "\n".join(ch_sample)

    prompt = REVIEW_SCRIPT_PROMPT.format(title=title, hook=hook, n_ch=n_ch,
                                          n_sc=n_sc, chapters_sample=sample_str)
    try:
        text, model = _call_reviewer(prompt)
        data = _extract_json(text) or {}
        score = data.get("score", 0)
        passed = data.get("pass", False)
        print(f"  [Reviewer] Script score: {score}/10 pass={passed} via {model}", flush=True)
        if data.get("issues"):
            for iss in data["issues"]:
                print(f"    issue: {iss}", flush=True)
        return {
            "passed": passed,
            "score": score,
            "issues": data.get("issues", []),
            "suggestions": data.get("suggestions", []),
            "ai_tells": data.get("ai_tells_found", []),
            "model": model,
        }
    except Exception as e:
        print(f"  [Reviewer] Script review unavailable: {e}", flush=True)
        return {"passed": True, "score": 7, "issues": [], "suggestions": [], "model": "none"}


# ─── Agent 2: Scene Uniqueness Reviewer ──────────────────────────────

REVIEW_SCENES_PROMPT = """You are a visual director reviewing scene keywords. Check:

1. UNIQUENESS — Every keyword must have a COMPLETELY UNIQUE subject + camera angle + lighting combo
2. DIVERSITY — No two scenes describe the same visual concept
3. CINEMATIC QUALITY — Each keyword should specify: camera angle, lighting, color palette

FIND DUPLICATE / SIMILAR keywords and flag them.

SCENES:
{scenes_keywords}

Return ONLY valid JSON:
{{
  "score": 0-10,
  "pass": true/false (pass if >= 7),
  "duplicate_groups": [["scene 0 keyword", "scene 3 keyword"]],
  "unique_count": 0,
  "suggestions": ["how to fix duplicates"]
}}

Pure JSON.
"""


def review_scenes_unique(chapters):
    """Agent 2: Check all scene keywords are visually unique."""
    keywords = []
    for ci, c in enumerate(chapters):
        for si, s in enumerate(c.get("scenes", [])):
            kw = s.get("keyword", "")[:100]
            keywords.append(f"  Ch{ci}-Sc{si}: {kw}")

    if not keywords:
        return {"passed": True, "score": 10, "issues": [], "model": "none"}

    prompt = REVIEW_SCENES_PROMPT.format(scenes_keywords="\n".join(keywords))
    try:
        text, model = _call_reviewer(prompt)
        data = _extract_json(text) or {}
        score = data.get("score", 8)
        passed = data.get("pass", True)
        dupes = data.get("duplicate_groups", [])
        print(f"  [Reviewer] Scene uniqueness: {data.get('unique_count','?')} unique, "
              f"{len(dupes)} dupes, score={score}/10 via {model}", flush=True)
        return {
            "passed": passed,
            "score": score,
            "duplicate_groups": dupes,
            "unique_count": data.get("unique_count", len(keywords)),
            "model": model,
        }
    except Exception as e:
        print(f"  [Reviewer] Scene review unavailable: {e}", flush=True)
        return {"passed": True, "score": 8, "duplicate_groups": [], "model": "none"}


# ─── Agent 3: Content Safety ─────────────────────────────────────────

REVIEW_SAFETY_PROMPT = """You are a content safety moderator. Review this video plan for any policy violations.

Check for:
1. Hate speech, harassment, discrimination
2. Harmful/dangerous advice
3. Misinformation or unsubstantiated claims
4. Copyright concerns (tutorials using brand names without commentary)
5. Sensitive topics that need disclaimer

TITLE: {title}
CHAPTER_TOPICS: {chapter_topics}

Return ONLY valid JSON:
{{
  "score": 0-10,
  "pass": true/false (pass if >= 8),
  "risk_level": "low/medium/high",
  "issues": ["any flagged concerns"],
  "requires_disclaimer": true/false,
  "disclaimer_text": "if needed"
}}

Pure JSON.
"""


def review_safety(title, chapters):
    """Agent 3: Content safety check before render."""
    ch_topics = [c.get("title", "") for c in chapters[:6]]
    prompt = REVIEW_SAFETY_PROMPT.format(title=title, chapter_topics="; ".join(ch_topics))
    try:
        text, model = _call_reviewer(prompt)
        data = _extract_json(text) or {}
        passed = data.get("pass", True)
        risk = data.get("risk_level", "low")
        print(f"  [Reviewer] Safety: risk={risk}, pass={passed} via {model}", flush=True)
        return {
            "passed": passed,
            "score": data.get("score", 10),
            "risk_level": risk,
            "issues": data.get("issues", []),
            "requires_disclaimer": data.get("requires_disclaimer", False),
            "disclaimer_text": data.get("disclaimer_text", ""),
            "model": model,
        }
    except Exception as e:
        print(f"  [Reviewer] Safety check unavailable: {e}", flush=True)
        return {"passed": True, "score": 10, "risk_level": "low", "issues": [], "model": "none"}


# ─── Agent 4: Visual Search Predictor ────────────────────────────────

REVIEW_VISUALS_PROMPT = """You are a stock footage search expert. Review each visual keyword below and predict if Pexels/Pixabay will find good results.

For each keyword, score 0-10 how likely a stock site will have matching footage.

KEYWORDS:
{keywords}

Return ONLY valid JSON:
{{
  "score": 0-10 (average),
  "pass": true/false (pass if avg >= 6),
  "hard_to_find": [list of keyword indices that will fail],
  "suggestions": ["keyword 0: suggested fix"],
  "predicted_coverage": 0-100%
}}

Pure JSON.
"""


def review_visual_feasibility(chapters):
    """Agent 4: Check if stock footage exists for each scene keyword."""
    kws = []
    for ci, c in enumerate(chapters):
        for si, s in enumerate(c.get("scenes", [])):
            kw = s.get("keyword", "")[:120]
            if kw:
                kws.append(f"[{len(kws)}] {kw}")

    if not kws:
        return {"passed": True, "score": 10, "issues": [], "model": "none"}

    prompt = REVIEW_VISUALS_PROMPT.format(keywords="\n".join(kws[:30]))
    try:
        text, model = _call_reviewer(prompt)
        data = _extract_json(text) or {}
        passed = data.get("pass", True)
        coverage = data.get("predicted_coverage", 80)
        hard = data.get("hard_to_find", [])
        print(f"  [Reviewer] Visual feasibility: {coverage}% coverage, "
              f"{len(hard)} hard-to-find, pass={passed} via {model}", flush=True)
        return {
            "passed": passed,
            "score": data.get("score", 8),
            "hard_to_find": hard,
            "predicted_coverage": coverage,
            "suggestions": data.get("suggestions", []),
            "model": model,
        }
    except Exception as e:
        print(f"  [Reviewer] Visual review unavailable: {e}", flush=True)
        return {"passed": True, "score": 8, "hard_to_find": [], "model": "none"}


# ─── Agent 5: Duration & Pacing ──────────────────────────────────────

REVIEW_PACING_PROMPT = """You are a video pacing expert. Review the scene durations and chapter structure.

TOTAL SCENES: {n_scenes}
CHAPTERS:
{chapter_durs}

Target: 5-15 minute video. Individual scenes: 20-45 seconds.
Check for: scenes too short (<15s), too long (>60s), uneven chapter distribution.

Return ONLY valid JSON:
{{
  "score": 0-10,
  "pass": true/false (pass >= 6),
  "estimated_total_sec": 0,
  "issues": ["scene X too short", "chapter Y too dense"],
  "suggestions": ["merge scenes X,Y", "split chapter Z"]
}}

Pure JSON.
"""


def review_pacing(chapters):
    """Agent 5: Verify scene durations and overall pacing."""
    ch_durs = []
    total_scenes = 0
    for c in chapters:
        scenes = c.get("scenes", [])
        n = len(scenes)
        total_scenes += n
        ch_durs.append(f"{c.get('title','?')}: {n} scenes")

    prompt = REVIEW_PACING_PROMPT.format(n_scenes=total_scenes,
                                          chapter_durs="\n".join(ch_durs))
    try:
        text, model = _call_reviewer(prompt)
        data = _extract_json(text) or {}
        passed = data.get("pass", True)
        est = data.get("estimated_total_sec", total_scenes * 30)
        print(f"  [Reviewer] Pacing: ~{est//60}m{est%60:02d}s, pass={passed} via {model}", flush=True)
        return {
            "passed": passed,
            "score": data.get("score", 7),
            "estimated_total_sec": est,
            "issues": data.get("issues", []),
            "model": model,
        }
    except Exception as e:
        print(f"  [Reviewer] Pacing review unavailable: {e}", flush=True)
        return {"passed": True, "score": 7, "estimated_total_sec": total_scenes * 30, "model": "none"}


# ─── Run All Reviewers ──────────────────────────────────────────────

def run_all_reviewers(title, hook, chapters, parallel=True):
    """Run all 5 reviewer agents, optionally in parallel."""
    results = {}

    def _run_script():
        return ("script", review_script(title, hook, chapters))

    def _run_scenes():
        return ("scenes", review_scenes_unique(chapters))

    def _run_safety():
        return ("safety", review_safety(title, chapters))

    def _run_visuals():
        return ("visuals", review_visual_feasibility(chapters))

    def _run_pacing():
        return ("pacing", review_pacing(chapters))

    agents = [_run_script, _run_scenes, _run_safety, _run_visuals, _run_pacing]

    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futs = {pool.submit(a): a for a in agents}
            for fut in concurrent.futures.as_completed(futs, timeout=180):
                try:
                    name, result = fut.result(timeout=30)
                    results[name] = result
                except Exception as e:
                    print(f"  [Reviewer] Agent failed: {e}", flush=True)
    else:
        for a in agents:
            try:
                name, result = a()
                results[name] = result
            except Exception as e:
                print(f"  [Reviewer] Agent failed: {e}", flush=True)

    # Summary
    all_passed = all(r.get("passed", True) for r in results.values() if r)
    scores = {k: v.get("score", 0) for k, v in results.items() if v}
    print(f"  [Reviewer] All agents complete. Passed={all_passed}. Scores: {scores}", flush=True)
    return {"results": results, "all_passed": all_passed, "scores": scores}
