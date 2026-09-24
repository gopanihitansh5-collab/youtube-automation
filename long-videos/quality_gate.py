"""Hard gate before render/upload.

Blocks the run when the script came from the offline builder or when the
narration repeats itself too much. A blocked run exits non-zero so nothing
is rendered or uploaded and the workflow shows red.
"""
import os
import re
from collections import Counter

MAX_REPEAT_RATIO = float(os.environ.get("QG_MAX_REPEAT_RATIO", "0.10"))


def _sentences(plan):
    out = []
    for ch in plan.get("chapters", []):
        for sc in ch.get("scenes", []):
            text = str(sc.get("narration", ""))
            for s in re.split(r"(?<=[.!?])\s+", text):
                norm = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
                if len(norm.split()) >= 4:
                    out.append(norm)
    return out


def repeated_sentence_ratio(plan):
    sents = _sentences(plan)
    if not sents:
        return 1.0
    counts = Counter(sents)
    repeats = sum(c - 1 for c in counts.values() if c > 1)
    return repeats / len(sents)


def check(plan, provider):
    """Return (ok, reason)."""
    if "offline" in str(provider).lower():
        return False, f"script provider is {provider!r}"
    ratio = repeated_sentence_ratio(plan)
    if ratio > MAX_REPEAT_RATIO:
        return False, (f"repeated-sentence ratio {ratio:.2f} > "
                       f"{MAX_REPEAT_RATIO:.2f}")
    return True, f"ok (repeat ratio {ratio:.2f})"
