"""One-time private EP02 staging upload. Never print the archive URL."""
import hashlib
import os
import pathlib
import urllib.request
import zipfile
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

EXPECTED = '90cace87e6651f788bfb25819a1b816a303c2de68a6034cbdb70a0436167d697'
CHANNEL = 'UCslmke9cOovN4gBowddLKiA'
for key in ('DATASET_URL', 'YT_CLIENT_ID', 'YT_CLIENT_SECRET', 'YT_REFRESH_TOKEN'):
    if not os.environ.get(key):
        raise RuntimeError(f'Missing {key}')
url = os.environ['DATASET_URL']
if not url.startswith('https://storage.googleapis.com:443/kaggle-data-sets/'):
    raise RuntimeError('Unexpected archive host')
archive = pathlib.Path('/tmp/ep02-private-dataset.zip')
try:
    with urllib.request.urlopen(url, timeout=180) as response, archive.open('wb') as output:
        while block := response.read(2 * 1024 * 1024):
            output.write(block)
except Exception:
    raise RuntimeError('Private archive download failed; no URL logged') from None
with zipfile.ZipFile(archive) as z:
    names = [n for n in z.namelist() if pathlib.PurePosixPath(n).name == 'final.mp4']
    if len(names) != 1:
        raise RuntimeError('Expected exactly one final.mp4')
    video = pathlib.Path('/tmp/ep02-corrected-final.mp4')
    with z.open(names[0]) as source, video.open('wb') as target:
        while block := source.read(2 * 1024 * 1024):
            target.write(block)
with video.open('rb') as source:
    digest = hashlib.file_digest(source, 'sha256').hexdigest()
if digest != EXPECTED or video.stat().st_size != 83890655:
    raise RuntimeError('Video integrity mismatch')
print(f'Video verified: {digest}, {video.stat().st_size} bytes', flush=True)
creds = Credentials(token=None, refresh_token=os.environ['YT_REFRESH_TOKEN'],
                    client_id=os.environ['YT_CLIENT_ID'], client_secret=os.environ['YT_CLIENT_SECRET'],
                    token_uri='https://oauth2.googleapis.com/token')
yt = build('youtube', 'v3', credentials=creds)
try:
    mine = yt.channels().list(part='id', mine=True).execute().get('items', [])
except Exception as exc:
    if getattr(getattr(exc, 'resp', None), 'status', None) != 403:
        raise RuntimeError('OAuth channel check failed before upload') from None
    print('Channel read forbidden by upload-only grant; private upload needs Studio identity check', flush=True)
else:
    if len(mine) != 1 or mine[0].get('id') != CHANNEL:
        raise RuntimeError('OAuth channel does not match Alpha Explorer')
    print('Verified Alpha Explorer OAuth channel', flush=True)
request = yt.videos().insert(part='snippet,status', body={
    'snippet': {'title': 'Nvidia explained - corrected EP02',
                'description': 'Private staging for Alpha Explorer EP02. Metadata pending review.',
                'categoryId': '28'},
    'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False},
}, media_body=MediaFileUpload(str(video), mimetype='video/mp4', resumable=True,
                             chunksize=8 * 1024 * 1024))
response = None
while response is None:
    status, response = request.next_chunk(num_retries=0)
    if status:
        print(f'Upload progress: {status.progress():.1%}', flush=True)
video_id = response['id']
print(f'PRIVATE_VIDEO_ID={video_id}', flush=True)
print(f'EXPECTED_CHANNEL_ID={CHANNEL}', flush=True)
print(f'PRIVATE_VIDEO_STATUS={response.get("status", {}).get("privacyStatus")}', flush=True)
if response.get('status', {}).get('privacyStatus') != 'private':
    raise RuntimeError('Upload response did not confirm private')
