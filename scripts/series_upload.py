"""One-off batch upload: 'How AI Agents Actually Work' series (14 videos).

Runs once in GitHub Actions; workflow + this file are removed after success.
Auth: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN repo secrets, same
refresh-token pattern as the daily pipeline (src/youtube_upload.py). Secret
values are never printed. Idempotent: re-runs skip videos already on the
channel (exact title match) and playlist items already added, and continue
the hourly publishAt chain from whatever is already scheduled.

Order: probe playlist scope -> create/reuse playlist -> landscape final
(public now) -> Shorts 1-12 (publishAt hourly, Part 1 ASAP) -> vertical
final Short (slot 13) -> add all 14 to playlist -> verify statuses.
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
WORK = "/tmp/series"
RESULTS = "output/series-results.json"
PLAYLIST_TITLE = "How AI Agents Actually Work | 12-Part AI Explainer"
PLAYLIST_DESC = "12 quick lessons, each about 10 seconds, on goals, reasoning, tools, actions, observation, memory and the difference between an AI agent and a chatbot. Watch the full two-minute explainer too."
VIDEOS = [
  {
    "kind": "part",
    "part": 1,
    "file": "short01-how-ai-agents-work-hook.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1Ms1Uk_eA2cBFVtrvyz_P-tYppNAvdsx1",
    "size": 1578103,
    "title": "AI Agent vs Chatbot: It Can Actually Do Things | Part 01/12 #Shorts",
    "description": "A chatbot answers a question. An AI agent can work toward a goal with tools, decisions and actions. This 10-second hook starts the 12-part series.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 01/12\n\n#AIAgents #AIExplained #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIExplained",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 2,
    "file": "short02-what-is-an-agent.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1cYGzq1tU9bStB1pVNF4-0nSMhOpCYgZp",
    "size": 2450669,
    "title": "What Is an AI Agent? A Goal-Driven Assistant | Part 02/12 #Shorts",
    "description": "Give an AI agent a goal. It works out the steps rather than waiting for you to spell out every click. Part 2 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 02/12\n\n#AIAgents #Automation #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "Automation",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 3,
    "file": "short03-the-goal.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1Lk2E-j4rwCBxoCYT5wgxvVwOw1kBcXiA",
    "size": 1788918,
    "title": "Every AI Agent Starts With a Goal | Part 03/12 #Shorts",
    "description": "A concrete goal - like finding 10 qualified leads - gives the agent a task it can plan and check. Part 3 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 03/12\n\n#AIAgents #GoalSetting #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "GoalSetting",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 4,
    "file": "short04-reasoning.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1UDRkyTHDFF37qcYwQTKAjgmP-u59L6LP",
    "size": 1289880,
    "title": "How AI Agents Break Down a Task | Part 04/12 #Shorts",
    "description": "Search for companies, find decision-makers, check the facts, then qualify. The agent plans a sequence before it acts. Part 4 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 04/12\n\n#AIAgents #AIWorkflow #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIWorkflow",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 5,
    "file": "short05-tools.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1D8vzX01t-1htkv4JAgdeDovl9dH313Bh",
    "size": 2095965,
    "title": "AI Agents Need Tools, Not Just a Model | Part 05/12 #Shorts",
    "description": "APIs, databases, browsers, search, CRMs and code let an agent work with the outside world. The model alone cannot magically access everything. Part 5 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 05/12\n\n#AIAgents #AITools #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AITools",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 6,
    "file": "short06-action.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1Y_CHcV5AJ59d3Y8evUSoP01r5kzTY5lf",
    "size": 2284609,
    "title": "What Can an AI Agent Actually Do? | Part 06/12 #Shorts",
    "description": "A tool-equipped agent can search, call an API, update a CRM, send an email or prepare a report when given the right access. Part 6 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 06/12\n\n#AIAgents #Automation #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "Automation",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 7,
    "file": "short07-observe.mp4",
    "url": "https://drive.google.com/uc?export=download&id=12f0b3DWlb4OzfKBF3oLYD3lGraPTmAaM",
    "size": 1903594,
    "title": "The Step AI Agents Cannot Skip: Observe | Part 07/12 #Shorts",
    "description": "After acting, the agent checks the result. Did the API respond? Was the right company found? Did a step fail? Part 7 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 07/12\n\n#AIAgents #AIAutomation #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIAutomation",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 8,
    "file": "short08-loop.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1oQUS7ZqfU4tOR7a2WvZsGVsYeD0_9zk5",
    "size": 1974212,
    "title": "The AI Agent Loop: Think, Act, Observe | Part 08/12 #Shorts",
    "description": "Agents work in a loop: think, act, observe, then adjust and try again until they have enough information to move forward. Part 8 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 08/12\n\n#AIAgents #AgentLoop #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AgentLoop",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 9,
    "file": "short09-memory.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1p0bskcWFsrUX0YEKeBeVzQt5FDpyF6wp",
    "size": 2424979,
    "title": "How AI Agents Use Memory | Part 09/12 #Shorts",
    "description": "An agent can use past conversation context, retrieved documents and a database to keep useful information available for the next step. Part 9 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 09/12\n\n#AIAgents #AIMemory #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIMemory",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 10,
    "file": "short10-sales-agent.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1mjB4SvowMHEi5A3nBVrufb69kxRDGVEG",
    "size": 1971499,
    "title": "AI Sales Agent: A 10-Second Example | Part 10/12 #Shorts",
    "description": "A sales agent can research potential customers, qualify them, write personalized outreach and update a CRM - with appropriate access and review. Part 10 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 10/12\n\n#AIAgents #SalesAutomation #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "SalesAutomation",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 11,
    "file": "short11-agent-vs-chatbot.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1JPwxUZZmY2yIq-sEAxULt1NPemPunCn9",
    "size": 1311239,
    "title": "AI Agent vs Chatbot: The Real Difference | Part 11/12 #Shorts",
    "description": "A chatbot mainly responds. An agent can pursue a goal across steps, use tools, react to results and take actions. Part 11 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 11/12\n\n#AIAgents #Chatbot #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "Chatbot",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 12,
    "file": "short12-big-takeaway.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1Cz_4uvP8WiKMGqLNENFXXtSlw9mHKeeQ",
    "size": 1252958,
    "title": "AI Agents = Think + Act + Learn | Part 12/12 #Shorts",
    "description": "Intelligence plus tools, a reasoning loop and actions: a simple way to understand why agents change how software works. Part 12 of 12.\n\nWatch the full 2-minute explainer: {FULL_VIDEO_URL}\n\nHow AI Agents Actually Work | Part 12/12\n\n#AIAgents #FutureOfAI #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "FutureOfAI",
      "Shorts"
    ]
  },
  {
    "kind": "part",
    "part": 13,
    "file": "how-ai-agents-actually-work-final.mp4",
    "url": "https://drive.google.com/uc?export=download&id=117dL4s6VEDInB2luX6apIm_PHob_5U5v",
    "size": 22312219,
    "title": "How AI Agents Actually Work in 2 Minutes | Full Vertical Edition #Shorts",
    "description": "What does an AI agent actually do? This two-minute visual guide goes from the first goal through planning, tools, action, observation, the reasoning loop and memory - then shows a sales-agent example and the difference from a chatbot.\n\n12 chapters, 10 seconds each:\n00:00 Hook - an agent can do things\n00:10 What is an agent?\n00:20 The goal\n00:30 Reasoning\n00:40 Tools\n00:50 Action\n01:00 Observe\n01:10 The loop\n01:20 Memory\n01:30 Real example: sales agent\n01:40 Agent vs chatbot\n01:50 Big takeaway\n\nWatch the widescreen full video: {LANDSCAPE_VIDEO_URL}\nWatch the 12-part Shorts series: {PLAYLIST_URL}\n\nAn agent's tools and actions still depend on the access, checks and permissions it is given.\n\n#AIAgents #AIExplained #Shorts\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIExplained",
      "Shorts"
    ]
  },
  {
    "kind": "final",
    "part": 0,
    "file": "how-ai-agents-actually-work-landscape.mp4",
    "url": "https://drive.google.com/uc?export=download&id=1bI2KJtFeJTBjdIBbkc0CLhPRhtsL4Qfd",
    "size": 18086450,
    "title": "How AI Agents Actually Work | Think, Act, Observe (2-Minute Explainer)",
    "description": "What does an AI agent actually do? This two-minute visual guide goes from the first goal through planning, tools, action, observation, the reasoning loop and memory - then shows a sales-agent example and the difference from a chatbot.\n\n12 chapters, 10 seconds each:\n00:00 Hook - an agent can do things\n00:10 What is an agent?\n00:20 The goal\n00:30 Reasoning\n00:40 Tools\n00:50 Action\n01:00 Observe\n01:10 The loop\n01:20 Memory\n01:30 Real example: sales agent\n01:40 Agent vs chatbot\n01:50 Big takeaway\n\nWatch the 12-part Shorts series: {PLAYLIST_URL}\n\nAn agent's tools and actions still depend on the access, checks and permissions it is given.\n\n#AIAgents #AIExplained #Automation\n\nEmoji graphics: Twemoji (CC-BY 4.0).",
    "tags": [
      "AIAgents",
      "AIExplained",
      "Automation"
    ]
  }
]


def log(msg):
    print(msg, flush=True)


def service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def download_all():
    os.makedirs(WORK, exist_ok=True)
    for v in VIDEOS:
        dest = os.path.join(WORK, v["file"])
        log(f"download {v['file']} ...")
        with requests.get(v["url"], stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        got = os.path.getsize(dest)
        if got != v["size"]:
            raise RuntimeError(f"{v['file']}: size mismatch {got} != {v['size']}")
        with open(dest, "rb") as f:
            if b"ftyp" not in f.read(64):
                raise RuntimeError(f"{v['file']}: not an MP4 (Drive error page?)")
    log("all 14 downloads verified")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ist_hour_floor(now):
    """now + 65 min, rounded UP to the next on-the-hour mark in IST
    (IST = UTC+5:30, so IST hour marks sit at UTC minute == 30)."""
    t = now + timedelta(minutes=65)
    t = t.replace(second=0, microsecond=0)
    if t.minute <= 30:
        return t.replace(minute=30)
    return (t + timedelta(hours=1)).replace(minute=30)


def probe_playlist_scope(yt):
    try:
        yt.playlists().list(part="snippet", mine=True, maxResults=1).execute()
        return True
    except HttpError as e:
        log(f"playlist scope probe failed: {e.status_code} {e.error_details or e}")
        return False


def existing_uploads(yt):
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    found = {}
    page = None
    while True:
        resp = yt.playlistItems().list(part="snippet", playlistId=up,
                                       maxResults=50, pageToken=page).execute()
        for it in resp.get("items", []):
            t = it["snippet"]["title"]
            if t not in found:
                found[t] = it["snippet"]["resourceId"]["videoId"]
        page = resp.get("nextPageToken")
        if not page:
            break
    pub = {}
    ids = list(found.values())
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            pub[it["id"]] = it["status"].get("publishAt")
    return {t: (vid, pub.get(vid)) for t, vid in found.items()}


def upload_one(yt, v, description, publish_at=None):
    status = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    else:
        status["privacyStatus"] = "public"
    body = {
        "snippet": {"title": v["title"][:100], "description": description,
                    "tags": v["tags"], "categoryId": "27"},
        "status": status,
    }
    media = MediaFileUpload(os.path.join(WORK, v["file"]),
                            chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        try:
            st, resp = req.next_chunk()
        except HttpError:
            raise
        except Exception as e:
            log(f"  chunk retry ({type(e).__name__})")
            time.sleep(5)
    return resp["id"]


def verify(yt, video_id, tries=12, delay=10):
    st = {}
    for _ in range(tries):
        r = yt.videos().list(part="status", id=video_id).execute()
        if not r.get("items"):
            time.sleep(delay)
            continue
        st = r["items"][0]["status"]
        if st.get("uploadStatus") in ("processed", "failed", "rejected"):
            return st
        time.sleep(delay)
    return st


def ensure_playlist(yt):
    page = None
    pl_id = None
    while True:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50,
                                   pageToken=page).execute()
        for it in resp.get("items", []):
            if it["snippet"]["title"] == PLAYLIST_TITLE:
                pl_id = it["id"]
        page = resp.get("nextPageToken")
        if pl_id or not page:
            break
    if not pl_id:
        resp = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": PLAYLIST_TITLE, "description": PLAYLIST_DESC},
            "status": {"privacyStatus": "public"},
        }).execute()
        pl_id = resp["id"]
        log(f"playlist created: {pl_id}")
    else:
        log(f"playlist exists: {pl_id}")
    return pl_id


def fill_playlist(yt, pl_id, ordered_ids):
    have = set()
    page = None
    while True:
        resp = yt.playlistItems().list(part="snippet", playlistId=pl_id,
                                       maxResults=50, pageToken=page).execute()
        for it in resp.get("items", []):
            have.add(it["snippet"]["resourceId"]["videoId"])
        page = resp.get("nextPageToken")
        if not page:
            break
    for vid in ordered_ids:
        if vid in have:
            continue
        yt.playlistItems().insert(part="snippet", body={
            "snippet": {"playlistId": pl_id,
                        "resourceId": {"kind": "youtube#video", "videoId": vid}},
        }).execute()
        log(f"  playlist += {vid}")


def is_quota(e):
    return e.status_code == 403 and "quota" in str(e.error_details or e).lower()


def main():
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            log(f"MISSING SECRET: {k}")
            sys.exit(1)
    os.makedirs("output", exist_ok=True)
    results = {"videos": [], "playlist_url": None}
    yt = service()

    if not probe_playlist_scope(yt):
        log("PLAYLIST_SCOPE_MISSING - halting before any upload")
        results["playlist_error"] = "insufficient scope for playlists"
        with open(RESULTS, "w") as f:
            json.dump(results, f, indent=2)
        sys.exit(3)

    download_all()

    pl_id = ensure_playlist(yt)
    pl_url = f"https://www.youtube.com/playlist?list={pl_id}"
    results["playlist_url"] = pl_url

    have = existing_uploads(yt)
    parts = [v for v in VIDEOS if v["kind"] == "part"]
    final = [v for v in VIDEOS if v["kind"] == "final"][0]

    # 1) landscape final first (public immediately) - Shorts link to it
    land_id = None
    if final["title"] in have:
        land_id = have[final["title"]][0]
        log(f"final exists: {land_id}")
        results["videos"].append({"file": final["file"], "title": final["title"],
                                  "video_id": land_id,
                                  "url": f"https://youtu.be/{land_id}",
                                  "skipped": "already uploaded"})
    land_url = f"https://youtu.be/{land_id}" if land_id else None

    quota_stop = False
    if land_id is None:
        desc = final["description"].replace("{PLAYLIST_URL}", pl_url)
        try:
            log(f"upload FINAL: {final['title']} (public)")
            land_id = upload_one(yt, final, desc)
            land_url = f"https://youtu.be/{land_id}"
            st = verify(yt, land_id)
            results["videos"].append({
                "file": final["file"], "title": final["title"],
                "video_id": land_id, "url": land_url,
                "privacyStatus": st.get("privacyStatus"),
                "uploadStatus": st.get("uploadStatus")})
            log(f"  ok: {land_url} status={st.get('uploadStatus')}")
        except HttpError as e:
            log(f"FINAL UPLOAD FAILED: {e.status_code} {e.error_details or e}")
            results["videos"].append({"file": final["file"], "title": final["title"],
                                      "error": f"{e.status_code} {e.error_details or e}"})
            if is_quota(e):
                quota_stop = True

    # 2) schedule chain for parts (IST-aligned, hourly)
    floor = ist_hour_floor(datetime.now(timezone.utc))
    slots = {}
    prev = None
    for v in parts:
        if v["title"] in have and have[v["title"]][1]:
            prev = parse_ts(have[v["title"]][1])
            continue
        slot = prev + timedelta(hours=1) if prev else floor
        if slot < floor:
            slot = floor
        slots[v["title"]] = slot
        prev = slot

    # 3) parts in order
    for v in parts:
        entry = {"file": v["file"], "title": v["title"], "part": v["part"]}
        if v["title"] in have:
            vid, pub = have[v["title"]]
            entry.update(video_id=vid, url=f"https://youtu.be/{vid}",
                         skipped="already uploaded", publishAt=pub)
            results["videos"].append(entry)
            log(f"skip (exists): Part {v['part']} -> {vid}")
            continue
        if quota_stop or land_url is None:
            entry["skipped"] = "quota exhausted" if quota_stop else "final missing"
            results["videos"].append(entry)
            continue
        desc = (v["description"]
                .replace("{FULL_VIDEO_URL}", land_url)
                .replace("{LANDSCAPE_VIDEO_URL}", land_url)
                .replace("{PLAYLIST_URL}", pl_url))
        if "{" in desc:
            entry["error"] = "unresolved placeholder in description"
            results["videos"].append(entry)
            continue
        pa = fmt_ts(slots[v["title"]])
        try:
            log(f"upload Part {v['part']}: publishAt={pa}")
            vid = upload_one(yt, v, desc, publish_at=pa)
        except HttpError as e:
            log(f"PART {v['part']} FAILED: {e.status_code} {e.error_details or e}")
            entry["error"] = f"{e.status_code} {e.error_details or e}"
            results["videos"].append(entry)
            if is_quota(e):
                quota_stop = True
            continue
        st = verify(yt, vid)
        entry.update(video_id=vid, url=f"https://youtu.be/{vid}",
                     publishAt=st.get("publishAt") or pa,
                     privacyStatus=st.get("privacyStatus"),
                     uploadStatus=st.get("uploadStatus"))
        results["videos"].append(entry)
        log(f"  ok: https://youtu.be/{vid} status={st.get('uploadStatus')}")

    # 4) playlist membership: Shorts 1-12, landscape final, vertical final
    id_by_title = {}
    for e in results["videos"]:
        if e.get("video_id"):
            id_by_title[e["title"]] = e["video_id"]
    shorts12 = [v for v in parts if v["part"] <= 12]
    vertical = [v for v in parts if v["part"] == 13]
    ordered = [id_by_title[v["title"]] for v in shorts12 + [final] + vertical
               if v["title"] in id_by_title]
    try:
        fill_playlist(yt, pl_id, ordered)
        results["playlist_filled"] = len(ordered)
    except HttpError as e:
        log(f"PLAYLIST FILL FAILED: {e.status_code} {e.error_details or e}")
        results["playlist_error"] = f"{e.status_code} {e.error_details or e}"

    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2)

    summary = ["## Series upload results", ""]
    for e in results["videos"]:
        line = f"- {e.get('title', e['file'])}"
        if e.get("url"):
            line += f" -> {e['url']}"
        if e.get("publishAt"):
            line += f" (publishes {e['publishAt']})"
        if e.get("error"):
            line += f" ERROR {e['error']}"
        if e.get("skipped"):
            line += f" [{e['skipped']}]"
        summary.append(line)
    summary.append("")
    summary.append(f"Playlist: {pl_url}")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a") as f:
        f.write("\n".join(summary) + "\n")

    log(json.dumps(results, indent=2)[:6000])
    fails = [e for e in results["videos"] if e.get("error")]
    pending = [e for e in results["videos"] if e.get("skipped") == "quota exhausted"]
    if fails and not quota_stop:
        sys.exit(1)
    if quota_stop or pending:
        sys.exit(2)
    log("ALL DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
