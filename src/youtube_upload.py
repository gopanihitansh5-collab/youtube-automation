"""Upload the finished MP4 to YouTube using a stored OAuth refresh token.

No browser needed at runtime: we mint a refresh token once locally with
scripts/get_youtube_token.py, store it as a repo secret, and exchange it for
a short-lived access token on every run.

Comment pinning uses a SEPARATE service instance (with force-ssl scope) so it
gracefully degrades when the token only has youtube.upload scope.
"""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
VALID_PRIVACY = {"public", "unlisted", "private"}


def _service(extra_scopes=None):
    """Build a YouTube API service with upload scope + optional extras."""
    refresh = os.environ.get("YT_REFRESH_TOKEN")
    cid = os.environ.get("YT_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET")
    if not all([refresh, cid, secret]):
        return None
    scopes = list(SCOPES)
    if extra_scopes:
        scopes.extend(extra_scopes)
    creds = Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )
    return build("youtube", "v3", credentials=creds)


def upload(path, title, description, tags, privacy="public", hook=None, comment=None):
    youtube = _service()
    if not youtube:
        raise RuntimeError("YouTube secrets not configured")

    desc = (description or "").strip()
    if not desc:
        desc = f"{title}\n\n#shorts #{' #'.join((tags or [])[:5])}"

    body = {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": desc,
            "tags": tags or [],
            "categoryId": "22",
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

    _pin_comment(video_id, text=comment or hook or "What did you think? Drop your thoughts below!")

    return f"https://youtu.be/{video_id}"


def _pin_comment(video_id, text=None):
    """Pin a comment on the uploaded video (separate service with force-ssl).
    Gracefully skips if the token only has youtube.upload scope."""
    if not text:
        text = "What did you think? Drop your thoughts below!"
    try:
        svc = _service(extra_scopes=[
            "https://www.googleapis.com/auth/youtube.force-ssl"])
        if not svc:
            return
        resp = svc.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text}
                    },
                }
            },
        ).execute()
        cid = resp["id"]
        print(f"  comment posted: {text[:50]}...", flush=True)
        try:
            svc.commentThreads().update(
                part="snippet",
                body={
                    "id": cid,
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {"snippet": {"textOriginal": text}},
                        "isPinned": True,
                    }
                },
            ).execute()
            print(f"  comment pinned", flush=True)
        except AttributeError:
            print(f"  comment pinning not supported by this API version — comment posted unpinned", flush=True)
    except Exception as e:
        err = str(e)
        if any(k in err.lower() for k in ("insufficient", "scope", "403", "invalid_scope")):
            print(f"  comment pinning: token lacks force-ssl scope (re-auth needed)")
        else:
            print(f"  comment pinning failed: {err}", flush=True)
