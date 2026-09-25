"""One-off batch upload: 'How AI Agents Actually Work' series (14 videos).

Runs in GitHub Actions; workflow + this file are removed after success.
Auth: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN repo secrets, same
refresh-token pattern as the daily pipeline (src/youtube_upload.py). The
stored refresh token carries ONLY the youtube.upload scope (confirmed: a
refresh requesting upload+force-ssl fails with invalid_scope), so this
script deliberately makes NO read or playlist API calls - those need
youtube.force-ssl. videos.insert responses themselves provide the upload
status + publishAt echo used for verification.

Resumable: after every insert, progress is written to
output/series-results.json; the workflow caches that file (actions/cache)
so a re-run after a quota reset skips completed videos and continues the
hourly publishAt chain. Secrets are never printed.
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

UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
CHANNEL_URL = "https://www.youtube.com/@The4FutureLens"
WORK = "/tmp/series"
RESULTS = "output/series-results.json"
PLAYLIST_TITLE = "How AI Agents Actually Work | 12-Part AI Explainer"
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
        scopes=UPLOAD_SCOPE,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def load_progress():
    if os.path.exists(RESULTS):
        try:
            with open(RESULTS) as f:
                return json.load(f)
        except Exception:
            pass
    return {"videos": [], "playlist_url": None,
            "playlist_status": "deferred: refresh token has upload-only scope "
                               "(force-ssl needed); create playlist after re-auth"}


def save(results):
    os.makedirs("output", exist_ok=True)
    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2)


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
    return resp


def is_quota(e):
    return e.status_code == 403 and "quota" in str(e.error_details or e).lower()


def substitute(desc, land_url):
    return (desc.replace("{FULL_VIDEO_URL}", land_url)
                .replace("{LANDSCAPE_VIDEO_URL}", land_url)
                .replace("{PLAYLIST_URL}", CHANNEL_URL))


def main():
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            log(f"MISSING SECRET: {k}")
            sys.exit(1)
    yt = service()
    results = load_progress()
    done = {e["title"]: e for e in results["videos"] if e.get("video_id")}
    if done:
        log(f"resuming: {len(done)} videos already uploaded")

    download_all()

    parts = [v for v in VIDEOS if v["kind"] == "part"]
    final = [v for v in VIDEOS if v["kind"] == "final"][0]
    quota_stop = False

    # 1) landscape final first (public immediately) - Shorts link to it
    land_url = None
    if final["title"] in done:
        land_url = done[final["title"]]["url"]
        log(f"final exists: {land_url}")
    else:
        desc = substitute(final["description"], "")
        try:
            log(f"upload FINAL: {final['title']} (public)")
            resp = upload_one(yt, final, desc)
            vid = resp["id"]
            land_url = f"https://youtu.be/{vid}"
            results["videos"].append({
                "file": final["file"], "title": final["title"], "kind": "final",
                "video_id": vid, "url": land_url,
                "privacyStatus": resp.get("status", {}).get("privacyStatus"),
                "uploadStatus": resp.get("status", {}).get("uploadStatus")})
            save(results)
            log(f"  ok: {land_url} status={resp.get('status', {}).get('uploadStatus')}")
        except HttpError as e:
            log(f"FINAL UPLOAD FAILED: {e.status_code} {e.error_details or e}")
            results["videos"].append({"file": final["file"], "title": final["title"],
                                      "kind": "final",
                                      "error": f"{e.status_code} {e.error_details or e}"})
            save(results)
            if is_quota(e):
                quota_stop = True
            else:
                sys.exit(1)

    # 2) hourly schedule chain (IST-aligned), continuing prior slots on resume
    floor = ist_hour_floor(datetime.now(timezone.utc))
    slots = {}
    prev = None
    for v in parts:
        if v["title"] in done and done[v["title"]].get("publishAt"):
            prev = parse_ts(done[v["title"]]["publishAt"])
            continue
        slot = prev + timedelta(hours=1) if prev else floor
        if slot < floor:
            slot = floor
        slots[v["title"]] = slot
        prev = slot

    # 3) parts in order (Shorts 1-12, then vertical final as slot 13)
    for v in parts:
        if v["title"] in done:
            log(f"skip (exists): Part {v['part']}")
            continue
        entry = {"file": v["file"], "title": v["title"], "kind": "part",
                 "part": v["part"]}
        if quota_stop or land_url is None:
            entry["skipped"] = "quota exhausted" if quota_stop else "final missing"
            results["videos"].append(entry)
            save(results)
            continue
        desc = substitute(v["description"], land_url)
        if "{" in desc:
            entry["error"] = "unresolved placeholder in description"
            results["videos"].append(entry)
            save(results)
            continue
        pa = fmt_ts(slots[v["title"]])
        try:
            log(f"upload Part {v['part']}: publishAt={pa}")
            resp = upload_one(yt, v, desc, publish_at=pa)
        except HttpError as e:
            log(f"PART {v['part']} FAILED: {e.status_code} {e.error_details or e}")
            entry["error"] = f"{e.status_code} {e.error_details or e}"
            results["videos"].append(entry)
            save(results)
            if is_quota(e):
                quota_stop = True
            continue
        vid = resp["id"]
        entry.update(video_id=vid, url=f"https://youtu.be/{vid}",
                     publishAt=resp.get("status", {}).get("publishAt") or pa,
                     privacyStatus=resp.get("status", {}).get("privacyStatus"),
                     uploadStatus=resp.get("status", {}).get("uploadStatus"))
        results["videos"].append(entry)
        save(results)
        log(f"  ok: https://youtu.be/{vid} status={entry['uploadStatus']}")

    save(results)
    summary = ["## Series upload results", ""]
    for e in results["videos"]:
        line = f"- {e.get('title', e['file'])}"
        if e.get("url"):
            line += f" -> {e['url']}"
        if e.get("publishAt"):
            line += f" (publishes {e['publishAt']}Z)"
        if e.get("error"):
            line += f" ERROR {e['error']}"
        if e.get("skipped"):
            line += f" [{e['skipped']}]"
        summary.append(line)
    summary.append("")
    summary.append("Playlist: " + results["playlist_status"])
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a") as f:
        f.write("\n".join(summary) + "\n")
    log(json.dumps(results, indent=2)[:6000])

    fails = [e for e in results["videos"] if e.get("error")]
    pending = [e for e in results["videos"] if e.get("skipped")]
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
