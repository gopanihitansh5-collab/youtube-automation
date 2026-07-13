"""Long-form chapter-based prompt builder with diversity engine.

Produces plans with 4-8 chapters, each containing 5-10 scenes,
designed for 8-15 minute landscape YouTube videos.
"""
import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

_MAX_MEMORY = 200

_MEMORY_FILES = {
    "combo": Path("output/.prompt_history.json"),
    "hooks": Path("output/.used_hooks.json"),
    "fingerprints": Path("output/.fingerprints.json"),
}


def _load_memory(key):
    path = _MEMORY_FILES[key]
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return data[-_MAX_MEMORY:]
        except Exception:
            pass
    return []


def _save_memory(key, items):
    path = _MEMORY_FILES[key]
    hist = _load_memory(key)
    hist.extend(items if isinstance(items, list) else [items])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hist[-_MAX_MEMORY:]))


def _recently_used(combo, threshold=3):
    hist = _load_memory("combo")
    return hist.count(combo) >= threshold


LONG_FORM_ARCS = [
    {"name": "educational_deep_dive", "description": "Teach a concept from first principles, building understanding layer by layer with clear progression", "chapters": (5, 8)},
    {"name": "documentary", "description": "Chronological exploration of a topic with historical context, key milestones, and primary sources", "chapters": (5, 7)},
    {"name": "case_study", "description": "Deep forensic analysis of one specific example, event, or subject with granular detail", "chapters": (4, 6)},
    {"name": "explainer", "description": "How something works, step by step, breaking down complexity into digestible mental models", "chapters": (5, 8)},
    {"name": "analysis", "description": "Data-driven breakdown of a situation, trend, or phenomenon with statistical evidence", "chapters": (4, 7)},
    {"name": "tutorial", "description": "Actionable guide with clear steps the viewer can follow and apply immediately in real life", "chapters": (5, 7)},
    {"name": "comparison", "description": "Side-by-side examination of two approaches, systems, or philosophies with balanced evaluation", "chapters": (4, 6)},
    {"name": "debate", "description": "Present both sides of a controversial topic with rigorous fair treatment of each position", "chapters": (4, 6)},
    {"name": "investigative", "description": "Follow evidence and clues to uncover hidden truths or expose misconceptions layer by layer", "chapters": (5, 8)},
    {"name": "philosophical", "description": "Explore fundamental questions about meaning, existence, knowledge, and values through multiple lenses", "chapters": (4, 6)},
    {"name": "biographical", "description": "Trace the life, work, and impact of a remarkable person or group through defining moments", "chapters": (5, 7)},
    {"name": "systems", "description": "Map how interconnected parts form a whole, revealing emergent behavior and leverage points", "chapters": (5, 8)},
]

