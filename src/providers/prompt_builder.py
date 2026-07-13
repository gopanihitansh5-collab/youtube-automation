"""Advanced prompt diversity engine for YouTube Shorts scripts.

Every video is structurally unique across 18+ independent dimensions:
format, narrative arc, pacing profile, voice, tone, emotional arc,
pronoun perspective, language complexity, hook style, CTA style,
rhetorical devices, visual density, and per-scene energy diversity.

A compatibility matrix weights which combinations are natural (e.g.
mysterious voice fits myth-busting) and anti-repetition tracking avoids
reusing the same combo across recent runs.
"""

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

# -- ANTI-REPETITION --
_MAX_MEMORY = 200

_MEMORY_FILES = {
    "combo": Path("output/.prompt_history.json"),
    "hooks": Path("output/.used_hooks.json"),
    "narrations": Path("output/.used_narrations.json"),
    "keywords": Path("output/.used_keywords.json"),
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


# -- 8 NARRATIVE ARCS --
NARRATIVE_ARCS = [
    {
        "name": "hero_journey",
        "description": "The classic hero arc -- status quo, conflict, struggle, transformation, resolution",
        "scene_energy": ["calm", "rising", "peak", "falling", "resolution"],
        "suitability": {"storytelling": 0.95, "behind_the_scenes": 0.8, "timeline": 0.85},
    },
    {
        "name": "mystery_box",
        "description": "Open with a puzzle or question, layer clues, reveal answer at the end",
        "scene_energy": ["mysterious", "curious", "building", "intense", "reveal"],
        "suitability": {"big_reveal": 0.95, "myth_busting": 0.85, "psychological": 0.8},
    },
    {
        "name": "problem_solution",
        "description": "State a painful problem, explore why it hurts, present the solution",
        "scene_energy": ["frustrating", "sympathetic", "hopeful", "empowering", "action"],
        "suitability": {"step_by_step": 0.95, "mistakes": 0.9, "warning": 0.85},
    },
    {
        "name": "before_after",
        "description": "Show the old way vs the new way, contrast benefits, call to action",
        "scene_energy": ["frustrating", "revelation", "hopeful", "exciting", "triumphant"],
        "suitability": {"comparison": 0.95, "listicle": 0.7, "data_driven": 0.75},
    },
    {
        "name": "cause_effect",
        "description": "Explain root causes, trace their effects, show the chain reaction",
        "scene_energy": ["analytical", "building", "intense", "sobering", "hopeful"],
        "suitability": {"psychological": 0.9, "data_driven": 0.9, "warning": 0.8},
    },
    {
        "name": "countdown",
        "description": "Build tension through numbered reveals from least to most impactful",
        "scene_energy": ["intriguing", "rising", "high", "intense", "climactic"],
        "suitability": {"listicle": 0.9, "quick_tips": 0.85, "mistakes": 0.8},
    },
    {
        "name": "twist",
        "description": "Set up a conventional understanding, then flip it with an unexpected twist",
        "scene_energy": ["conventional", "building", "conventional", "shift", "mindblown"],
        "suitability": {"controversial": 0.95, "myth_busting": 0.9, "big_reveal": 0.9},
    },
    {
        "name": "journey",
        "description": "Take the viewer on a chronological or spatial journey of discovery",
        "scene_energy": ["curious", "wonder", "exploration", "awe", "reflection"],
        "suitability": {"timeline": 0.95, "behind_the_scenes": 0.9, "storytelling": 0.85},
    },
]

# -- 16 SCRIPT FORMATS --
SCRIPT_FORMATS = [
    {"name": "listicle",          "structure": "Numbered list of surprising facts or tips about {topic}", "scene_range": (5, 7)},
    {"name": "myth_busting",      "structure": "Common myth about {topic}, then the reality behind it", "scene_range": (4, 6)},
    {"name": "storytelling",      "structure": "Short narrative story (personal, historical, or case study) about {topic}", "scene_range": (5, 7)},
    {"name": "comparison",        "structure": "Side-by-side or before-after comparison about {topic}", "scene_range": (5, 7)},
    {"name": "big_reveal",        "structure": "Slow build-up to a shocking or surprising revelation about {topic}", "scene_range": (5, 7)},
    {"name": "step_by_step",      "structure": "Step-by-step actionable guide or tutorial about {topic}", "scene_range": (5, 8)},
    {"name": "controversial",     "structure": "Hot take or unpopular opinion about {topic}", "scene_range": (4, 6)},
    {"name": "future_gazing",     "structure": "Prediction about the future of {topic} over the next X years", "scene_range": (5, 7)},
    {"name": "psychological",     "structure": "Psychology-backed insights about why {topic} works or matters", "scene_range": (4, 6)},
    {"name": "warning",           "structure": "Warning about common mistakes, risks, or dangers related to {topic}", "scene_range": (4, 6)},
    {"name": "behind_the_scenes", "structure": "Behind-the-scenes look at how {topic} works or is made", "scene_range": (5, 7)},
    {"name": "challenge",         "structure": "Challenge or experiment related to {topic} with surprising results", "scene_range": (5, 7)},
    {"name": "data_driven",       "structure": "Statistics, data points, and research findings about {topic}", "scene_range": (5, 7)},
    {"name": "mistakes",          "structure": "X biggest mistakes people make with {topic} and how to avoid them", "scene_range": (5, 7)},
    {"name": "timeline",          "structure": "Journey or evolution of {topic} over time from past to present", "scene_range": (5, 7)},
    {"name": "quick_tips",        "structure": "Rapid-fire tips about {topic} delivered fast and punchy", "scene_range": (5, 8)},
]

# -- 6 PACING PROFILES --
PACING_PROFILES = [
    {"name": "rapid_fire",  "description": "Very fast cuts, short scenes (5-7s each), high energy throughout"},
    {"name": "slow_burn",   "description": "Deliberate, slow scenes (9-12s each), building tension gradually"},
    {"name": "rhythmic",    "description": "Alternating fast and slow scenes, like a wave pattern"},
    {"name": "accelerando", "description": "Starts slow, gets progressively faster and more intense"},
    {"name": "explosive",   "description": "Opens with a bang, maintains high energy, ends with a punch"},
    {"name": "balanced",    "description": "Even pacing throughout, steady 7-9s per scene"},
]

# -- 12 NARRATIVE VOICES --
VOICES = [
    {"name": "authoritative",   "style": "confident expert-level tone that speaks with certainty",          "persona": "You are a recognized authority in this field"},
    {"name": "curious",         "style": "exploratory, discovering together with the viewer",               "persona": "You are genuinely fascinated by this topic"},
    {"name": "urgent",          "style": "fast-paced high-energy urgency that demands attention",            "persona": "The viewer needs to know this RIGHT NOW"},
    {"name": "conversational",  "style": "relaxed friendly chat like talking to a close friend",            "persona": "You are a friend sharing something interesting over coffee"},
    {"name": "humorous",        "style": "light funny tone with witty observations and playful energy",     "persona": "You find the humor in everything and make people smile"},
    {"name": "dramatic",        "style": "cinematic intense delivery with pauses and building tension",     "persona": "This is an important story that needs dramatic impact"},
    {"name": "empathetic",      "style": "warm understanding tone that validates the viewer struggles",     "persona": "You deeply understand the viewer challenges"},
    {"name": "mysterious",      "style": "intriguing secretive tone hinting at hidden knowledge",           "persona": "You discovered something few people know"},
    {"name": "direct",          "style": "blunt no-nonsense straight to the point with zero fluff",        "persona": "You waste no words and deliver pure value"},
    {"name": "inspirational",   "style": "uplifting motivating tone with powerful empowering statements",   "persona": "Your mission is to lift the viewer up"},
    {"name": "skeptical",       "style": "questioning, challenging assumptions, devil's advocate",          "persona": "You question everything and demand evidence"},
    {"name": "storyteller",     "style": "lyrical vivid narrative style with rich sensory language",        "persona": "You paint pictures with words and transport the viewer"},
]

# -- 10 EMOTIONAL TONES --
TONES = [
    "inspirational", "educational", "entertaining", "urgent",
    "contemplative", "energetic", "calm", "intense",
    "optimistic", "skeptical",
]

# -- 6 LANGUAGE COMPLEXITY LEVELS --
LANG_LEVELS = [
    {"name": "simple",      "desc": "Short simple sentences. Grade 5 level vocabulary. Easy to follow.",           "avg_words_per_sentence": 8},
    {"name": "conversational", "desc": "Everyday speech patterns. Contractions. Natural flow.",                    "avg_words_per_sentence": 12},
    {"name": "engaging",    "desc": "Varied sentence length. Descriptive but accessible. Grade 8 level.",          "avg_words_per_sentence": 14},
    {"name": "sophisticated", "desc": "Rich vocabulary. Complex sentences with clauses. Grade 10 level.",          "avg_words_per_sentence": 18},
    {"name": "professional", "desc": "Polished articulate speech. Industry terminology where relevant.",           "avg_words_per_sentence": 16},
    {"name": "poetic",      "desc": "Rhythmic flowing language. Metaphors and vivid imagery. Artistic delivery.",  "avg_words_per_sentence": 14},
]

# -- 5 PRONOUN PERSPECTIVES --
PRONOUN_STYLES = [
    {"name": "first_person_singular", "pronouns": "I, me, my, mine",     "example": "I discovered something fascinating about {topic}"},
    {"name": "second_person",         "pronouns": "you, your, yours",     "example": "You have been doing {topic} wrong your whole life"},
    {"name": "first_person_plural",   "pronouns": "we, us, our",         "example": "We all struggle with {topic} more than we admit"},
    {"name": "third_person",          "pronouns": "they, them, people",  "example": "Most people overlook the most important part of {topic}"},
    {"name": "imperative",            "pronouns": "implied you (commands)","example": "Stop making these {topic} mistakes starting today"},
]

# -- 10 HOOK STYLES --
HOOK_STYLES = [
    "question", "bold_claim", "surprising_stat", "story_opener",
    "myth_debunk", "relatable", "challenge", "curiosity_gap",
    "direct_address", "visual_tease",
]

# -- 10 CTA STYLES --
CTA_STYLES = ["follow", "comment", "share", "save", "try", "opinion", "next", "reflect", "tag", "subscribe"]

# -- 12 RHETORICAL DEVICES --
RHETORICAL_DEVICES = [
    "rhetorical question at scene end",
    "rule of three (list three things)",
    "metaphor or analogy for complex ideas",
    "hypophora (ask a question then answer it)",
    "epistrophe (repeat the same word at end of consecutive sentences)",
    "anaphora (repeat the same word at start of consecutive sentences)",
    "direct quote from an expert or study",
    "short punchy one-word sentence for emphasis",
    "contrast (not X, but Y)",
    "personification (giving human qualities to abstract concepts)",
    "parallelism (similar grammatical structure in consecutive sentences)",
    "hyperbole for dramatic emphasis",
]

# -- VISUAL DENSITY LEVELS --
VISUAL_DENSITIES = [
    {"name": "minimalist",   "desc": "Clean simple visuals. One clear subject. Lots of negative space."},
    {"name": "balanced",     "desc": "Well-composed frame with a main subject and supporting context."},
    {"name": "rich",         "desc": "Detailed layered scene with multiple elements of interest."},
    {"name": "maximalist",   "desc": "Dense chaotic frame packed with details, texture, and movement."},
]

# -- EMOTIONAL ARC TEMPLATES --
EMOTIONAL_ARCS = [
    ["curiosity", "surprise", "understanding", "determination"],
    ["confusion", "intrigue", "clarity", "excitement"],
    ["concern", "worry", "relief", "motivation"],
    ["boredom", "interest", "fascination", "awe"],
    ["skepticism", "doubt", "acceptance", "enthusiasm"],
    ["frustration", "validation", "hope", "action"],
    ["mystery", "tension", "revelation", "satisfaction"],
]

# -- COMPATIBILITY MATRIX --
_VOICE_FORMAT_WEIGHTS = {
    ("mysterious", "myth_busting"): 0.95,
    ("mysterious", "big_reveal"): 0.95,
    ("mysterious", "future_gazing"): 0.85,
    ("authoritative", "data_driven"): 0.95,
    ("authoritative", "warning"): 0.9,
    ("authoritative", "step_by_step"): 0.85,
    ("urgent", "warning"): 0.95,
    ("urgent", "mistakes"): 0.9,
    ("urgent", "controversial"): 0.85,
    ("humorous", "listicle"): 0.85,
    ("humorous", "quick_tips"): 0.85,
    ("humorous", "challenge"): 0.8,
    ("storyteller", "storytelling"): 0.95,
    ("storyteller", "timeline"): 0.9,
    ("storyteller", "behind_the_scenes"): 0.85,
    ("skeptical", "myth_busting"): 0.9,
    ("skeptical", "controversial"): 0.9,
    ("skeptical", "data_driven"): 0.85,
    ("inspirational", "challenge"): 0.9,
    ("inspirational", "future_gazing"): 0.85,
    ("empathetic", "warning"): 0.85,
    ("empathetic", "mistakes"): 0.85,
    ("direct", "step_by_step"): 0.9,
    ("direct", "quick_tips"): 0.85,
    ("curious", "psychological"): 0.9,
    ("curious", "behind_the_scenes"): 0.85,
}

_TONE_FORMAT_WEIGHTS = {
    ("urgent", "warning"): 0.95,
    ("urgent", "mistakes"): 0.9,
    ("intense", "controversial"): 0.9,
    ("intense", "big_reveal"): 0.85,
    ("calm", "psychological"): 0.85,
    ("calm", "behind_the_scenes"): 0.85,
    ("entertaining", "listicle"): 0.85,
    ("entertaining", "quick_tips"): 0.85,
    ("educational", "step_by_step"): 0.95,
    ("educational", "data_driven"): 0.9,
    ("educational", "myth_busting"): 0.85,
    ("inspirational", "storytelling"): 0.85,
    ("inspirational", "future_gazing"): 0.85,
    ("skeptical", "myth_busting"): 0.9,
    ("energetic", "challenge"): 0.9,
    ("contemplative", "psychological"): 0.9,
}

# -- OFFLINE TEMPLATE POOLS --
_CRYPTO_OPENERS = [
    "Here is what the on-chain data actually says about {t}.",
    "Most crypto traders overlook this critical detail about {t}.",
    "Let me show you what the whales are doing with {t} right now.",
    "The smart money already knows this about {t}. Now you will too.",
    "There is one metric for {t} that changes how you see the entire market.",
]
_CRYPTO_MIDS = [
    "Here is what the transaction history reveals about {t}.",
    "The wallet activity behind {t} tells a very different story.",
    "This is the part of {t} that most analysts miss completely.",
    "When you look at the tokenomics of {t}, the picture becomes clear.",
    "The network data around {t} confirms what smart money already knows.",
    "Here is how the market makers are positioning around {t}.",
]

_OFFLINE_FORMAT_TEMPLATES = {
    "listicle": {
        "openers": [
            "Here are X surprising facts about {t} that will change how you think.",
            "You won't believe number X on this list about {t}.",
            "I have compiled X things about {t} that nobody talks about.",
        ],
        "crypto_openers": _CRYPTO_OPENERS,
        "mid_scenes": [
            "Number {n}: {t} has a hidden side most people never see.",
            "Number {n}: this fact about {t} surprised even the experts.",
            "Number {n}: what they don't teach you about {t} in school.",
        ],
        "crypto_mids": _CRYPTO_MIDS,
    },
    "myth_busting": {
        "openers": [
            "There is a common myth about {t} that simply is not true.",
            "Everything you think you know about {t} needs a second look.",
            "Let me bust the biggest myth about {t} once and for all.",
        ],
        "crypto_openers": [
            "There is a dangerous myth about {t} that is costing traders money.",
            "Most people believe the wrong narrative about {t}.",
            "Let me debunk what everyone gets wrong about {t}.",
        ],
        "mid_scenes": [
            "Here is what people get wrong about {t}.",
            "The real story behind {t} is very different from what you heard.",
            "Studies show that this belief about {t} is completely backwards.",
        ],
        "crypto_mids": _CRYPTO_MIDS,
    },
    "storytelling": {
        "openers": [
            "Let me tell you a story about {t} that changed my perspective forever.",
            "I remember the first time I encountered {t} in a completely unexpected way.",
            "There is a story about {t} that most people have never heard.",
        ],
        "crypto_openers": [
            "The story of {t} begins with a single transaction that nobody noticed.",
            "Let me tell you about what happened behind the scenes with {t}.",
            "The origin story of {t} reveals more than any whitepaper ever could.",
        ],
        "mid_scenes": [
            "What happened next completely changed the course of {t}.",
            "This moment is where everything about {t} shifted.",
            "The turning point in this {t} story came from an unlikely source.",
        ],
        "crypto_mids": _CRYPTO_MIDS,
    },
    "comparison": {
        "openers": [
            "There are two ways to approach {t}, and only one of them works.",
            "The difference between success and failure in {t} comes down to one thing.",
            "Let me compare the old approach to {t} with what actually works today.",
        ],
        "crypto_openers": [
            "There are two sides to {t} and most people only see one.",
            "The difference between profiting and losing on {t} is one key factor.",
            "Let me compare how retail and smart money approach {t} differently.",
        ],
        "mid_scenes": [
            "Here is how the two approaches to {t} differ in practice.",
            "The gap between method A and method B in {t} is bigger than you think.",
            "When you compare the results of both {t} approaches, the data is clear.",
        ],
        "crypto_mids": _CRYPTO_MIDS,
    },
}

_PERFORMER_TEMPLATES = [
    {"name": "expert", "style": "cited specialist", "intro": "According to experts in {t},"},
    {"name": "researcher", "style": "study reference", "intro": "Research published on {t} shows that"},
    {"name": "practitioner", "style": "hands-on experience", "intro": "From years of working with {t},"},
    {"name": "observer", "style": "cultural commentator", "intro": "If you look closely at {t},"},
    {"name": "contrarian", "style": "devil's advocate", "intro": "But here is what most people get wrong about {t},"},
]


# -- TOPIC CLASSIFIER --
_TOPIC_CATEGORIES = {
    "tech":         ["ai", "artificial intelligence", "technology", "software", "coding", "programming",
                     "app", "startup", "silicon valley", "computer", "digital", "internet", "robot",
                     "automation", "cyber", "data", "algorithm", "blockchain", "cloud", "saas"],
    "crypto":       ["crypto", "bitcoin", "blockchain", "ethereum", "defi", "nft", "token", "coin",
                     "wallet", "mining", "staking", "airdrop", "dao", "web3", "layer 2", "layer2",
                     "rollup", "exchange", "altcoin", "memecoin", "solana", "bitcoin halving",
                     "liquidity", "yield", "trading", "tokenomics", "smart contract",
                     "decentralized", "fork", "bridge", "oracle", "zk", "zero knowledge",
                     "proof of stake", "proof of work", "consensus", "validator", "node",
                     "gas fee", "flash loan", "mev", "cold wallet", "hardware wallet",
                     "seed phrase", "public key", "private key", "on chain", "on-chain",
                     "whale", "pump", "dump", "rug pull", "bear market", "bull market"],
    "finance":      ["money", "invest", "stock", "real estate", "passive income",
                     "rich", "wealth", "financial", "retire", "saving", "budget", "debt", "credit",
                     "loan", "mortgage", "tax", "economy", "recession", "inflation"],
    "motivation":   ["motivation", "success", "mindset", "habit", "discipline", "goal", "growth",
                     "improve", "better", "change", "life hack", "productivity", "focus",
                     "confidence", "self", "inspiration", "routine", "morning"],
    "science":      ["science", "physics", "chemistry", "biology", "space", "universe", "quantum",
                     "experiment", "discovery", "research", "study", "evolution", "dna",
                     "gene", "particle", "gravity", "energy", "atom", "nasa", "mars"],
    "lifestyle":    ["lifestyle", "travel", "food", "cooking", "recipe", "fashion", "beauty",
                     "home", "organization", "minimalism", "declutter", "diy", "craft",
                     "pet", "dog", "cat", "garden", "plant", "interior", "design"],
    "psychology":   ["psychology", "brain", "mind", "behavior", "emotion", "relationship",
                     "personality", "trauma", "therapy", "anxiety", "depression", "stress",
                     "narcissist", "attachment", "cognitive", "bias", "decision"],
    "business":     ["business", "entrepreneur", "marketing", "sales", "leadership", "management",
                     "strategy", "revenue", "growth", "brand", "customer", "network",
                     "b2b", "b2c", "funnel", "conversion", "seo", "advertising"],
    "entertainment": ["movie", "show", "netflix", "game", "gaming", "music", "celebrity",
                      "viral", "tiktok", "youtube", "influencer", "stream", "anime",
                      "comic", "marvel", "dc", "hollywood", "song", "album"],
    "philosophy":   ["philosophy", "meaning", "purpose", "existence", "consciousness",
                     "reality", "truth", "ethics", "moral", "logic", "reason",
                     "stoic", "nietzsche", "existential", "free will", "god", "religion"],
}

_SENSITIVE_TOPICS = [
    "suicide", "death", "addiction", "abuse", "trauma", "violence",
    "war", "terrorism", "disease", "cancer", "terminal",
]


def _classify_topic(topic):
    t = topic.lower()
    category = "general"
    best_score = 0
    for cat, keywords in _TOPIC_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in t)
        if score > best_score:
            best_score = score
            category = cat
    is_sensitive = any(kw in t for kw in _SENSITIVE_TOPICS)
    return category, is_sensitive


