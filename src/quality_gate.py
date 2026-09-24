"""Repeated-sentence check for the shorts pipeline.

The offline fallback is allowed to ship, but only if its narration actually
varies. A run whose narration repeats itself is blocked before render and
upload.
"""
import os
import re
from collections import Counter

MAX_REPEAT_RATIO = float(os.environ.get("QG_MAX_REPEAT_RATIO", "0.10"))


def repeated_sentence_ratio(scenes):
    sents = []
    for sc in scenes or []:
        for s in re.split(r"(?<=[.!?])\s+", str(sc.get("narration", ""))):
            norm = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
            if len(norm.split()) >= 4:
                sents.append(norm)
    if not sents:
        return 1.0
    counts = Counter(sents)
    return sum(c - 1 for c in counts.values() if c > 1) / len(sents)


def check(scenes):
    """Return (ok, reason)."""
    ratio = repeated_sentence_ratio(scenes)
    if ratio > MAX_REPEAT_RATIO:
        return False, f"repeated-sentence ratio {ratio:.2f} > {MAX_REPEAT_RATIO:.2f}"
    return True, f"ok (repeat ratio {ratio:.2f})"
