"""Topic source with a graceful fallback chain.

Order:
  1. Google Sheet (service account) — full status tracking, writes back
  2. topics.csv in the repo        — rotates by day-of-year, no state
  3. built-in topic list           — pipeline never dies

Sheet header row (row 1): topic | voice | privacy | status | youtube_url | date_posted
topics.csv columns:        topic,voice,privacy
"""
import os
import csv
import json
import datetime

FALLBACK_TOPICS = [
    {"topic": "3 habits that quietly build unstoppable discipline",
     "voice": "en-US-GuyNeural", "privacy": "unlisted"},
    {"topic": "why your brain sabotages your goals and how to stop it",
     "voice": "en-US-AriaNeural", "privacy": "unlisted"},
    {"topic": "the 5 minute rule that beats procrastination",
     "voice": "en-US-GuyNeural", "privacy": "unlisted"},
]


def _worksheet():
    import gspread
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = gspread.service_account_from_dict(info)
    return gc.open_by_key(os.environ["SHEET_ID"]).sheet1


def _from_sheet():
    ws = _worksheet()
    for i, rec in enumerate(ws.get_all_records()):
        status = str(rec.get("status", "")).strip().lower()
        if status in ("", "pending", "todo", "queue", "queued"):
            rec = {str(k).lower(): v for k, v in rec.items()}
            return {"row_idx": i + 2, "source": "google-sheet", **rec}
    return None  # sheet reachable but everything is done


def _from_csv():
    if not os.path.exists("topics.csv"):
        raise FileNotFoundError("no topics.csv in repo root")
    with open("topics.csv", newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("topic") or "").strip()]
    if not rows:
        raise ValueError("topics.csv has no usable rows")
    pick = rows[datetime.date.today().timetuple().tm_yday % len(rows)]
    return {"row_idx": None, "source": "topics.csv", **pick}


def get_next_item():
    """Return an item dict {topic, voice, privacy, source, row_idx} — or None
    only when the Google Sheet is reachable and every row is already done."""
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and os.environ.get("SHEET_ID"):
        try:
            item = _from_sheet()
            if item is None:
                print("Sheet reachable: all rows done — nothing to post today.")
                return None
            return item
        except Exception as e:
            print(f"Google Sheet unavailable ({e}) -> falling back to topics.csv")
    try:
        return _from_csv()
    except Exception as e:
        print(f"topics.csv unavailable ({e}) -> using built-in topic list")
        pick = FALLBACK_TOPICS[
            datetime.date.today().timetuple().tm_yday % len(FALLBACK_TOPICS)]
        return {"row_idx": None, "source": "built-in", **pick}


def _write_fields(item, updates):
    """Write multiple fields to the sheet row."""
    if item.get("source") != "google-sheet" or not item.get("row_idx"):
        return
    try:
        ws = _worksheet()
        header = [h.strip().lower() for h in ws.row_values(1)]
        for name, value in updates.items():
            if name in header:
                ws.update_cell(item["row_idx"], header.index(name) + 1, value)
    except Exception as e:
        print(f"WARNING: could not write to sheet: {e}")


def write_script_metadata(item, plan):
    """Write back LLM-generated title, description, tags, hook to sheet."""
    _write_fields(item, {
        "script_title": (plan.get("title") or "")[:200],
        "script_desc": (plan.get("description") or "")[:500],
        "script_tags": ",".join(plan.get("tags") or [])[:500],
        "script_hook": (plan.get("hook") or "")[:200],
    })


def mark_done(item, url):
    """Write status back — only possible when the topic came from the Sheet."""
    if item.get("source") != "google-sheet" or not item.get("row_idx"):
        print(f"(source={item.get('source')}: no write-back, nothing to update)")
        return
    _write_fields(item, {"status": "done", "youtube_url": url,
                         "date_posted": datetime.date.today().isoformat()})
    print("Sheet updated.")


def get_recent_urls(limit=5):
    """Return the most recent youtube_url values from done rows."""
    try:
        ws = _worksheet()
        vals = ws.get_all_values()
        header = [h.strip().lower() for h in vals[0]]
        try:
            url_idx = header.index("youtube_url")
            status_idx = header.index("status")
        except ValueError:
            return []
        urls = []
        for row in reversed(vals[1:]):
            if len(row) > max(url_idx, status_idx):
                if str(row[status_idx]).strip().lower() == "done":
                    url = str(row[url_idx]).strip()
                    if url:
                        urls.append(url)
                        if len(urls) >= limit:
                            break
        return urls
    except Exception as e:
        print(f"WARNING: could not read recent URLs: {e}")
        return []