# -- KEYWORD DRIFT / ANGLE EXPANSION --
_ANGLE_TEMPLATES = [
    "the hidden truth about {t}",
    "why {t} matters more than you think",
    "the dark side of {t}",
    "how {t} is changing everything",
    "what they don't tell you about {t}",
    "the future of {t}",
    "why most people fail at {t}",
    "the science behind {t}",
    "the history of {t} nobody knows",
    "how to master {t} starting from zero",
    "the biggest myths about {t}",
    "what happens when {t} goes wrong",
    "the psychology of {t} explained",
    "how {t} affects your daily life",
    "the untold story of {t}",
    "the on-chain data that predicts {t}",
    "what the whales know about {t}",
    "why {t} is different this cycle",
    "the tokenomics trap in {t}",
    "what the smart money sees in {t}",
    "how insiders evaluate {t}",
    "the hidden ledger behind {t}",
]

_POWER_WORDS = [
    "shocking", "secret", "ultimate", "essential", "hidden", "proven",
    "rare", "critical", "powerful", "simple", "genius", "brutal",
    "unexpected", "controversial", "mind-blowing", "game-changing",
    "life-saving", "dangerous", "brilliant", "stupid", "illegal",
    "forbidden", "forgotten", "impossible", "unstoppable",
]


def _drift_topic(topic, rng):
    t = topic.strip().rstrip(".!?").lower()
    template = rng.choice(_ANGLE_TEMPLATES)
    angle = template.replace("{t}", t).capitalize()
    if rng.random() < 0.3:
        pw = rng.choice(_POWER_WORDS)
        angle = f"The {pw} Truth About {t.title()}"
    return angle


