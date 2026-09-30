"""Private pinned-master transport and durable upload state.

No generation fallback. Runtime configuration is required and publication stays
blocked until source-grounded channel/bank/grant and full publish stack exist.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from .episode_queue import QueueBlocked, publish_time

READONLY_DRIVE = 'https://www.googleapis.com/auth/drive.readonly'
READONLY_YOUTUBE = 'https://www.googleapis.com/auth/youtube.readonly'
UPLOAD_YOUTUBE = 'https://www.googleapis.com/auth/youtube.upload'
STATE_HEADERS = ('youtube_video_id', 'upload_attempt_id', 'upload_started_at')


class PrivateBank:
    def __init__(self, drive, folder_id):
        if not folder_id:
            raise QueueBlocked('private_bank_unconfigured')
        self.drive, self.folder_id = drive, folder_id

    def _private(self, file_id):
        permissions = self.drive.permissions().list(fileId=file_id, fields='permissions(type,role)').execute().get('permissions', [])
        if not permissions or any(p.get('type') in ('anyone', 'domain') for p in permissions):
            raise QueueBlocked('private_bank_access_invalid')

    def _metadata(self, file_id, mime):
        meta = self.drive.files().get(fileId=file_id, fields='id,mimeType,size,parents,trashed').execute()
        if meta.get('trashed') or meta.get('mimeType') != mime or self.folder_id not in meta.get('parents', []):
            raise QueueBlocked('private_bank_file_invalid')
        self._private(self.folder_id)
        self._private(file_id)
        return meta

    def manifest(self, file_id):
        meta = self._metadata(file_id, 'application/json')
        if int(meta.get('size', 0)) > 256000:
            raise QueueBlocked('manifest_size_invalid')
        raw = self.drive.files().get_media(fileId=file_id).execute()
        if not isinstance(raw, bytes) or len(raw) > 256000:
            raise QueueBlocked('manifest_size_invalid')
        return raw

    def master(self, file_id, expected_hash, target):
        meta = self._metadata(file_id, 'video/mp4')
        size = int(meta.get('size', 0))
        if not 0 < size <= 250000000:
            raise QueueBlocked('master_size_invalid')
        from googleapiclient.http import MediaIoBaseDownload
        with open(target, 'wb') as out:
            os.chmod(target, 0o600)
            download = MediaIoBaseDownload(out, self.drive.files().get_media(fileId=file_id), chunksize=1048576)
            done = False
            while not done:
                _, done = download.next_chunk(num_retries=0)
                if out.tell() > 250000000:
                    raise QueueBlocked('master_size_invalid')
        if Path(target).stat().st_size != size or file_hash(target) != expected_hash:
            raise QueueBlocked('master_hash_invalid')


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_media(path, manifest):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        streams = data['streams']
        video = next(s for s in streams if s.get('codec_type') == 'video')
        audio = next(s for s in streams if s.get('codec_type') == 'audio')
        if not 10 <= duration <= 30 or abs(duration - manifest['qc']['duration_seconds']) > 0.5:
            raise ValueError()
        if int(video['width']) >= int(video['height']) or int(audio.get('channels', 0)) < 1:
            raise ValueError()
    except Exception:
        raise QueueBlocked('master_media_contract_invalid') from None
    # Container checks do not replace the source-grounded frame/audio review.


class SheetLedger:
    def __init__(self, worksheet):
        self.ws = worksheet

    def read(self, episode_id):
        values = self.ws.get_all_values()
        headers = [str(h).strip().lower() for h in values[0]] if values else []
        if len(headers) != len(set(headers)) or not set(STATE_HEADERS).issubset(headers):
            raise QueueBlocked('upload_ledger_schema_missing')
        matches = []
        for idx, cells in enumerate(values[1:], 2):
            row = {h: str(cells[i] if i < len(cells) else '').strip() for i, h in enumerate(headers)}
            if row.get('episode_id') == episode_id:
                matches.append((idx, headers, row, cells))
        if len(matches) != 1:
            raise QueueBlocked('upload_ledger_identity_invalid')
        return matches[0]

    def transition(self, original, expected_state, updates):
        idx, headers, live, cells = self.read(original['episode_id'])
        for key in ('episode_id','topic','type','publish_at','timezone','manifest_ref','manifest_sha256','master_sha256','voice','privacy'):
            if live.get(key) != original.get(key):
                raise QueueBlocked('episode_changed_before_commit')
        if live['status'] != expected_state or any(k not in headers for k in updates):
            raise QueueBlocked('upload_ledger_state_invalid')
        row = [live.get(h, '') for h in headers]
        for k, v in updates.items():
            row[headers.index(k)] = str(v)
        # One API write, then exact readback. No warning-and-continue path.
        self.ws.update(values=[row], range_name=f'A{idx}', value_input_option='RAW')
        _, _, checked, _ = self.read(original['episode_id'])
        if any(checked.get(k) != str(v) for k, v in updates.items()):
            raise QueueBlocked('upload_ledger_write_unverified')
        return checked


def verify_channel(youtube, expected_id):
    channels = youtube.channels().list(part='id', mine=True).execute().get('items', [])
    if len(channels) != 1 or channels[0].get('id') != expected_id:
        raise QueueBlocked('youtube_channel_mismatch')


def verify_uploaded(youtube, video_id, manifest):
    items = youtube.videos().list(part='snippet,status', id=video_id).execute().get('items', [])
    if len(items) != 1:
        raise QueueBlocked('youtube_upload_readback_missing')
    video = items[0]; snippet = video.get('snippet', {}); status = video.get('status', {})
    metadata = manifest['metadata']
    if (snippet.get('channelId') != manifest['channel_id'] or snippet.get('title') != metadata['title']
            or snippet.get('description') != metadata['description']
            or snippet.get('tags', []) != metadata['tags'] or status.get('privacyStatus') != 'public'
            or status.get('uploadStatus') not in ('uploaded','processed')):
        raise QueueBlocked('youtube_upload_readback_mismatch')


def commit_master(ledger, row, manifest, path, youtube, now, uploader):
    """Effect-bearing API requires an independently prepared reviewed proposal."""
    if now < publish_time(row['publish_at'],row['timezone']):
        raise QueueBlocked('episode_not_due')
    verify_channel(youtube, manifest['channel_id'])
    attempt = uuid.uuid4().hex
    ledger.transition(row, 'ready_to_publish', {'status':'uploading','upload_attempt_id':attempt,
                       'upload_started_at':now.isoformat(),'youtube_video_id':''})
    # An ambiguous insert/network failure leaves uploading, never retries insertion.
    video_id = uploader(youtube, path, manifest['metadata'])
    if not isinstance(video_id, str) or not __import__('re').fullmatch(r'[A-Za-z0-9_-]{11}',video_id):
        raise QueueBlocked('youtube_upload_id_invalid')
    ledger.transition(row, 'uploading', {'youtube_video_id':video_id})
    verify_uploaded(youtube, video_id, manifest)
    ledger.transition(row, 'uploading', {'status':'posted','youtube_url':'https://youtu.be/'+video_id,
                       'date_posted':now.astimezone(__import__('zoneinfo').ZoneInfo(row['timezone'])).date().isoformat()})
    return video_id


def reconcile_known_upload(ledger, row, manifest, youtube, now):
    _, _, live, _ = ledger.read(row['episode_id'])
    if live['status'] != 'uploading' or not live.get('youtube_video_id'):
        raise QueueBlocked('upload_reconciliation_required')
    verify_channel(youtube,manifest['channel_id']);verify_uploaded(youtube,live['youtube_video_id'],manifest)
    ledger.transition(row,'uploading',{'status':'posted','youtube_url':'https://youtu.be/'+live['youtube_video_id'],
                      'date_posted':now.astimezone(__import__('zoneinfo').ZoneInfo(row['timezone'])).date().isoformat()})
    return live['youtube_video_id']


def run_managed_episode(item):
    # Adapters above are testable, but must not create approval from a Sheet,
    # manifest, or config self-claim. Activation awaits grounded private bank,
    # channel, grant and the rest of the owner's required publish stack.
    raise QueueBlocked('managed_publication_activation_pending')
