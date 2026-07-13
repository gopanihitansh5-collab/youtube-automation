"""Rich description and transcript generator for long-form YouTube videos.

Produces:
  - SEO-optimised YouTube description with chapter timestamps
  - Full timestamped transcript (plain text)
  - SRT subtitle file with chapter markers
  - Markdown blog post version for website/Social
"""
import os
import re
import datetime
import hashlib


def _fmt_ts(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_srt_ts(sec):
    h, rem = divmod(abs(sec), 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def _classify_topic(title, hook):
    t = (title + " " + hook).lower()
    categories = {
        "tech": ["ai", "technology", "software", "coding", "quantum", "cyber", "computer", "digital", "robot", "algorithm", "data", "programming", "app", "startup", "internet", "saas", "blockchain", "cloud", "neural", "gpu", "compute", "api", "automation"],
        "finance": ["money", "invest", "stock", "wealth", "financial", "economy", "crypto", "bitcoin", "market", "trading", "passive income", "recession", "inflation", "budget", "saving", "retire", "dividend", "portfolio", "asset", "equity", "bond"],
        "science": ["science", "physics", "chemistry", "biology", "space", "universe", "evolution", "dna", "brain", "neuroscience", "memory", "sleep", "vaccine", "climate", "dark matter", "quantum", "particle", "gravity", "genetics", "cell", "microbe"],
        "history": ["history", "ancient", "civilization", "war", "empire", "revolution", "origin", "rise and fall", "century", "rome", "greece", "medieval", "renaissance", "colonial", "cold war", "dynasty", "kingdom"],
        "psychology": ["psychology", "mind", "behavior", "cognitive", "bias", "persuasion", "habit", "procrastination", "stoic", "mental", "emotion", "memory", "focus", "personality", "trauma", "anxiety", "depression", "narcissist", "attachment", "motivation"],
        "motivation": ["success", "habit", "discipline", "focus", "productivity", "deep work", "wealth", "master", "goals", "growth", "mindset", "morning", "routine", "confidence", "overcome", "breakthrough", "potential"],
        "education": ["guide", "explained", "tutorial", "complete", "beginners", "learn", "course", "lesson", "how to", "breakdown", "introduction", "overview", "primer", "walkthrough", "masterclass"],
        "philosophy": ["philosophy", "meaning", "existence", "consciousness", "reality", "truth", "ethics", "moral", "logic", "stoicism", "nietzsche", "plato", "aristotle", "socrates", "kant", "free will", "determinism"],
        "health": ["health", "fitness", "nutrition", "diet", "exercise", "sleep", "meditation", "wellness", "longevity", "vitamin", "supplement", "hormone", "gut", "inflammation", "immunity", "aging"],
        "business": ["business", "entrepreneur", "startup", "marketing", "sales", "leadership", "management", "strategy", "revenue", "growth", "brand", "customer", "b2b", "b2c", "funnel", "conversion", "seo", "advertising", "venture"],
    }
    scores = {}
    for cat, keywords in categories.items():
        score = sum(2 for kw in keywords if kw in t) + sum(1 for kw in keywords if kw in t.split())
        if score > 0:
            scores[cat] = score
    if scores:
        return max(scores, key=scores.get)
    return "general"


_CHANNEL_TAGLINES = [
    "Deep dives that actually make you smarter.",
    "Understand the world. One video at a time.",
    "Where curiosity meets clarity.",
    "Knowledge worth sharing.",
    "Think deeper. Learn faster. Stay curious.",
    "Complex ideas, simply explained.",
    "Your daily dose of genuine understanding.",
    "Education that sticks.",
    "Because surface-level is never enough.",
    "The smartest 15 minutes of your day.",
]

_TITLE_PATTERNS = {
    "tech": [
        "{t}: The Complete Guide (2026)",
        "How {t} Actually Works — Full Breakdown",
        "The Truth About {t} Nobody Talks About",
        "{t} Explained: From Zero to Hero",
        "Why {t} Matters More Than You Think",
        "The Hidden World of {t}",
        "{t}: What You Need to Know",
    ],
    "finance": [
        "{t}: The Ultimate Guide",
        "How {t} Works — And Why It Matters",
        "The Truth About {t} Most People Ignore",
        "{t} Explained Simply",
        "Why {t} Is More Important Than Ever",
        "Master {t}: A Complete Overview",
    ],
    "science": [
        "{t}: How It Actually Works",
        "The Science of {t} Explained",
        "{t}: What the Research Really Says",
        "How {t} Changes Everything We Know",
        "The Fascinating World of {t}",
        "{t}: A Journey from First Principles",
    ],
    "history": [
        "The Complete History of {t}",
        "{t}: Rise, Fall, and Legacy",
        "How {t} Shaped the Modern World",
        "The Untold Story of {t}",
        "{t}: A Timeline of Key Moments",
        "What {t} Teaches Us Today",
    ],
    "psychology": [
        "The Psychology of {t}: How Your Brain Works",
        "{t}: The Science Behind It",
        "Why {t} Happens — Psychological Insights",
        "Understanding {t}: A Deep Dive",
        "The Hidden Psychology of {t}",
        "{t} Explained: What the Research Shows",
    ],
    "motivation": [
        "The Science of {t}: How to Master It",
        "{t}: The Complete Framework",
        "Why {t} Is the Key to Everything",
        "How to Master {t} Starting Today",
        "{t}: What Successful People Know",
    ],
    "education": [
        "{t}: A Complete Introduction",
        "How to Understand {t} (Full Guide)",
        "{t} Explained from Scratch",
        "The Essential Guide to {t}",
        "Master {t}: Step-by-Step Breakdown",
    ],
    "philosophy": [
        "{t}: The Ideas That Changed Everything",
        "Understanding {t}: A Philosophical Approach",
        "What {t} Really Means — Deep Dive",
        "The Philosophy of {t} Explained",
        "{t}: Ancient Wisdom for Modern Life",
    ],
    "health": [
        "The Science of {t}: What Really Works",
        "{t}: A Complete Guide to Better Health",
        "How {t} Affects Your Body and Mind",
        "{t} Explained: Facts vs Myths",
        "The Truth About {t} Research Reveals",
    ],
    "business": [
        "The Complete Guide to {t}",
        "How {t} Drives Business Success",
        "{t}: Strategies That Actually Work",
        "Why {t} Matters for Your Business",
        "Master {t}: From Beginner to Pro",
    ],
    "general": [
        "{t}: The Complete Deep Dive",
        "Understanding {t} — Full Breakdown",
        "What Everyone Should Know About {t}",
        "{t}: Everything You Need to Know",
        "The Ultimate Guide to {t}",
        "How {t} Works — And Why It Matters",
    ],
}

_POWER_WORDS_TITLE = [
    "Ultimate", "Essential", "Complete", "Hidden", "Proven",
    "Secret", "Powerful", "Critical", "Game-Changing", "Definitive",
    "Master", "Comprehensive", "Fundamental", "Advanced", "Practical",
]


def refine_title(original, topic, hook, category="general"):
    """Generate multiple title variants and pick the best one."""
    import random
    rng = random.Random(hashlib.md5((original + str(datetime.date.today())).encode()).hexdigest())

    t = topic.strip().rstrip(".!?").title()
    patterns = _TITLE_PATTERNS.get(category, _TITLE_PATTERNS["general"])
    rng.shuffle(patterns)

    variants = []
    for pattern in patterns[:4]:
        title = pattern.format(t=t)
        if len(title) <= 80:
            variants.append(title)

    if original and original not in variants:
        variants.insert(0, original[:80])

    if rng.random() < 0.3 and variants:
        pw = rng.choice(_POWER_WORDS_TITLE)
        best = variants[0]
        prefix = f"The {pw} Guide to "
        if not best.startswith(prefix) and len(prefix + t) <= 80:
            variants.insert(0, f"{prefix}{t}")

    return variants[0] if variants else original[:80]


def generate_taglines(title, hook, category="general"):
    """Generate brand tagline and video-specific taglines."""
    channel_tagline = _CHANNEL_TAGLINES[hashlib.md5(title.encode()).hexdigest()[0] % len(_CHANNEL_TAGLINES)]

    video_taglines = [
        hook[:80],
        f"Understand {title.split(':')[0].split(' —')[0].strip()[:60]}.",
        f"Everything you need to know about {title.split('—')[0].strip()[:60]}.",
        f"Master this topic in {title.split('—')[0].strip()[:30]} minutes.",
    ]
    import random
    rng = random.Random(hashlib.md5((title + "tagline").encode()).hexdigest())
    primary_tagline = rng.choice(video_taglines)

    return {
        "channel_tagline": channel_tagline,
        "video_tagline": primary_tagline,
        "all_video_taglines": video_taglines,
    }


_HASHTAG_POOL = {
    "tech": {
        "broad": ["#technology", "#tech", "#innovation", "#future", "#engineering", "#science"],
        "niche": ["#ai", "#machinelearning", "#coding", "#programming", "#software", "#datascience", "#cybersecurity", "#cloudcomputing", "#blockchain", "#startup", "#computerscience", "#devops", "#webdev", "#opensource"],
        "trending": ["#artificialintelligence", "#chatgpt", "#ai", "#technews", "#innovation"],
        "longtail": ["#howtechnologyworks", "#techdeepdive", "#futureoftech", "#techexplained", "#understandingai"],
    },
    "finance": {
        "broad": ["#finance", "#money", "#investing", "#wealth", "#economy", "#personalfinance"],
        "niche": ["#stockmarket", "#crypto", "#bitcoin", "#trading", "#passiveincome", "#financialfreedom", "#retirement", "#realestate", "#dividends", "#budgeting", "#debtfree", "#wealthbuilding"],
        "trending": ["#crypto", "#bitcoin", "#recession", "#inflation", "#investing"],
        "longtail": ["#personalfinancetips", "#moneymanagement", "#wealthbuilding", "#investingforbeginners", "#financialliteracy"],
    },
    "science": {
        "broad": ["#science", "#physics", "#biology", "#chemistry", "#research", "#discovery"],
        "niche": ["#neuroscience", "#evolution", "#space", "#quantumphysics", "#genetics", "#microbiology", "#astrophysics", "#cosmology", "#climatechange", "#medicine"],
        "trending": ["#space", "#nasa", "#quantum", "#neuroscience", "#vaccine"],
        "longtail": ["#sciencediscoveries", "#howthingswork", "#scienceexplained", "#spaceexploration", "#sciencefacts"],
    },
    "history": {
        "broad": ["#history", "#culture", "#heritage", "#past", "#worldhistory", "#learning"],
        "niche": ["#ancienthistory", "#civilization", "#war", "#medieval", "#renaissance", "#coldwar", "#archaeology", "#historical", "#documentary", "#mythology"],
        "trending": ["#history", "#ancient", "#documentary", "#ww2", "#coldwar"],
        "longtail": ["#historyfacts", "#ancientcivilizations", "#historicalevents", "#worldhistoryfacts", "#historyuncovered"],
    },
    "psychology": {
        "broad": ["#psychology", "#mind", "#brain", "#science", "#behavior", "#mentalhealth"],
        "niche": ["#neuroscience", "#cognitive", "#behavioral", "#personality", "#trauma", "#anxiety", "#depression", "#mindfulness", "#meditation", "#stoicism", "#narcissism", "#attachment"],
        "trending": ["#mentalhealth", "#mindfulness", "#psychology", "#neuroscience", "#selfimprovement"],
        "longtail": ["#psychologyfacts", "#humanbehavior", "#mindmatters", "#brainhealth", "#psychologytips"],
    },
    "motivation": {
        "broad": ["#motivation", "#success", "#mindset", "#goals", "#growth", "#inspiration"],
        "niche": ["#discipline", "#productivity", "#focus", "#habits", "#leadership", "#selfimprovement", "#personaldevelopment", "#timemanagement", "#goalsetting", "#morningroutine"],
        "trending": ["#motivation", "#success", "#mindset", "#productivity", "#selfimprovement"],
        "longtail": ["#staymotivated", "#successmindset", "#dailyhabits", "#personaldevelopment", "#growthmindset"],
    },
    "education": {
        "broad": ["#education", "#learning", "#knowledge", "#study", "#skills", "#onlinelearning"],
        "niche": ["#deepdive", "#tutorial", "#guide", "#explained", "#howto", "#elearning", "#personalgrowth", "#criticalthinking", "#lifelonglearning", "#selfeducation"],
        "trending": ["#onlinelearning", "#education", "#howto", "#tutorial", "#skills"],
        "longtail": ["#lifelonglearning", "#selfeducation", "#learnnewskills", "#knowledgeispower", "#studygram"],
    },
    "philosophy": {
        "broad": ["#philosophy", "#wisdom", "#life", "#thinking", "#education", "#knowledge"],
        "niche": ["#stoicism", "#existence", "#consciousness", "#ethics", "#logic", "#meaning", "#plato", "#aristotle", "#nietzsche", "#freewill", "#determinism", "#metaphysics"],
        "trending": ["#philosophy", "#stoicism", "#wisdom", "#mindfulness", "#lifeadvice"],
        "longtail": ["#philosophical", "#stoicwisdom", "#lifephilosophy", "#thinkdeeper", "#ancientwisdom"],
    },
    "health": {
        "broad": ["#health", "#wellness", "#fitness", "#nutrition", "#healthyliving", "#science"],
        "niche": ["#longevity", "#sleep", "#meditation", "#exercise", "#diet", "#vitamins", "#guthealth", "#immunity", "#hormones", "#inflammation", "#aging", "#supplements"],
        "trending": ["#longevity", "#guthealth", "#sleep", "#meditation", "#healthylifestyle"],
        "longtail": ["#healthtips", "#wellnessjourney", "#healthyhabits", "#nutritiontips", "#sciencebasedhealth"],
    },
    "business": {
        "broad": ["#business", "#entrepreneur", "#marketing", "#leadership", "#success", "#strategy"],
        "niche": ["#startup", "#sales", "#management", "#revenue", "#growth", "#branding", "#seo", "#venturecapital", "#b2b", "#b2c", "#funnel", "#conversion"],
        "trending": ["#entrepreneurship", "#startup", "#marketing", "#leadership", "#businessgrowth"],
        "longtail": ["#businesstips", "#entrepreneurial", "#startupadvice", "#businessstrategy", "#growthhacking"],
    },
    "general": {
        "broad": ["#education", "#knowledge", "#learning", "#deepdive", "#documentary", "#explained"],
        "niche": ["#evergreen", "#educationalcontent", "#personalgrowth", "#criticalthinking", "#lifelonglearning", "#intellectual", "#curiosity", "#wisdom"],
        "trending": ["#educational", "#documentary", "#deepdive", "#explained", "#knowledge"],
        "longtail": ["#contentthatmatters", "#learnsomethingnew", "#qualitycontent", "#educationalvideo", "#neverstoplearning"],
    },
}


def build_description(plan, hook, duration_sec):
    """Build SEO-optimised YouTube description with chapters.

    Args:
        plan: full plan dict {title, description, chapters, tags, comment, ...}
        hook: hook text
        duration_sec: total video duration

    Returns:
        dict with {description, hashtags, chapters_text, full_text}
    """
    title = plan.get("title", "")
    chapters = plan.get("chapters", [])
    tags = plan.get("tags", [])
    comment_q = plan.get("comment", "")

    cat = _classify_topic(title, hook)
    hashtags = _HASHTAG_POOL.get(cat, _HASHTAG_POOL["general"])
    rng = random.Random(hashlib.md5((title + str(datetime.date.today())).encode()).hexdigest())
    selected_tags = rng.sample(hashtags, min(8, len(hashtags)))
    if tags:
        custom = ["#" + t.replace(" ", "").lower() for t in tags[:4]]
        selected_tags = custom + [t for t in selected_tags if t not in custom]
    hashtag_str = " ".join(selected_tags[:10])

    chapter_lines = []
    for ch in chapters:
        ts = _fmt_ts(ch.get("timestamp_sec", 0))
        chapter_lines.append(f"{ts} - {ch['title']}")

    chapter_text = "\n".join(chapter_lines)

    summary = plan.get("description", "").strip()
    if not summary:
        summary = f"A deep dive into {title}."

    desc_parts = [summary.strip()]
    desc_parts.append("")
    desc_parts.append("")
    desc_parts.append("")

    if comment_q:
        desc_parts.append(f"\u23e9 {comment_q}")
        desc_parts.append("")

    if chapter_lines:
        desc_parts.append("")
        desc_parts.append(chapter_text)
        desc_parts.append("")

    desc_parts.append("")
    desc_parts.append(hashtag_str)

    full = "\n".join(desc_parts)

    return {
        "description": full,
        "hashtags": selected_tags,
        "chapters_text": chapter_text,
        "full_text": full,
    }


def build_transcript(chapters, scene_words, chapter_durations):
    """Build full timestamped transcript with chapter markers.

    Args:
        chapters: list of {title, timestamp_sec, scenes}
        scene_words: flat list of [(word, start, end), ...] per scene
        chapter_durations: list of lists of durations per scene per chapter

    Returns:
        dict with {plain_text, srt, markdown}
    """
    plain_lines = []
    srt_entries = []
    md_lines = []

    srt_idx = 1
    global_offset = 0.0
    word_idx = 0

    for ci, ch in enumerate(chapters):
        ch_durs = chapter_durations[ci] if ci < len(chapter_durations) else []
        ch_scenes = ch.get("scenes", [])

        ch_ts = _fmt_ts(ch.get("timestamp_sec", 0))
        plain_lines.append(f"\n[{ch['title']}]")
        md_lines.append(f"\n## {ch['title']}")

        scene_offset = 0.0
        for si in range(len(ch_scenes)):
            dur = ch_durs[si] if si < len(ch_durs) else 5.0
            words = scene_words[word_idx] if word_idx < len(scene_words) else []
            word_idx += 1

            if words:
                sentence_text = " ".join(w[0] for w in words)
                plain_lines.append(f"  {sentence_text}")
                md_lines.append(f"\n{sentence_text}")

                for w in words:
                    raw = w[0].strip()
                    if not raw:
                        continue
                    s_start = global_offset + scene_offset + w[1]
                    s_end = global_offset + scene_offset + w[2]
                    if s_end - s_start < 0.3:
                        s_end = s_start + 0.3
                    srt_entries.append(
                        f"{srt_idx}\n"
                        f"{_fmt_srt_ts(s_start)} --> {_fmt_srt_ts(s_end)}\n"
                        f"{raw}\n"
                    )
                    srt_idx += 1

            scene_offset += dur

        global_offset += sum(ch_durs)

    srt_content = "\n".join(srt_entries)

    title_name = os.environ.get("CHANNEL_NAME", "Deep Dive Channel")
    md_header = (
        f"# {title_name}\n\n"
        f"*Published: {datetime.date.today().strftime('%B %d, %Y')}*\n\n"
    )
    md_content = md_header + "\n".join(md_lines)

    return {
        "plain_text": "\n".join(plain_lines).strip(),
        "srt": srt_content,
        "markdown": md_content,
    }


def write_all(plan, hook, duration_sec, chapters, scene_words,
              chapter_durations, output_dir="output_long"):
    """Generate and write all description and transcript files.

    Writes:
      - description.txt (YouTube description with chapters + hashtags)
      - transcript.txt (timestamped plain text transcript)
      - transcript.srt (subtitle file)
      - transcript.md (markdown blog post)
      - chapters.txt (chapter list for metadata)

    Returns dict of paths.
    """
    os.makedirs(output_dir, exist_ok=True)

    desc_data = build_description(plan, hook, duration_sec)
    trans_data = build_transcript(chapters, scene_words, chapter_durations)

    paths = {}

    desc_path = os.path.join(output_dir, "description.txt")
    with open(desc_path, "w", encoding="utf-8") as f:
        f.write(desc_data["full_text"])
    paths["description"] = desc_path
    print(f"  description written: {desc_path}", flush=True)

    trans_path = os.path.join(output_dir, "transcript.txt")
    with open(trans_path, "w", encoding="utf-8") as f:
        f.write(trans_data["plain_text"])
    paths["transcript"] = trans_path
    print(f"  transcript written: {trans_path}", flush=True)

    srt_path = os.path.join(output_dir, "transcript.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(trans_data["srt"])
    paths["srt"] = srt_path
    print(f"  SRT captions written: {srt_path}", flush=True)

    blog_path = os.path.join(output_dir, "transcript.md")
    with open(blog_path, "w", encoding="utf-8") as f:
        f.write(trans_data["markdown"])
    paths["blog"] = blog_path
    print(f"  markdown blog written: {blog_path}", flush=True)

    chapters_path = os.path.join(output_dir, "chapters.txt")
    ch_lines = []
    for ch in chapters:
        ts = _fmt_ts(ch.get("timestamp_sec", 0))
        ch_lines.append(f"{ts} - {ch['title']}")
    with open(chapters_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ch_lines))
    paths["chapters"] = chapters_path
    print(f"  chapters written: {chapters_path}", flush=True)

    return paths


import random