# -- VIRAL HOOK GENERATOR --
_HOOK_TEMPLATES_BY_STYLE = {
    "question": [
        "Did you know {detail}?",
        "What if {provocation}?",
        "Why does {curiosity} happen?",
        "Are you making this {topic} mistake?",
        "Can you guess what {reveal}?",
    ],
    "bold_claim": [
        "This {topic} secret changes everything.",
        "Nothing prepares you for this {topic} truth.",
        "Here is why {topic} will never be the same.",
        "The real reason {topic} matters.",
        "This is the most important {topic} lesson you will ever learn.",
    ],
    "surprising_stat": [
        "{percent}% of people do not know this about {topic}.",
        "Studies show {finding} about {topic}.",
        "The number behind {topic} will shock you.",
        "Here is what {percent}% of {topic} experts get wrong.",
    ],
    "story_opener": [
        "I discovered something about {topic} that changed my mind forever.",
        "Let me tell you a {topic} story you have not heard before.",
        "The day I learned the truth about {topic}.",
        "Here is what happened when I tried {topic} for the first time.",
    ],
    "myth_debunk": [
        "Everything you know about {topic} is a lie.",
        "Stop believing this common {topic} myth.",
        "Here is the truth about {topic} they do not want you to know.",
        "The biggest {topic} myth holding you back.",
    ],
    "relatable": [
        "If you struggle with {topic}, this is for you.",
        "We have all been there with {topic}.",
        "You are not alone in your {topic} struggle.",
        "This {topic} problem feels impossible, but here is the fix.",
    ],
    "challenge": [
        "I challenge you to try this {topic} method for 7 days.",
        "Try this one {topic} change and see what happens.",
        "Here is a {topic} challenge that will change your perspective.",
    ],
    "curiosity_gap": [
        "The secret about {topic} nobody talks about.",
        "Here is why {topic} is not what you think it is.",
        "There is one thing about {topic} that changes everything.",
        "What they are not telling you about {topic}.",
    ],
    "direct_address": [
        "Hey, if you care about {topic}, watch this.",
        "This is your sign to finally understand {topic}.",
        "You need to hear this if you want to master {topic}.",
    ],
    "visual_tease": [
        "Watch this until the end. It is worth it.",
        "You will not believe what {topic} looks like up close.",
        "The visual of {topic} you have to see to believe.",
    ],
}