CHAPTER_TEMPLATES = {
    "educational_deep_dive": [
        "What Is {t}? — The Foundation", "How {t} Actually Works",
        "The Science Behind {t}", "Common Misconceptions About {t}",
        "Real-World Applications of {t}", "The Future of {t}",
        "Why {t} Matters to You", "Putting {t} Into Practice",
    ],
    "documentary": [
        "The Origin of {t}", "The Early Days of {t}",
        "The Turning Point for {t}", "How {t} Changed Everything",
        "The Modern Era of {t}", "Controversies Around {t}",
        "Where {t} Is Headed", "The Legacy of {t}",
    ],
    "case_study": [
        "Setting the Stage for {t}", "The Key Players in {t}",
        "The Critical Moment of {t}", "What the Data Says About {t}",
        "The Aftermath of {t}", "Lessons Learned from {t}",
        "How {t} Applies to You",
    ],
    "explainer": [
        "Why {t} Exists", "The Core Mechanism of {t}",
        "Breaking Down How {t} Works", "The Components of {t}",
        "How {t} Interacts With Everything", "Practical Examples of {t}",
        "Troubleshooting {t}",
    ],
    "analysis": [
        "The Current State of {t}", "Key Metrics That Define {t}",
        "Trends Shaping {t}", "The Contrarian View on {t}",
        "What Experts Predict for {t}", "The Data Behind {t}",
        "What This Means for the Future",
    ],
    "tutorial": [
        "What You Will Need for {t}", "Step 1: Preparing for {t}",
        "Step 2: The Core Process of {t}", "Step 3: Refining Your {t} Approach",
        "Common Mistakes in {t}", "Advanced {t} Techniques",
        "Next Steps After Mastering {t}",
    ],
    "comparison": [
        "Introducing the Two Sides of {t}", "How Approach A Handles {t}",
        "How Approach B Handles {t}", "Head-to-Head: {t} Performance",
        "Cost-Benefit Analysis of {t}", "Which Approach Wins for {t}",
        "Hybrid Strategies for {t}",
    ],
    "debate": [
        "The Case for {t}", "The Case Against {t}",
        "Where Both Sides Agree on {t}", "The Gray Area of {t}",
        "Evidence That Challenges {t}", "Reconciling the Two Views on {t}",
        "Your Verdict on {t}",
    ],
    "investigative": [
        "The Question at the Heart of {t}", "Following the First Clue",
        "The Evidence Stack", "The Cover-Up or Misconception",
        "The Breakthrough Discovery", "Connecting All the Dots",
        "The Full Truth About {t}",
    ],
    "philosophical": [
        "Why {t} Demands Our Attention", "The Classical View on {t}",
        "The Modern Challenge to {t}", "What the Sciences Say About {t}",
        "The Practical Wisdom of {t}", "Reconciling Perspectives on {t}",
        "How to Live with {t}",
    ],
    "biographical": [
        "Before They Were Known", "The Formative Years",
        "The Defining Challenge", "The Breakthrough Moment",
        "The Peak of Influence", "The Later Years and Reflection",
        "The Lasting Legacy",
    ],
    "systems": [
        "Mapping the {t} Landscape", "The Core Components of {t}",
        "Feedback Loops in {t}", "Emergent Behavior of {t}",
        "Leverage Points in {t}", "When {t} Systems Break Down",
        "Designing Better {t} Systems",
    ],
}

VOICES = [
    {"name": "authoritative", "style": "confident expert-level tone that speaks with certainty", "persona": "You are a recognized authority in this field"},
    {"name": "curious", "style": "exploratory, discovering together with the viewer", "persona": "You are genuinely fascinated by this topic"},
    {"name": "conversational", "style": "relaxed friendly chat like talking to a close friend", "persona": "You are a friend sharing something interesting"},
    {"name": "empathetic", "style": "warm understanding tone that validates the viewer's journey", "persona": "You deeply understand the viewer's challenges"},
    {"name": "storyteller", "style": "lyrical vivid narrative style with rich sensory language", "persona": "You paint pictures with words and transport the viewer"},
    {"name": "skeptical", "style": "questioning, challenging assumptions, devil's advocate", "persona": "You question everything and demand evidence"},
    {"name": "direct", "style": "blunt no-nonsense straight to the point with zero fluff", "persona": "You waste no words and deliver pure value"},
    {"name": "inspirational", "style": "uplifting motivating tone with powerful empowering statements", "persona": "Your mission is to lift the viewer up"},
]

TONES = ["educational", "authoritative", "engaging", "thoughtful", "analytical", "conversational", "inspiring", "critical"]

HOOK_STYLES = [
    "question", "bold_claim", "surprising_stat", "story_opener",
    "myth_debunk", "relatable", "challenge", "curiosity_gap",
]

CTA_STYLES = ["subscribe", "comment", "share", "save", "next_video", "reflect", "try_it", "learn_more"]

SCENE_PURPOSE_POOL = [
    "introduce_concept", "deepen_understanding", "provide_evidence",
    "counter_argument", "real_world_example", "data_point",
    "historical_context", "practical_application", "common_mistake",
    "expert_insight", "future_implication", "key_takeaway",
    "transition_to_next", "summary_so_far",
]

