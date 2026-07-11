"""Upload the finished MP4 to YouTube using a stored OAuth refresh token.

No browser needed at runtime: we mint a refresh token once locally with
scripts/get_youtube_token.py, store it as a repo secret, and exchange it for
a short-lived access token on every run.
"""
import os
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
VALID_PRIVACY = {"public", "unlisted", "private"}


def _service(scopes=None):
    """Build a YouTube API service with the given scopes (default SCOPES)."""
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
        scopes=scopes or SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def upload(path, title, description, tags, privacy="public"):
    youtube = _service()
    if not youtube:
        raise RuntimeError("YouTube secrets not configured")

    body = {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": description or "",
            "tags": tags or [],
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy if privacy in VALID_PRIVACY else "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%", flush=True)

    video_id = response["id"]

    # Pin a comment with the hook (best-effort)
    _pin_comment(youtube, video_id)

    return f"https://youtu.be/{video_id}"


def _pin_comment(youtube, video_id, text=None):
    """Pin a top-level comment on the just-uploaded video.
    Gracefully skips if the token doesn't have the 'force-ssl' scope."""
    try:
        comment_text = text or (
            "What did you think? Drop your thoughts below! "
            "Don't forget to subscribe for more daily insights \U0001f525")
        resp = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    },
                }
            },
        ).execute()
        comment_id = resp["id"]
        # Pin it
        youtube.commentThreads().update(
            part="snippet",
            body={
                "id": comment_id,
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    },
                    "isPinned": True,
                }
            },
        ).execute()
        print(f"  comment pinned: {comment_text[:50]}...", flush=True)
    except Exception as e:
        err = str(e)
        if "insufficient" in err.lower() or "scope" in err.lower() or "403" in err:
            print(f"  comment pinning unavailable (re-authenticate with new scopes)")

        else:
            print(f"  comment pinning failed: {err}", flush=True)