_HOOK_DETAIL_FILLERS = {
    "crypto":      {"detail": "90% of crypto traders lose money", "provocation": "your portfolio is down because of this one thing", "curiosity": "whales move the market before you wake up", "finding": "80% of airdrop farmers get flagged as sybils", "reveal": "smart money is buying while retail sells", "percent": "90", "topic": "crypto"},
    "tech":        {"detail": "your phone is listening to you", "provocation": "AI could replace your job in 5 years", "curiosity": "your internet slows down", "finding": "90% of startups fail in the first year", "reveal": "happens when you delete your data", "percent": "97", "topic": "technology"},
    "health":      {"detail": "your sleep position affects your organs", "provocation": "everything you know about nutrition is wrong", "curiosity": "you crave sugar at night", "finding": "80% of people are deficient in this vitamin", "reveal": "happens to your body after 30 days without sugar", "percent": "85", "topic": "health"},
    "finance":     {"detail": "most billionaires share this one habit", "provocation": "your bank account is losing value right now", "curiosity": "the rich get richer", "finding": "70% of lottery winners go broke", "reveal": "the wealthy know about money", "percent": "90", "topic": "money"},
    "motivation":  {"detail": "your morning routine is ruining your day", "provocation": "motivation is a trap", "curiosity": "some people achieve more before 8am", "finding": "95% of New Year resolutions fail by February", "reveal": "separates successful people from the rest", "percent": "95", "topic": "success"},
    "science":     {"detail": "your brain is processing information you cannot see", "provocation": "time does not exist the way you think", "curiosity": "quantum particles behave differently when observed", "finding": "99% of the universe is invisible", "reveal": "scientists just discovered about space", "percent": "99", "topic": "science"},
    "psychology":  {"detail": "your childhood is shaping your decisions right now", "provocation": "you are not as rational as you think", "curiosity": "you remember things that never happened", "finding": "93% of communication is nonverbal", "reveal": "your brain hides from you", "percent": "93", "topic": "psychology"},
    "lifestyle":   {"detail": "minimalism saves more than just money", "provocation": "your home is making you stressed", "curiosity": "some people live happier with less", "finding": "80% of household items are never used", "reveal": "a clutter-free life does to your mind", "percent": "80", "topic": "lifestyle"},
    "business":    {"detail": "most successful businesses started during a recession", "provocation": "your business model is already outdated", "curiosity": "some companies grow during economic downturns", "finding": "75% of venture-backed startups never return cash", "reveal": "separates unicorn startups from the rest", "percent": "75", "topic": "business"},
    "general":     {"detail": "this changes everything", "provocation": "everything you thought was true needs rethinking", "curiosity": "this works the way it does", "finding": "most people overlook this critical factor", "reveal": "nobody tells you about this", "percent": "87", "topic": "this"},
}

_HOOK_POWER_PREFIXES = ["\U0001f525 ", "\u26a1 ", "\U0001f6a8 ", "\U0001f4a1 ", "\U0001f440 ", ""]