RHETORICAL_DEVICES = [
    "rhetorical question to engage the viewer",
    "rule of three for emphasis",
    "metaphor or analogy for complex ideas",
    "hypophora (ask a question then answer it)",
    "direct quote from an expert or study",
    "contrast (not X, but Y)",
    "anecdote or mini-story",
    "statistical fact for credibility",
]

_ANGLE_TEMPLATES = [
    "the hidden truth about {t}",
    "why {t} matters more than you think",
    "how {t} is changing everything",
    "the complete guide to {t}",
    "what nobody tells you about {t}",
    "the science behind {t}",
    "the history of {t} nobody knows",
    "how to master {t} starting from zero",
    "the biggest myths about {t}",
    "why most people misunderstand {t}",
    "the untold story of {t}",
    "everything you need to know about {t}",
    "the dark side of {t}",
    "the future of {t}",
    "how {t} affects your daily life",
]

_POWER_WORDS = [
    "shocking", "secret", "ultimate", "essential", "hidden", "proven",
    "critical", "powerful", "game-changing", "controversial",
    "mind-blowing", "dangerous", "forbidden", "forgotten", "unstoppable",
]


def _drift_topic(topic, rng):
    t = topic.strip().rstrip(".!?").lower()
    template = rng.choice(_ANGLE_TEMPLATES)
    angle = template.replace("{t}", t).capitalize()
    if rng.random() < 0.3:
        pw = rng.choice(_POWER_WORDS)
        angle = f"The {pw} Truth About {t.title()}"
    return angle


def _seed(topic):
    raw = (topic + os.environ.get("GITHUB_RUN_ID", "")).encode()
    return int(hashlib.md5(raw).hexdigest()[:8], 16)


HOOK_TEMPLATES = {
    "question": [
        "Did you know that {detail}?",
        "What if {provocation}?",
        "Have you ever wondered why {curiosity}?",
        "What would happen if {reveal}?",
    ],
    "bold_claim": [
        "This {topic} secret changes everything you thought you knew.",
        "Nothing prepares you for this {topic} truth.",
        "Here is why {topic} will never be the same again.",
        "The real reason {topic} matters more than you realize.",
    ],
    "surprising_stat": [
        "{percent}% of people do not know this about {topic}.",
        "Studies show {finding} about {topic}.",
        "The number behind {topic} will shock you.",
        "Here is what {percent}% of experts get wrong about {topic}.",
    ],
    "story_opener": [
        "I discovered something about {topic} that changed my perspective forever.",
        "Let me tell you a {topic} story you have not heard before.",
        "The day I learned the truth about {topic} changed everything.",
        "Here is what happened when I investigated {topic} for myself.",
    ],
    "myth_debunk": [
        "Everything you think you know about {topic} is wrong.",
        "Stop believing this common {topic} myth right now.",
        "Here is the truth about {topic} they do not want you to know.",
        "The biggest {topic} myth that is holding you back.",
    ],
    "relatable": [
        "If you have ever struggled with {topic}, this video is for you.",
        "We have all been misled about {topic} at some point.",
        "You are not alone in finding {topic} confusing.",
        "This {topic} problem feels impossible, but here is the truth.",
    ],
    "challenge": [
        "I challenge you to reconsider everything you know about {topic}.",
        "Try looking at {topic} from this angle and see what changes.",
        "Here is a {topic} perspective that will challenge your assumptions.",
    ],
    "curiosity_gap": [
        "The secret about {topic} that nobody talks about in mainstream discussions.",
        "Here is why {topic} is not what you think it is at all.",
        "There is one aspect of {topic} that changes the entire picture.",
        "What they are not telling you about {topic} will surprise you.",
    ],
}

HOOK_FILLERS = {
    "detail": "most people overlook this critical factor",
    "provocation": "everything you understood so far needs a complete rethink",
    "curiosity": "the most successful people approach this completely differently",
    "finding": "consistent patterns emerge across decades of research",
    "reveal": "when you dig deeper than surface-level understanding",
    "percent": "87",
    "topic": "this topic",
}


