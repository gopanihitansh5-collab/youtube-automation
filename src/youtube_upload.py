"""Upload the finished MP4 to YouTube using a stored OAuth refresh token.

No browser needed at runtime: we mint a refresh token once locally with
scripts/get_youtube_token.py, store it as a repo secret, and exchange it for
a short-lived access token on every run.

Comment pinning uses a SEPARATE service instance (with force-ssl scope) so it
gracefully degrades when the token only has youtube.upload scope.
"""
import os
import time
from src.upload_ledger import Ledger, RecordingHttp, UploadConflict
from src.private_upload_store import PrivateGitHubStore
import requests as req_lib

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


def upload(path, title, description, tags, privacy="public", hook=None, comment=None, episode_id=None, ledger_dir=None):
    youtube = _service()
    if not youtube:
        raise RuntimeError("YouTube secrets not configured")

    store = PrivateGitHubStore()
    ledger = Ledger(path, episode_id or title, ledger_dir or os.environ.get("YT_UPLOAD_LEDGER_DIR", "/tmp/youtube-upload-ledger"), store=store)
    if ledger.data.get("video_id"):
        _verify_ready(youtube, ledger.data["video_id"], privacy, ledger)
        return "https://youtu.be/" + ledger.data["video_id"]
    if ledger.data and not ledger.data.get("session_uri"):
        video_id = _reconcile_existing(ledger)
        ledger.save(video_id=video_id, state="reconciled")
        _verify_ready(youtube, video_id, privacy, ledger)
        return "https://youtu.be/" + video_id

    desc = (description or "").strip()
    if not desc:
        desc = f"{title}\n\n#shorts #{' #'.join((tags or [])[:5])}"

    body = {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": desc,
            "tags": list(dict.fromkeys((tags or []) + [ledger.marker])),
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy if privacy in VALID_PRIVACY else "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(path, chunksize=8*1024*1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    if ledger.data.get("session_uri"):
        request.resumable_uri = ledger.data["session_uri"]
        request.resumable_progress = ledger.data.get("progress", 0)
        request._in_error_state = True
    else:
        ledger.save(state="initiating", privacy=privacy, title=title)
    http = RecordingHttp(request.http, ledger)
    response = None
    try:
        while response is None:
            status, response = request.next_chunk(http=http)
            ledger.save(progress=request.resumable_progress)
            if status:
                print(f"  upload {int(status.progress() * 100)}%", flush=True)
    except Exception as exc:
        ledger.save(state="needs_reconciliation")
        if getattr(getattr(exc, "resp", None), "status", None) == 409:
            video_id = _reconcile_existing(ledger)
            response = {"id": video_id}
        else:
            raise UploadConflict("Upload paused; private receipt retained. Do not start a new insert.") from None
    video_id = response["id"]
    ledger.save(video_id=video_id, state="uploaded")
    _verify_ready(youtube, video_id, privacy, ledger)

    # Pinning is not exposed by the YouTube Data API. UI review owns the
    # sourced comment and pin, never an unsupported isPinned write.
    ledger.save(publication_state="public_media_verified_stack_review_pending")

    return f"https://youtu.be/{video_id}"


def _reconcile_existing(ledger):
    """Only an exact durable episode marker can bind an existing entity."""
    try:
        service = _service(extra_scopes=["https://www.googleapis.com/auth/youtube.readonly"])
        channels = service.channels().list(part="contentDetails", mine=True).execute()["items"]
        if len(channels) != 1:
            raise UploadConflict("Channel identity ambiguous")
        playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids = []
        token = None
        for _ in range(5):
            page = service.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50, pageToken=token).execute()
            ids.extend(item["contentDetails"]["videoId"] for item in page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                break
        matches = []
        for offset in range(0, len(ids), 50):
            videos = service.videos().list(part="snippet", id=",".join(ids[offset:offset+50])).execute()
            matches.extend(v["id"] for v in videos.get("items", []) if ledger.marker in v.get("snippet", {}).get("tags", []))
        if len(matches) == 1:
            return matches[0]
    except Exception:
        pass
    raise UploadConflict("Existing entity could not be uniquely reconciled; no new insert allowed")


def _verify_ready(service, video_id, privacy, ledger):
    for attempt in range(6):
        response = service.videos().list(part="status,processingDetails", id=video_id).execute()
        items = response.get("items", [])
        if len(items) != 1:
            raise UploadConflict("Upload entity could not be read back")
        status = items[0].get("status", {})
        processing = items[0].get("processingDetails", {}).get("processingStatus")
        if status.get("uploadStatus") == "processed" and processing in (None, "succeeded") and status.get("privacyStatus") == privacy:
            ledger.save(state="processed", privacy=privacy)
            if privacy == "public" and not (ledger.data.get("public_verified_video_id") == video_id and ledger.data.get("public_verified_sha256") == ledger.sha256):
                from src.public_media_check import verify
                proof = verify(video_id, ledger.source_path)
                ledger.save(public_verified_video_id=video_id, public_verified_sha256=ledger.sha256,
                            public_media_proof=proof, publication_state="public_media_verified_stack_review_pending")
            return
        if processing in ("failed", "terminated") or status.get("uploadStatus") in ("failed", "rejected", "deleted"):
            raise UploadConflict("Existing upload failed processing; inspect before recovery")
        if attempt < 5:
            time.sleep(30)
    raise UploadConflict("Existing video is still processing; receipt retained, no new upload")