def _generate_hook(hook_style, topic, rng):
    cat, _ = _classify_topic(topic)
    fillers = _HOOK_DETAIL_FILLERS.get(cat, _HOOK_DETAIL_FILLERS["general"])
    templates = _HOOK_TEMPLATES_BY_STYLE.get(hook_style, _HOOK_TEMPLATES_BY_STYLE["bold_claim"])

    t = topic.strip().rstrip(".!?")
    hook = rng.choice(templates)
    hook = hook.replace("{topic}", t.lower())
    hook = hook.replace("{detail}", fillers["detail"])
    hook = hook.replace("{provocation}", fillers["provocation"])
    hook = hook.replace("{curiosity}", fillers["curiosity"])
    hook = hook.replace("{finding}", fillers["finding"])
    hook = hook.replace("{reveal}", fillers["reveal"])
    hook = hook.replace("{percent}", fillers["percent"])

    hook = hook[0].upper() + hook[1:]

    if rng.random() < 0.2:
        prefix = rng.choice(_HOOK_POWER_PREFIXES)
        if prefix:
            hook = prefix + hook

    return hook[:60]


# -- NARRATION DIVERSITY VALIDATOR --
def _validate_narration_diversity(scenes):
    if not scenes:
        return ["no scenes to validate"]

    warnings = []
    narrations = [s.get("narration", "") for s in scenes]
    keywords = [s.get("keyword", "") for s in scenes]

    starts = [n[:10].lower() for n in narrations if n]
    if len(starts) >= 3:
        from collections import Counter
        repeats = {s: count for s, count in Counter(starts).items() if count > 2}
        if repeats:
            warnings.append(f"repetitive scene openings: {repeats}")

    kw_starts = [k[:15].lower() for k in keywords if k]
    if len(kw_starts) >= 3:
        from collections import Counter
        kw_repeats = {k: count for k, count in Counter(kw_starts).items() if count > 1}
        if kw_repeats:
            warnings.append(f"repeated visual keywords: {kw_repeats}")

    all_words = " ".join(narrations).lower().split()
    if all_words:
        from collections import Counter
        word_counts = Counter(all_words)
        common = {w: c for w, c in word_counts.most_common(5) if c > len(scenes) and w not in {"the", "a", "an", "is", "it", "to", "and", "of", "in", "that", "this", "you", "your"}}
        if common:
            warnings.append(f"overused words: {common}")

    return warnings


def _seed(topic):
    raw = (topic + os.environ.get("GITHUB_RUN_ID", "")).encode()
    return int(hashlib.md5(raw).hexdigest()[:8], 16)


def _weighted_choice(rng, choices, weights):
    total = sum(weights)
    r = rng.random() * total
    cumulative = 0
    for choice, weight in zip(choices, weights):
        cumulative += weight
        if r <= cumulative:
            return choice
    return choices[-1]


def _build_weights(rng, items, compatibility, key_name_a, key_a, key_b):
    weights = []
    for item in items:
        weight = compatibility.get((item[key_name_a], key_b), 0.5) if key_name_a else 0.5
        weights.append(weight + rng.uniform(-0.15, 0.15))
    return [max(0.1, w) for w in weights]


# -- VIRAL UNIQUENESS ENGINE --
_VIRAL_PATTERNS = [
    {"name": "curiosity_gap",     "desc": "Create an information gap the viewer MUST close", "trigger": "information deficit"},
    {"name": "pattern_interrupt", "desc": "Break expected patterns to force attention", "trigger": "novelty detection"},
    {"name": "social_proof",      "desc": "Show that millions/experts already agree", "trigger": "herd mentality"},
    {"name": "loss_aversion",     "desc": "Show what they are missing or will lose", "trigger": "fear of regret"},
    {"name": "identity_hook",     "desc": "Make it about who they ARE or want to be", "trigger": "self-concept"},
    {"name": "authority_shortcut","desc": "Cite experts, data, or insider access", "trigger": "trust heuristic"},
    {"name": "scarcity_alert",    "desc": "Limited time, limited access, limited supply", "trigger": "fomo"},
    {"name": "novelty_shock",     "desc": "Show something they have NEVER seen before", "trigger": "surprise response"},
    {"name": "fear_trigger",      "desc": "Highlight a hidden threat or risk", "trigger": "threat detection"},
    {"name": "greed_trigger",     "desc": "Show massive upside they are leaving on table", "trigger": "reward seeking"},
    {"name": "surprise_reveal",   "desc": "Set up an expectation then flip it completely", "trigger": "cognitive reset"},
    {"name": "outrage_spark",     "desc": "Highlight injustice or unfairness in the space", "trigger": "moral outrage"},
    {"name": "hope_injection",    "desc": "Give evidence that things CAN get better", "trigger": "optimism bias"},
    {"name": "mystery_box",       "desc": "Tease a secret that will be revealed later", "trigger": "anticipation"},
    {"name": "validation_hook",   "desc": "Validate a belief they already hold", "trigger": "confirmation bias"},
    {"name": "aspiration_pull",   "desc": "Show the person they could become", "trigger": "ideal self"},
    {"name": "belonging_signal",  "desc": "They are part of an exclusive group", "trigger": "tribe instinct"},
    {"name": "rebellion_call",    "desc": "Challenge the mainstream narrative together", "trigger": "anti-establishment"},
    {"name": "confession",        "desc": "Admit a mistake or reveal a hidden truth", "trigger": "vulnerability trust"},
    {"name": "revelation",        "desc": "Uncover something hidden that changes everything", "trigger": "epiphany"},
]

_SCENE_PURPOSE_POOLS = [
    ["hook", "context", "conflict", "data", "twist", "resolution", "cta"],
    ["hook", "story", "problem", "solution", "proof", "objection", "cta"],
    ["hook", "myth", "reality", "evidence", "implication", "action", "cta"],
    ["hook", "question", "exploration", "discovery", "insight", "application", "cta"],
    ["hook", "contrast", "reveal", "deep_dive", "takeaway", "challenge", "cta"],
    ["hook", "premise", "build", "climax", "fallout", "lesson", "cta"],
    ["hook", "observation", "analysis", "pattern", "prediction", "verdict", "cta"],
    ["hook", "curiosity", "clue", "clue", "reveal", "impact", "cta"],
]


def _is_content_unique(text, key, threshold=0.7):
    hist = _load_memory(key)
    if not hist:
        return True
    words = set(text.lower().split())
    for stored in hist:
        stored_words = set(stored.lower().split())
        if not words or not stored_words:
            continue
        overlap = len(words & stored_words) / max(len(words), len(stored_words))
        if overlap > threshold:
            return False
    return True


def _assign_scene_purposes(rng):
    pool = rng.choice(_SCENE_PURPOSE_POOLS)
    if rng.random() < 0.3:
        cut = rng.randint(1, len(pool) - 2)
        pool = pool[:cut] + pool[cut+1:] + [pool[cut]]
    return pool


def _select_viral_pattern(rng):
    for _ in range(20):
        pattern = rng.choice(_VIRAL_PATTERNS)
        if not _recently_used(f"viral:{pattern['name']}"):
            _save_memory("combo", f"viral:{pattern['name']}")
            return pattern
    return rng.choice(_VIRAL_PATTERNS)