def _generate_hook(hook_style, topic, rng):
    templates = HOOK_TEMPLATES.get(hook_style, HOOK_TEMPLATES["bold_claim"])
    fillers = dict(HOOK_FILLERS)
    fillers["topic"] = topic.strip().rstrip(".!?").lower()
    hook = rng.choice(templates)
    for k, v in fillers.items():
        hook = hook.replace("{" + k + "}", v)
    hook = hook[0].upper() + hook[1:]
    return hook[:100]


def _build_fingerprint(meta):
    raw = json.dumps(meta, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _ensure_unique_fingerprint(fingerprint):
    hist = _load_memory("fingerprints")
    if fingerprint in hist:
        return False
    _save_memory("fingerprints", fingerprint)
    return True


ENERGY_PALETTE_DESC = {
    "calm": "soft, muted, pastel or earth tones with gentle lighting",
    "curious": "cool blues, teals, with sharp focus and clean lines",
    "energetic": "warm oranges, yellows, high contrast and dynamic range",
    "intense": "deep reds, dark shadows, dramatic chiaroscuro lighting",
    "hopeful": "golden hour warmth, bright highlights, airy composition",
    "thoughtful": "deep indigos, sepia tones, contemplative framing",
}

SCENE_PURPOSE_DESC = {
    "introduce_concept": "introduce a new idea clearly and simply",
    "deepen_understanding": "build on the previous concept with more depth",
    "provide_evidence": "show data, research, or proof for the claim",
    "counter_argument": "present an opposing view fairly",
    "real_world_example": "give a concrete example the viewer can relate to",
    "data_point": "cite a specific statistic or research finding",
    "historical_context": "provide background that led to the current situation",
    "practical_application": "show how this applies in real life",
    "common_mistake": "highlight errors people often make",
    "expert_insight": "share what authorities in the field say",
    "future_implication": "explore where this trend is heading",
    "key_takeaway": "distill the most important point from this section",
    "transition_to_next": "bridge to the next chapter naturally",
    "summary_so_far": "recap what has been covered to reinforce learning",
}


def build_long_prompt(topic, trending_context=None):
    entropy = int.from_bytes(os.urandom(4)) + time.time_ns()
    rng = random.Random(_seed(topic) + entropy)

    drifted = _drift_topic(topic, rng)

    for _ in range(20):
        arc_candidate = rng.choice(LONG_FORM_ARCS)
        combo_key = f"long_arc:{arc_candidate['name']}"
        if not _recently_used(combo_key):
            break
    arc = arc_candidate

    num_chapters = rng.randint(*arc["chapters"])
    chapter_titles = CHAPTER_TEMPLATES.get(arc["name"], ["Introduction to {t}", "Deep Dive into {t}", "Conclusion"])
    selected_titles = []
    rng.shuffle(chapter_titles)
    for i in range(num_chapters):
        if i < len(chapter_titles):
            title = chapter_titles[i]
        else:
            title = f"{['Exploring','Understanding','Analyzing','Examining','Discovering'][i % 5]} {arc['name'].replace('_', ' ').title()} — Part {i + 1}"
        selected_titles.append(title.replace("{t}", topic.strip().rstrip(".!?")))

    voice = rng.choice(VOICES)
    tone = rng.choice(TONES)
    hook_style = rng.choice(HOOK_STYLES)
    cta = rng.choice(CTA_STYLES)
    hook_text = _generate_hook(hook_style, topic, rng)
    rhetorical = rng.sample(RHETORICAL_DEVICES, k=rng.randint(2, 4))

    scenes_per_chapter = rng.randint(5, 10)

    total_scenes = num_chapters * scenes_per_chapter
    arc_energies = ["calm", "curious", "energetic", "intense", "hopeful", "thoughtful"]
    scene_energies = [rng.choice(arc_energies) for _ in range(total_scenes)]

    chapter_guide_lines = []
    scene_idx = 0
    for ci, ct in enumerate(selected_titles):
        chapter_guide_lines.append(f"  Chapter {ci + 1}: \"{ct}\" ({scenes_per_chapter} scenes)")
        for si in range(scenes_per_chapter):
            purpose = rng.choice(SCENE_PURPOSE_POOL)
            energy = scene_energies[scene_idx]
            chapter_guide_lines.append(f"    Scene {si + 1}: energy={energy}, purpose={purpose}")
            scene_idx += 1

    chapter_guide = "\n".join(chapter_guide_lines)

    _save_memory("combo", f"long_arc:{arc['name']}")
    _save_memory("combo", f"long_voice:{voice['name']}")

    meta = {
        "arc": arc["name"],
        "voice": voice["name"],
        "tone": tone,
        "hook_style": hook_style,
        "cta": cta,
        "num_chapters": num_chapters,
        "scenes_per_chapter": scenes_per_chapter,
        "scene_energies": scene_energies,
        "chapter_titles": selected_titles,
    }
    fingerprint = _build_fingerprint(meta)
    _ensure_unique_fingerprint(fingerprint)
    meta["fingerprint"] = fingerprint

    BO = "You are a world-class long-form YouTube content creator building a trusted educational brand."
    prompt = f"""{BO} Every script must feel 100% human-written — no AI patterns, no robotic phrasing, no repetitive structures.

BRAND IDENTITY — This channel is building long-term viewer trust. Every video must:
- Deliver genuine deep understanding, not surface-level facts
- Sound like a passionate expert explaining to a curious friend
- Use specific examples, stories, and analogies — never vague generic statements
- Respect the viewer's intelligence while making complex ideas accessible
- End with the viewer feeling genuinely smarter, not just entertained

CONTENT ANGLE: {drifted}

NARRATIVE ARC: {arc['name'].replace('_', ' ').title()} — {arc['description']}

NARRATIVE VOICE: {voice['name']}
{voice['persona']}
Voice delivery style: {voice['style']}

EMOTIONAL TONE: {tone.upper()}

HOOK STYLE REFERENCE: "{hook_text}"
Use this exact style for your opening hook.

END CALL TO ACTION STYLE: {cta.replace('_', ' ').title()}

RHETORICAL TECHNIQUES TO INCLUDE: {', '.join(rhetorical)}

SCENE ENERGY COLOR PALETTES:
- calm: {ENERGY_PALETTE_DESC['calm']}
- curious: {ENERGY_PALETTE_DESC['curious']}
- energetic: {ENERGY_PALETTE_DESC['energetic']}
- intense: {ENERGY_PALETTE_DESC['intense']}
- hopeful: {ENERGY_PALETTE_DESC['hopeful']}
- thoughtful: {ENERGY_PALETTE_DESC['thoughtful']}

SCENE PURPOSE DESCRIPTIONS:
{chr(10).join(f"- {k}: {v}" for k, v in SCENE_PURPOSE_DESC.items())}

STRUCTURE OVERVIEW ({num_chapters} chapters, ~{scenes_per_chapter} scenes each):
{chapter_guide}

RETENTION ARCHITECTURE (MANDATORY):
1. OPENING (first 30s): Pattern interrupt hook that establishes stakes. Tell them what they will learn and why it matters.
2. EVERY CHAPTER: Start with a mini-hook that previews what this chapter covers. End with a reason to watch the next chapter.
3. EVERY 60-90s: Plant a breadcrumb — tease something coming later to reduce drop-off.
4. VALUE DENSITY: Every scene must deliver either: a surprising fact, a counter-intuitive insight, a practical takeaway, or an emotional beat.
5. CLIMAX: Place the biggest reveal or strongest argument at ~80% of the video, not at the end.
6. CONCLUSION: Summarize the transformation. Give a clear single next step. End with a question to drive comments.
7. CHAPTER TRANSITIONS: Use verbal cues like "Now that we understand X, let's look at Y" for natural chapter boundaries.

HUMAN AUTHENTICITY RULES (MANDATORY — VIOLATION BREAKS THE ILLUSION):
1. Vary sentence starters aggressively. Never begin two consecutive sentences with the same word. Never begin more than 3 sentences in a chapter with the same part of speech.
2. Use contractions naturally (don't, can't, won't, isn't, it's, there's, that's, they've).
3. Occasionally start a sentence with "And", "But", "So", "Or", "Because" — real humans speak this way.
4. Include one specific concrete example per chapter — a real number, a named person, a specific date, a place, or a study citation.
5. Use analogies and metaphors to explain abstract concepts. At least one per chapter.
6. Vary paragraph length. A single short punchy sentence followed by a longer 3-sentence explanation creates natural rhythm.
7. No formulaic transitions. Instead of "Now let's look at X", try "X tells a completely different story" or "This is where X gets fascinating".
8. Read every scene aloud. If it sounds like it was written by AI, rewrite it until it sounds like a human expert speaking naturally.
9. Include one rhetorical question per chapter that makes the viewer pause and think.
10. Never use the phrases: "delve into", "let's dive in", "in this video we'll explore", "it's worth noting", "in conclusion", "overall", "essentially". These are AI tells.

ANTI-REPETITION RULES:
- Every scene's keyword must describe a COMPLETELY UNIQUE visual — different subject, camera angle, lighting, color palette, and mood.
- No two scenes across the entire script should have similar visual keywords.
- Vary narration structure dramatically between scenes: question→answer, statement→evidence, example→implication, contrast→resolution.
- The opening hook and the closing scene must use structurally different sentence patterns.

SELF-SCORING (REQUIRED):
- virality_score (0.0-1.0): How likely is this to be shared/saved/bookmarked? Must exceed 0.65.
- attention_score (0.0-1.0): How well does it retain attention across the FULL duration? Must exceed 0.65.
- authenticity_score (0.0-1.0): How much does this sound like a real human expert? Must exceed 0.75.
If any score is below threshold, rewrite the entire script.

OUTPUT FORMAT:
Return ONLY valid JSON with EXACTLY these keys:
{{
  "title": "SEO-optimised title <= 80 chars, primary keyword near the start, no clickbait without delivery",
  "description": "3-5 punchy lines with emojis, then chapter timestamps (0:00 - Hook\\n2:15 - Chapter 1\\n...), then 8-10 relevant #hashtags",
  "tags": ["12", "lowercase", "seo", "tags"],
  "hook": "8-15 word hook that stops the scroll — a genuine curiosity gap or bold claim",
  "comment": "specific opinion question that drives thoughtful discussion replies, not generic",
  "virality_score": 0.0,
  "attention_score": 0.0,
  "authenticity_score": 0.0,
  "chapters": [
    {{
      "title": "Chapter Title Here",
      "timestamp_sec": 0,
      "scenes": [
        {{"narration": "3-5 sentences delivering one complete narrative beat in natural spoken language. 40-80 words. Should include one specific detail (number, name, example).", "keyword": "CINEMATIC VISUAL BRIEF 15-25 words for landscape 16:9 stock footage — unique perspective, lighting, and subject"}}
      ]
    }}
  ]
}}

TIME BUDGET: 8-15 minute YouTube video.
- Total script: 480-900 seconds spoken.
- Each scene: 25-45 seconds (3-5 sentences, 40-80 words).
- Each chapter: 5-10 scenes, ends with a verbal bridge to the next chapter.
- Leave natural breathing room between scenes — real pauses, not robotic gaps.

NARRATION MASTERY:
- Match the {voice['name']} voice and {tone} tone exactly.
- Follow the {arc['name'].replace('_', ' ').title()} narrative arc naturally.
- Vary sentence TEMPO: short (5-10 words) for emphasis and punch, medium (12-20) for explanation and flow, long (20-35) for immersion and depth.
- NEVER start two consecutive sentences with the same word.
- Use {', '.join(rhetorical)} naturally — they should feel organic, not forced.
- Each chapter must end with a reason to watch the next, not a robotic "now let's move on".
- No emojis, hashtags, URLs, or speaker labels in narration. Pure spoken word.
- Read every scene aloud. If it does not flow naturally when spoken aloud by a human, rewrite it completely.

CINEMATIC KEYWORD ARCHITECTURE:
Each "keyword" is a visual brief for stock footage search (landscape 16:9). Rules:
- 15-25 words describing ONE continuous frame with a specific subject.
- Include: primary subject, camera perspective (wide, medium, close-up, aerial, POV, tracking, dolly, crane, macro, Dutch angle), lighting quality (golden hour, dramatic shadows, soft diffused, neon, rim light, volumetric), color atmosphere.
- Match scene's energy level for mood.
- Every keyword must have a COMPLETELY UNIQUE subject + perspective + lighting combo from all others.
- NEVER repeat a visual concept across scenes. If one scene uses "close up of hands typing", the next must use something completely different like "wide aerial cityscape at dusk".

Valid JSON only. No markdown fences. No explanatory text outside JSON. Never include "Here is the JSON" or similar.

TOPIC: "{topic}"
"""
    if trending_context:
        tc = trending_context
        ctx_lines = []
        if tc.get("top_trending_topic"):
            ctx_lines.append(f"TRENDING RIGHT NOW: {tc['top_trending_topic']}")
        if tc.get("reason"):
            ctx_lines.append(f"WHY IT MATTERS: {tc['reason']}")
        if tc.get("briefings"):
            for b in tc["briefings"]:
                cat = b.get("category", "general")
                hl = (b.get("headlines") or [])
                if hl:
                    ctx_lines.append(f"{cat.upper()}: {' | '.join(hl[:3])}")
        if ctx_lines:
            prompt += "\n\nCURRENT CONTEXT (integrate naturally into the narrative):\n" + "\n".join(ctx_lines)
            prompt += "\n\nReference these current events where relevant to make the content timely and grounded in real news."

    return prompt, meta


def build_offline_long_script(topic, meta=None):
    rng = random.Random(_seed(topic) + int.from_bytes(os.urandom(4)))
    t = topic.strip().rstrip(".!?")
    meta = meta or {}
    arc_name = meta.get("arc", "educational_deep_dive")
    num_ch = meta.get("num_chapters", rng.randint(4, 6))
    spc = meta.get("scenes_per_chapter", rng.randint(5, 8))
    chapter_titles = meta.get("chapter_titles", [f"Chapter {i+1}" for i in range(num_ch)])
    cta_style = meta.get("cta", rng.choice(CTA_STYLES))
    hook_style = meta.get("hook_style", rng.choice(HOOK_STYLES))

    hook_line = _generate_hook(hook_style, t, rng)

    openers = [
        f"Let us begin our exploration of {t} by understanding the fundamentals.",
        f"To properly understand {t}, we first need to establish some context.",
        f"The story of {t} starts with a question that few people ask.",
        f"Before we dive deep into {t}, let us set the stage properly.",
    ]
    mid_scenes = [
        f"This is where {t} gets really interesting. The data reveals a pattern that most people miss.",
        f"Here is a critical insight about {t} that changes how we should think about it.",
        f"Research into {t} shows us something counter-intuitive that is worth examining closely.",
        f"Let us look at what the evidence actually says about {t} rather than what people assume.",
        f"A common misconception about {t} is that it works one way, but the reality is more nuanced.",
        f"What makes {t} so fascinating is the unexpected connection to broader trends.",
        f"Experts in {t} have been debating this point for years, and here is where the consensus is settling.",
        f"The practical implications of {t} are more significant than most people realize.",
    ]
    closers = [
        f"Now that we have explored {t} in depth, let us summarize what really matters.",
        f"The key takeaway from everything we have covered about {t} is simpler than you might think.",
        f"As we have seen throughout this exploration of {t}, the truth is both fascinating and practical.",
        f"What we have learned about {t} today has real implications for how we move forward.",
    ]

    cta_lines = {
        "subscribe": "If you found this valuable, subscribe for more deep dives like this one.",
        "comment": "What is your take on this? I would love to hear your perspective in the comments.",
        "share": "Share this video with someone who needs to understand this topic better.",
        "save": "Save this video for later reference — you will want to come back to these insights.",
        "next_video": "Click the next video to continue your learning journey on this topic.",
        "reflect": "Take a moment to reflect on how this applies to your own situation.",
        "try_it": "Try applying one insight from this video today and see what changes.",
        "learn_more": "The resources linked in the description will help you go even deeper.",
    }

    scenes_all = []
    offset = 0
    for ci in range(num_ch):
        ch_title = chapter_titles[ci] if ci < len(chapter_titles) else f"Chapter {ci + 1}"
        chapter_scenes = []
        for si in range(spc):
            if ci == 0 and si == 0:
                nar = rng.choice(openers).replace("{t}", t)
            elif si == spc - 1:
                nar = rng.choice(mid_scenes).replace("{t}", t)
                if ci < num_ch - 1:
                    next_ch = chapter_titles[ci + 1] if ci + 1 < len(chapter_titles) else f"the next section"
                    nar += f" This naturally brings us to {next_ch}, where we will explore this further."
            else:
                nar = rng.choice(mid_scenes).replace("{t}", t)

            energy = rng.choice(["calm", "curious", "energetic", "intense", "hopeful", "thoughtful"])
            vis_keywords = {
                "calm": f"wide landscape view soft natural lighting peaceful atmosphere serene {t} concept",
                "curious": f"close up detail shot intriguing texture warm amber lighting mysterious {t} exploration",
                "energetic": f"dynamic fast motion time-lapse vibrant colors energetic {t} transformation",
                "intense": f"dramatic low angle shot deep shadows intense spotlight on {t} subject matter",
                "hopeful": f"golden hour sunrise warm optimistic tones bright future of {t} inspiring",
                "thoughtful": f"thoughtful contemplative scene soft window lighting reflective {t} analysis",
            }
            keyword = vis_keywords.get(energy, vis_keywords["calm"])

            chapter_scenes.append({"narration": nar, "keyword": keyword})
            scenes_all.append({"narration": nar, "keyword": keyword})
            offset += rng.randint(25, 45)

        offset = ci * sum([rng.randint(25, 45) for _ in range(spc)])

    total_sec = offset + 30
    chapters_json = []
    ch_offset = 0
    for ci in range(num_ch):
        ch_title = chapter_titles[ci] if ci < len(chapter_titles) else f"Chapter {ci + 1}"
        ch_scenes = scenes_all[ci * spc:(ci + 1) * spc]
        chapters_json.append({
            "title": ch_title,
            "timestamp_sec": ch_offset,
            "scenes": ch_scenes,
        })
        ch_offset += sum(rng.randint(25, 45) for _ in range(spc))

    tag_words = [w for w in re.findall(r"[A-Za-z]+", t) if len(w) > 3][:5]
    cta_line = cta_lines.get(cta_style, cta_lines["subscribe"])

    return {
        "title": f"{t.title()}: The Complete Guide"[:80],
        "description": f"A deep dive into {t}.\n\n"
                       f"{cta_line}\n\n"
                       f"#education #{tag_words[0] if tag_words else 'learning'} "
                       f"#deepdive #{tag_words[1] if len(tag_words) > 1 else 'explained'} "
                       f"#{tag_words[2] if len(tag_words) > 2 else 'knowledge'}",
        "tags": ["education", "deep dive", "explained", "learning"] + tag_words,
        "hook": hook_line,
        "comment": "What did you think? Share your perspective below.",
        "virality_score": round(rng.uniform(0.60, 0.80), 2),
        "attention_score": round(rng.uniform(0.65, 0.85), 2),
        "authenticity_score": round(rng.uniform(0.70, 0.85), 2),
        "chapters": chapters_json,
    }
