"""Persistent done-topic tracker for long-form CSV/built-in fallback.

Records topic hashes + date so we never repeat a topic, even if the
Google Sheet is unreachable or all sheet rows are done.
"""
import os
import json
import hashlib
import datetime

_DONE_FILE = os.path.join(os.path.dirname(__file__), "done_topics.json")


def _load():
    if not os.path.exists(_DONE_FILE):
        return {}
    try:
        with open(_DONE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data):
    os.makedirs(os.path.dirname(_DONE_FILE), exist_ok=True)
    with open(_DONE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  done-tracker saved: {_DONE_FILE}", flush=True)


def _topic_id(topic):
    raw = topic.strip().lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_done(topic):
    tid = _topic_id(topic)
    data = _load()
    return tid in data


def mark_done(topic, url=""):
    tid = _topic_id(topic)
    data = _load()
    data[tid] = {
        "topic": topic.strip()[:120],
        "date": datetime.date.today().isoformat(),
        "url": url,
    }
    _save(data)


def filter_undone(rows):
    """Given a list of dicts with at least 'topic', return only undone rows."""
    data = _load()
    out = []
    for r in rows:
        tid = _topic_id(r.get("topic", ""))
        if tid not in data:
            out.append(r)
    return out


def reset():
    """Delete the tracker file (for testing)."""
    if os.path.exists(_DONE_FILE):
        os.remove(_DONE_FILE)
