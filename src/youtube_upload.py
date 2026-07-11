"""Upload the finished MP4 to YouTube using a stored OAuth refresh token.

No browser needed at runtime: we mint a refresh token once locally with
scripts/get_youtube_token.py, store it as a repo secret, and exchange it for
a short-lived access token on every run.
"""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
VALID_PRIVACY = {"public", "unlisted", "private"}


def upload(path, title, description, tags, privacy="public"):
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    youtube = build("youtube", "v3", credentials=creds)

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
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%", flush=True)

    return f"https://youtu.be/{response['id']}"
