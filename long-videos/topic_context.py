"""Topic context parser, passer, and storer for the long-form pipeline.

Parses raw LLM topic-pick responses into structured TopicContext objects,
passes them through pipeline stages, and persists to disk.
"""
import os
import json
import datetime
from dataclasses import dataclass, field, asdict


@dataclass
class TopicContext:
    """Structured context for a selected video topic."""
    topic: str
    target_region: str = ""
    reason_picked: str = ""
    hook: str = ""
    video_angle: str = ""
    what_happened: str = ""
    why_now: str = ""
    key_facts: list = field(default_factory=list)
    news_headlines: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    search_date: str = ""
    source_label: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_llm_response(cls, raw: dict, source_label: str = ""):
        """Parse raw LLM JSON response into a TopicContext."""
        ctx_raw = raw.get("_topic_context", {}) if "_topic_context" in raw else raw.get("topic_context", {})
        return cls(
            topic=(raw.get("selected_topic") or raw.get("topic") or "").strip(),
            target_region=raw.get("target_region", ""),
            reason_picked=raw.get("reason_picked", ""),
            hook=raw.get("hook", ""),
            video_angle=raw.get("video_angle", "") or ctx_raw.get("video_angle", ""),
            what_happened=ctx_raw.get("what_happened", ""),
            why_now=ctx_raw.get("why_now", ""),
            key_facts=ctx_raw.get("key_facts", []),
            news_headlines=ctx_raw.get("news_headlines", []),
            sources=ctx_raw.get("sources", []),
            search_date=datetime.date.today().isoformat(),
            source_label=source_label,
        )

    @classmethod
    def from_item(cls, item: dict):
        """Build a minimal TopicContext from a sheet/CSV item."""
        return cls(
            topic=(item.get("topic") or "").strip(),
            target_region="",
            reason_picked="from topic source",
            hook=item.get("_hook", ""),
            video_angle="",
            what_happened="",
            why_now="",
            key_facts=[],
            news_headlines=[],
            sources=[],
            search_date=datetime.date.today().isoformat(),
            source_label=item.get("source", "unknown"),
        )

    def summary(self, max_facts=3):
        """Return a human-readable string for prompt injection."""
        lines = []
        if self.topic:
            lines.append(f"SELECTED TOPIC: {self.topic}")
        if self.target_region:
            lines.append(f"TARGET REGION: {self.target_region}")
        if self.reason_picked:
            lines.append(f"WHY THIS TOPIC: {self.reason_picked[:200]}")
        if self.what_happened:
            lines.append(f"WHAT HAPPENED: {self.what_happened[:300]}")
        if self.why_now:
            lines.append(f"WHY NOW: {self.why_now[:200]}")
        if self.video_angle:
            lines.append(f"VIDEO ANGLE: {self.video_angle[:200]}")
        if self.key_facts:
            for i, f in enumerate(self.key_facts[:max_facts]):
                lines.append(f"  FACT {i+1}: {f[:200]}")
        if self.news_headlines:
            lines.append(f"  HEADLINES: {' | '.join(self.news_headlines[:3])}")
        return "\n".join(lines)


# ─── Parser ──────────────────────────────────────────────────────────

def parse_topic_context(item: dict, source_label: str = "") -> TopicContext:
    """Parse any item dict into a TopicContext.
    
    Handles both LLM-picked topics (with _topic_context) and
    sheet/CSV items (minimal context).
    """
    if item.get("_topic_context") or item.get("topic_context"):
        return TopicContext.from_llm_response(item, source_label or item.get("source", "llm-pick"))
    return TopicContext.from_item(item)


# ─── Passer ──────────────────────────────────────────────────────────

def build_script_context_block(ctx: TopicContext) -> str:
    """Build a context block to inject into the script generation prompt.
    
    This gives the LLM full, specific information about the topic so
    it can write a grounded, factually rich script — no confusion.
    """
    parts = []
    if ctx.what_happened:
        parts.append(f"RECENT DEVELOPMENTS:\n{ctx.what_happened}")
    if ctx.why_now:
        parts.append(f"\nWHY THIS IS TIMELY:\n{ctx.why_now}")
    if ctx.key_facts:
        parts.append(f"\nKEY FACTS & DATA:\n" + "\n".join(f"• {f}" for f in ctx.key_facts))
    if ctx.news_headlines:
        parts.append(f"\nRECENT HEADLINES:\n" + "\n".join(f"• {h}" for h in ctx.news_headlines))
    if ctx.sources:
        parts.append(f"\nSOURCES:\n" + "\n".join(f"• {s}" for s in ctx.sources[:5]))
    if ctx.video_angle:
        parts.append(f"\nRECOMMENDED VIDEO ANGLE:\n{ctx.video_angle}")

    if not parts:
        return ""

    return (
        "═══════════════════════════════════════════════\n"
        "CURRENT TOPIC CONTEXT (use this to ground your script in real, timely information):\n"
        + "\n".join(parts) +
        "\n═══════════════════════════════════════════════\n"
        "Integrate these facts naturally. Do NOT list them robotically. "
        "Weave them into the narrative as a human expert would."
    )


def build_thumbnail_context(ctx: TopicContext) -> dict:
    """Build context for the thumbnail generator."""
    return {
        "region": ctx.target_region,
        "hook": ctx.hook,
        "reason": ctx.reason_picked[:100],
        "video_angle": ctx.video_angle[:100],
    }


def build_transcript_context(ctx: TopicContext) -> dict:
    """Build context for the transcript/description generator."""
    return {
        "region": ctx.target_region,
        "hook": ctx.hook,
        "key_facts": ctx.key_facts[:5],
        "headlines": ctx.news_headlines[:3],
    }


# ─── Storer ──────────────────────────────────────────────────────────

_CONTEXT_STORE_PATH = os.path.join("output_long", "topic_context.json")


def store_context(ctx: TopicContext):
    """Persist the topic context to disk for downstream use."""
    os.makedirs("output_long", exist_ok=True)
    data = ctx.to_dict()
    data["_stored_at"] = datetime.datetime.now().isoformat()
    with open(_CONTEXT_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  topic context stored: {_CONTEXT_STORE_PATH}", flush=True)


def load_context() -> TopicContext | None:
    """Load the most recently stored topic context."""
    if not os.path.exists(_CONTEXT_STORE_PATH):
        return None
    try:
        with open(_CONTEXT_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return TopicContext(**{k: v for k, v in data.items() if k in TopicContext.__dataclass_fields__})
    except (json.JSONDecodeError, OSError):
        return None


# ─── Pipeline Integration ────────────────────────────────────────────

def integrate_context_into_pipeline(
    ctx: TopicContext,
    script_prompt: str,
) -> str:
    """Inject topic context into the script generation prompt."""
    block = build_script_context_block(ctx)
    if block:
        return script_prompt + "\n\n" + block
    return script_prompt