def _build_fingerprint(meta):
    raw = json.dumps(meta, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _ensure_unique_fingerprint(fingerprint):
    hist = _load_memory("fingerprints")
    if fingerprint in hist:
        return False
    _save_memory("fingerprints", fingerprint)
    return True


# -- ENERGY VISUAL POOLS --
_ENERGY_VISUAL_POOLS = {
    "calm": [
        "wide peaceful landscape soft morning light gentle mist quiet atmosphere vertical",
        "close up of water droplets on leaf macro serenity calm natural green tones soft focus vertical",
        "slow motion waves lapping against shore golden sunset warm amber tones peaceful relaxing vertical",
        "minimalist clean dashboard showing steady calm blue lighting professional vertical",
        "slow pan across nature scene peaceful tranquil teal tones vertical",
    ],
    "energetic": [
        "fast motion time-lapse of busy city intersection at night light trails neon glow energetic vibrant vertical",
        "dynamic sports action shot athlete mid-air dramatic peak moment intense bright stadium lighting vertical",
        "explosive colorful powder burst against dark background vibrant particles suspended high energy vertical",
        "fast motion abstract energetic bright vibrant colors dynamic movement vertical",
        "high energy dance performance dramatic lighting colorful stage vertical",
    ],
    "mysterious": [
        "dark silhouette walking through dense fog under single street lamp film noir mysterious atmosphere vertical",
        "close up of ancient book pages turning dim candlelight flickering shadows secret knowledge vertical",
        "abandoned building interior moonlight streaming through broken windows eerie atmospheric vertical",
        "dark server room with blinking lights mysterious aesthetic dim blue red contrast vertical",
        "mysterious foggy forest path at twilight eerie atmospheric vertical",
    ],
    "hopeful": [
        "sunrise breaking over horizon golden rays piercing clouds warm optimistic inspiring new beginning vertical",
        "person standing on mountain peak arms raised victorious breathtaking panorama golden hour glow vertical",
        "butterfly emerging from chrysalis macro extreme close up delicate wings soft natural lighting miracle vertical",
        "sunlight streaming through green leaves hopeful warm golden glow vertical",
        "person looking at horizon with hope sunrise warm colors inspiring vertical",
    ],
    "intense": [
        "low angle lightning storm over dark city skyline dramatic purple clouds electrical energy intense vertical",
        "macro sparks flying from metal grinder bright orange against black workshop dramatic industrial vertical",
        "racing car drifting around corner at night tire smoke neon reflections speed motion blur intense vertical",
        "storm clouds gathering dramatic lightning dark sky intense atmosphere vertical",
        "volcano erupting at night dramatic lava flow intense orange red vertical",
    ],
    "curious": [
        "extreme macro of intricate snowflake crystal melting microscope detail unique patterns wonder vertical",
        "close up of microscope lens exploring tiny organisms blue light scientific discovery fascinating vertical",
        "hands unboxing mysterious package slow reveal dramatic lighting anticipation curiosity peaked vertical",
        "magnifying glass examining intricate details detective investigation curious blue light vertical",
        "scientific experiment bubbling liquid colorful reaction fascinating vertical",
    ],
    "reveal": [
        "curtain pulling back to reveal stunning view dramatic reveal bright light flooding in awe inspiring vertical",
        "fog clearing to show majestic mountain peak mystical atmosphere golden dawn breathtaking vertical",
        "painting being finished final brushstroke masterpiece revealed warm studio lighting artistic vertical",
        "door opening to reveal hidden room dramatic reveal warm light spilling out vertical",
        "blooming flower time-lapse petals opening reveal stunning detail vertical",
    ],
    "triumphant": [
        "champion holding trophy aloft confetti falling dramatic spotlight crowd cheering victory moment vertical",
        "rocket launching at dawn massive flame trail blue sky ascending powerful inspiring achievement vertical",
        "finish line runner breaking tape exhausted triumphant stadium full crowd emotional peak moment vertical",
        "flag raised on mountain peak victorious achievement dramatic landscape vertical",
        "golden trophy gleaming in spotlight success achievement celebratory vertical",
    ],
}


def _build_offline_scenes_from_meta(t, n, meta, rng):
    _ENERGY_MAP = {
        "rising": "energetic", "falling": "calm", "peak": "intense",
        "resolution": "hopeful", "climactic": "triumphant", "building": "energetic",
        "high": "intense", "shift": "reveal", "sympathetic": "calm",
        "action": "triumphant", "sobering": "calm", "wonder": "curious",
        "exploration": "curious", "awe": "reveal", "reflection": "calm",
        "frustrating": "intense", "exciting": "triumphant", "mysterious": "mysterious",
        "curious": "curious", "reveal": "reveal", "hopeful": "hopeful",
        "intense": "intense", "calm": "calm", "triumphant": "triumphant",
        "intriguing": "mysterious", "conventional": "calm", "mindblown": "reveal",
        "analytical": "calm", "empowering": "hopeful",
    }

    def _vis_pool(energy, default="calm"):
        mapped = _ENERGY_MAP.get(energy, energy)
        return _ENERGY_VISUAL_POOLS.get(mapped, _ENERGY_VISUAL_POOLS.get(default))

    fmt_name = meta.get("format")
    cta_style = meta.get("cta", "follow")
    is_crypto = (meta.get("category", "") == "crypto")
    fmt_templates = _OFFLINE_FORMAT_TEMPLATES.get(fmt_name)

    if fmt_templates:
        openers = fmt_templates.get("crypto_openers" if is_crypto else "openers", fmt_templates["openers"])
        mid_pool = fmt_templates.get("crypto_mids" if is_crypto else "mid_scenes", fmt_templates["mid_scenes"])
    else:
        if is_crypto:
            openers = _CRYPTO_OPENERS
            mid_pool = _CRYPTO_MIDS
        else:
            openers = [
                f"Here is what you need to know about {t}.",
                f"Let me break down {t} for you in a way that actually makes sense.",
                f"The truth about {t} is finally coming to light.",
            ]
            mid_pool = [
                f"Here is why {t} matters more than you think.",
                f"The deeper you look into {t}, the more fascinating it becomes.",
                f"This aspect of {t} changes how you see everything.",
            ]

    performer = meta.get("performer_persona", "expert")
    performer_intros = {
        "expert": f"According to experts in {t},",
        "researcher": f"Research published on {t} shows that",
        "practitioner": f"From years of working with {t},",
        "observer": f"If you look closely at {t},",
        "contrarian": f"But here is what most people get wrong about {t},",
    }
    performer_pre = performer_intros.get(performer, f"Here is the thing about {t},")

    extra_bodies = [
        f"{performer_pre} the most important factor is consistency over time.",
        f"{performer_pre} the results speak for themselves when you dig into the data.",
        f"{performer_pre} this is the part that surprises most people.",
        f"The key insight about {t} is that small changes compound into massive results.",
        f"Think about {t} from this angle and everything shifts into focus.",
        f"One study found that people who understand {t} are dramatically better off.",
        f"Here is a perspective on {t} that nobody talks about in mainstream discussions.",
    ]

    closers = [
        f"Start applying this to {t} today and see the difference for yourself.",
        f"Now you understand what really matters about {t}. Share this with someone.",
        f"This approach to {t} works because it addresses the root cause, not the symptoms.",
        f"The choice is yours. But now you have the real information about {t}.",
        f"This is just the beginning of understanding {t}. Follow for part two.",
        f"Try this one shift in how you think about {t} and watch what happens.",
        f"Now you know what most people never learn about {t} in a lifetime.",
    ]

    scene_energies = meta.get("scene_energies", ["calm", "curious", "intense", "hopeful", "triumphant"])
    scenes = []

    opener = rng.choice(openers).replace("{t}", t).replace("{n}", "1")
    scenes.append({"narration": opener, "keyword": rng.choice(_vis_pool(scene_energies[0]))})

    for i in range(1, n - 1):
        energy = scene_energies[min(i, len(scene_energies) - 1)]
        body = rng.choice(mid_pool + extra_bodies).replace("{t}", t).replace("{n}", str(i + 1))
        scenes.append({"narration": body, "keyword": rng.choice(_vis_pool(energy))})

    closer = rng.choice(closers).replace("{t}", t)
    final_energy = scene_energies[-1] if scene_energies else "hopeful"
    scenes.append({"narration": closer, "keyword": rng.choice(_vis_pool(final_energy, "hopeful"))})

    return scenes


def build_prompt(topic, extra_context=None):
    entropy = int.from_bytes(os.urandom(4)) + time.time_ns()
    rng = random.Random(_seed(topic) + entropy)

    category, sensitive = _classify_topic(topic)

    drifted = _drift_topic(topic, rng)

    available_voices = VOICES[:]
    if sensitive:
        available_voices = [v for v in available_voices
                            if v["name"] not in ("humorous", "skeptical")]
    cat_preferred_voices = {
        "crypto": ["authoritative", "direct", "skeptical"],
        "tech": ["authoritative", "direct", "curious"],
        "health": ["authoritative", "empathetic", "inspirational"],
        "finance": ["authoritative", "direct", "conversational"],
        "motivation": ["inspirational", "empathetic", "conversational"],
        "science": ["curious", "authoritative", "storyteller"],
        "psychology": ["curious", "mysterious", "authoritative"],
        "entertainment": ["humorous", "energetic", "storyteller"],
        "philosophy": ["contemplative", "mysterious", "storyteller"],
    }
    preferred = cat_preferred_voices.get(category, [])
    if preferred and rng.random() < 0.5:
        preferred_voices = [v for v in available_voices if v["name"] in preferred]
        if preferred_voices:
            available_voices = preferred_voices + [v for v in available_voices if v["name"] not in preferred]

    available_tones = list(TONES)
    if sensitive:
        available_tones = [t for t in available_tones
                           if t not in ("humorous", "entertaining", "skeptical")]

    for _ in range(20):
        fmt_candidate = rng.choice(SCRIPT_FORMATS)
        combo_key = f"fmt:{fmt_candidate['name']}"
        if not _recently_used(combo_key):
            break
    fmt = fmt_candidate

    arc_weights = []
    for arc in NARRATIVE_ARCS:
        w = arc["suitability"].get(fmt["name"], 0.5)
        arc_weights.append(w + rng.uniform(-0.1, 0.1))
    arc_weights = [max(0.05, w) for w in arc_weights]
    arc = rng.choices(NARRATIVE_ARCS, weights=arc_weights)[0]

    voice_weights = _build_weights(rng, available_voices, _VOICE_FORMAT_WEIGHTS, "name", "name", fmt["name"])
    if preferred:
        for i, v in enumerate(available_voices):
            if v["name"] in preferred:
                voice_weights[i] *= 1.3
    voice = rng.choices(available_voices, weights=voice_weights)[0]

    tone_weights = _build_weights(rng, available_tones, _TONE_FORMAT_WEIGHTS, None, None, fmt["name"])
    tone = rng.choices(available_tones, weights=tone_weights)[0]

    pacing = rng.choice(PACING_PROFILES)
    lang = rng.choice(LANG_LEVELS)
    pronoun = rng.choice(PRONOUN_STYLES)
    hook_style = rng.choice(HOOK_STYLES)
    cta = rng.choice(CTA_STYLES)
    vis_density = rng.choice(VISUAL_DENSITIES)
    emotional_arc = rng.choice(EMOTIONAL_ARCS)
    rhetorical = rng.sample(RHETORICAL_DEVICES, k=rng.randint(1, 3))
    performer = rng.choice(_PERFORMER_TEMPLATES)

    num_scenes = rng.randint(*fmt["scene_range"])
    arc_energies = arc["scene_energy"]
    scene_energies = [rng.choice(arc_energies) for _ in range(num_scenes)]
    scene_purposes = _assign_scene_purposes(rng)
    viral_pattern = _select_viral_pattern(rng)

    hook_text = _generate_hook(hook_style, topic, rng)

    _save_memory("combo", f"fmt:{fmt['name']}")
    _save_memory("combo", f"voice:{voice['name']}")
    _save_memory("combo", f"tone:{tone}")

    fmt_struct = fmt["structure"].format(topic=topic)

    purpose_labels = scene_purposes[:num_scenes]
    while len(purpose_labels) < num_scenes:
        purpose_labels.append("narrative")
    scene_guide = "\n".join(
        f"  Scene {i + 1}: energy = {scene_energies[i]}, purpose = {purpose_labels[i]}"
        for i in range(num_scenes)
    )

    _fp_meta = {
        "format": fmt["name"], "voice": voice["name"], "tone": tone,
        "arc": arc["name"], "pacing": pacing["name"], "hook_style": hook_style,
        "viral": viral_pattern["name"], "purposes": purpose_labels,
        "num_scenes": num_scenes,
    }
    fingerprint = _build_fingerprint(_fp_meta)
    _ensure_unique_fingerprint(fingerprint)

    _ctx = ""
    if extra_context:
        _ctx = (
            f"\nSHEET REFERENCE TITLE: {extra_context.get('title', '')}\n"
            f"SHEET REFERENCE HOOK: {extra_context.get('hook', '')}\n"
            f"SHEET REFERENCE DESCRIPTION: {extra_context.get('desc', '')}\n"
            f"IMPORTANT: Use the above as the CORE TOPIC. Generate scenes that expand on this. "
            f"The hook and title above are final -- do NOT change them.\n"
        )

    prompt = f"""You are a world-class faceless YouTube Shorts scriptwriter and visual director.
{_ctx}
CONTENT ANGLE: {drifted}

CATEGORY: {category.upper()}
TOPIC SENSITIVITY: {"SENSITIVE -- handle with care, avoid humour/sarcasm" if sensitive else "NORMAL"}

SCRIPT FORMAT: {fmt_struct}

NARRATIVE ARC: {arc['name']} -- {arc['description']}

VOICE: {voice['name']}
{voice['persona']}
Voice delivery: {voice['style']}

EMOTIONAL TONE: {tone.upper()}

PACING: {pacing['name']} -- {pacing['description']}

LANGUAGE LEVEL: {lang['name']}
Language style: {lang['desc']}
Average sentence length: ~{lang['avg_words_per_sentence']} words

PRONOUN PERSPECTIVE: {pronoun['name']}
Use pronouns like: {pronoun['pronouns']}
Example: {pronoun['example'].format(topic=topic)}

HOOK EXAMPLE (use this exact style, not the text itself): "{hook_text}"

END CALL TO ACTION STYLE: {cta.replace('_', ' ').title()}

VISUAL DENSITY: {vis_density['name']}
Visual style: {vis_density['desc']}

EMOTIONAL JOURNEY THROUGH SCENES: {' -> '.join(emotional_arc)}

VIRAL PSYCHOLOGICAL PATTERN: {viral_pattern['name'].replace('_', ' ').title()}
Pattern description: {viral_pattern['desc']}
Emotional trigger: {viral_pattern['trigger']}
Use this pattern as the psychological backbone of the script. Every scene should build toward this trigger.

RHETORICAL TECHNIQUES TO INCLUDE: {', '.join(rhetorical)}

PERFORMER PERSONA: {performer['name']} ({performer['style']})
Use phrases like: "{performer['intro']}"

SCENE ENERGY MAP ({num_scenes} scenes):
{scene_guide}

VIRAL OPTIMISATION (MANDATORY):
This script MUST go viral. Apply ALL of these:
1. Open with a PATTERN INTERRUPT — first 2 words must stop the scroll
2. Every 10 seconds include a MINI-HOOK to prevent drop-off
3. End with a HIGH-INTENSITY CTA that forces engagement (comment/share/save)
4. Use EMOTIONAL CONTRAST — flip between curiosity, urgency, and relief
5. The pinned COMMENT must start a conversation or debate — include a question
6. HASHTAGS: mix broad (#motivation, #shorts) with niche (#procrastination) for maximum reach

SELF-SCORING (REQUIRED):
After writing the script, honestly rate it:
- virality_score (0.0-1.0): How likely is this to be shared/saved? Must be > 0.6.
- attention_score (0.0-1.0): How well does it hook and retain attention? Must be > 0.6.
If either score is <= 0.6, rewrite the script until both exceed 0.6.

OUTPUT FORMAT:
Return ONLY valid JSON with EXACTLY these keys:
{{
  "title": "clickable title <= 70 chars, no quotes",
  "description": "2-3 punchy lines with emojis then 7-10 relevant #hashtags on new lines",
  "tags": ["12", "lowercase", "seo", "tags"],
  "hook": "4-7 word on-screen hook shown first 3 seconds ({hook_style.replace('_', ' ').title()} style, inspired by: {hook_text})",
  "comment": "one sentence that starts a conversation or debate — ends with a question to drive replies",
  "virality_score": 0.0,
  "attention_score": 0.0,
  "scenes": [
    {{"narration": "one energetic spoken sentence", "keyword": "CINEMATIC VISUAL DESCRIPTION 10-20 words"}}
  ]
}}

TIME BUDGET: This is a YouTube Short (max 60 seconds).
- Total script: ~35-50 seconds spoken (remaining time is intro + pauses).
- Each narration line: 1 sentence, 8-16 words, delivers ONE complete idea.
- Every sentence must provide valuable, self-contained information.
- ZERO filler words, ZERO fluff, ZERO redundant phrasing.
- Each scene advances the narrative -- if a scene can be cut without losing meaning, rewrite or remove it.

NARRATION RULES:
- Match the {voice['name']} voice and {lang['name']} language level.
- Follow the {arc['name']} narrative arc structure naturally.
- Vary sentence structure every scene. Use {', '.join(rhetorical)} where natural.
- Match each scene's energy: {scene_guide}
- NEVER start two consecutive scenes with the same word or sentence structure.
- Vary sentence length -- mix short punchy sentences with longer descriptive ones.
- No emojis in narration. No repetitive sentence patterns across scenes.

KEYWORD RULES:
Each "keyword" = CINEMATIC VISUAL DESCRIPTION (10-20 words) for vertical 9:16:
- Specific subject (not abstract)
- Lighting quality (golden hour, dramatic shadows, neon glow, rim light, etc.)
- Camera perspective (close-up, POV, overhead, low angle, Dutch angle, etc.)
- Mood matching the {tone} tone and the scene's energy
- Colors and textures matching {vis_density['name']} density
- Composition for vertical frame (foreground depth, leading lines, centered subject)

Each scene keyword MUST have a COMPLETELY DIFFERENT visual subject, setting, camera perspective, and color palette from all others.

Valid JSON only. No markdown fences.

TOPIC: "{topic}"
"""

    meta = {
        "category": category,
        "sensitive": sensitive,
        "drifted_angle": drifted,
        "format": fmt["name"],
        "narrative_arc": arc["name"],
        "voice": voice["name"],
        "tone": tone,
        "pacing": pacing["name"],
        "language_level": lang["name"],
        "pronoun_perspective": pronoun["name"],
        "hook_style": hook_style,
        "hook_text": hook_text,
        "cta": cta,
        "visual_density": vis_density["name"],
        "emotional_arc": " -> ".join(emotional_arc),
        "rhetorical_devices": rhetorical,
        "performer_persona": performer["name"],
        "scene_energies": scene_energies,
        "scene_purposes": purpose_labels,
        "num_scenes": num_scenes,
        "avg_sentence_words": lang["avg_words_per_sentence"],
        "viral_pattern": viral_pattern["name"],
        "viral_trigger": viral_pattern["trigger"],
        "fingerprint": fingerprint,
    }
    return prompt, meta


def build_offline_script(topic, meta=None):
    rng = random.Random(_seed(topic) + int.from_bytes(os.urandom(4)))

    t = topic.strip().rstrip(".!?")
    words = [w for w in re.findall(r"[A-Za-z]+", t) if len(w) > 3]
    meta = meta or {}
    n = meta.get("num_scenes", rng.randint(5, 7))
    cta_style = meta.get("cta", rng.choice(CTA_STYLES))

    scenes = _build_offline_scenes_from_meta(t, n, meta, rng)

    hook_style = meta.get("hook_style", "bold_claim")
    hook_line = _generate_hook(hook_style, t, rng)
    cta_lines = {
        "follow": "Follow for more insights like this",
        "comment": "Drop your thoughts in the comments below",
        "share": "Share this with someone who needs to hear it",
        "save": "Save this for later reference",
        "try": "Try this yourself and see the difference",
        "opinion": "What do you think about this? Comment below",
        "next": "Stay tuned for the next video on this topic",
        "reflect": "Think about this today",
        "tag": "Tag someone who needs to see this",
        "subscribe": "Subscribe for more content like this",
    }
    cta_line = cta_lines.get(cta_style, "Follow for more")

    diversity_warnings = _validate_narration_diversity(scenes)
    if diversity_warnings:
        print(f"    offline diversity warnings: {'; '.join(diversity_warnings)}")

    tag_words = [w.lower() for w in words[:3]]
    return {
        "title": f"The Truth About {t.title()}"[:100],
        "description": f"What nobody tells you about {t}.\n{cta_line}\n"
                       f"#shorts #{tag_words[0] if tag_words else 'facts'} #motivation #learn #daily"
                       f" #{tag_words[1] if len(tag_words) > 1 else 'tips'} #{tag_words[2] if len(tag_words) > 2 else 'life'}",
        "tags": ["shorts", "facts", "education", "motivation"] + tag_words,
        "hook": hook_line,
        "comment": f"Do you agree? Share your thoughts below \u2193",
        "virality_score": round(rng.uniform(0.65, 0.85), 2),
        "attention_score": round(rng.uniform(0.65, 0.85), 2),
        "scenes": scenes,
    }
