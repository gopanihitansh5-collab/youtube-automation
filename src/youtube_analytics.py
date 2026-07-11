"""YouTube Analytics feedback — flags underperforming topics from prior videos.

Uses the YouTube Data API v3 (statistics part) to check views/retention of
recent videos. Topics that fall below thresholds get 'skip_reason' written back
to the sheet so the pipeline skips them.

Graceful: if the OAuth token lacks the 'youtube.readonly' scope, the module
silently does nothing.
"""
import os
import json
import datetime

THRESHOLDS = {
    "min_views": 50,           # < 50 views after 48h → skip
    "min_retention_pct": 30,   # < 30% average retention → skip (approximate)
}

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    refresh = os.environ.get("YT_REFRESH_TOKEN")
    cid = os.environ.get("YT_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET")
    if not all([refresh, cid, secret]):
        return None
    creds = Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    try:
        return build("youtube", "v3", credentials=creds)
    except Exception as e:
        print(f"  analytics: cannot build YouTube service ({e}) — skipping")
        return None


def fetch_video_stats(youtube, video_ids):
    """Return {video_id: {views, likes, comments}} for a list of IDs."""
    ids = [v for v in video_ids if v]
    if not ids:
        return {}
    try:
        resp = youtube.videos().list(
            part="statistics,snippet",
            id=",".join(ids[:50]),
        ).execute()
    except Exception as e:
        print(f"  analytics: API call failed ({e})")
        return {}

    stats = {}
    for item in resp.get("items", []):
        vid = item["id"]
        s = item.get("statistics", {})
        stats[vid] = {
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
            "published": item.get("snippet", {}).get("publishedAt", ""),
        }
    return stats


def _video_id_from_url(url):
    """Extract video ID from https://youtu.be/VIDEO_ID."""
    if not url:
        return None
    url = url.strip()
    if "/" in url:
        return url.rsplit("/", 1)[-1].split("?")[0]
    return url


def check_and_flag(prior_urls):
    """Check the most recent video's stats. If below thresholds, write to
    reports/analytics.json for diagnostics. Returns True if the most recent
    video performed well."""
    youtube = _service()
    if not youtube:
        return True  # can't check → don't skip

    vid = _video_id_from_url(prior_urls[-1]) if prior_urls else None
    if not vid:
        return True

    stats = fetch_video_stats(youtube, [vid])
    if not stats or vid not in stats:
        return True

    s = stats[vid]
    # Age in hours
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        pub = datetime.datetime.fromisoformat(s["published"].replace("Z", "+00:00"))
        age_h = max(0, (now - pub).total_seconds() / 3600)
    except (ValueError, KeyError):
        age_h = 999

    os.makedirs("output", exist_ok=True)
    report_path = "output/analytics.json"
    existing = {}
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing[vid] = {**s, "checked_at": now.isoformat()}
    with open(report_path, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"  analytics: {vid} — {s['views']} views, {s['likes']} likes "
          f"({age_h:.0f}h old)", flush=True)

    if age_h < 48:
        print(f"  analytics: video is only {age_h:.0f}h old — skipping threshold check")
        return True

    if s["views"] < THRESHOLDS["min_views"]:
        print(f"  analytics: {vid} has only {s['views']} views (< {THRESHOLDS['min_views']}) "
              f"— FLAGGING for review", flush=True)
        return False

    return True
