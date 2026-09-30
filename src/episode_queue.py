"""Fail-closed selection of scheduled, immutable-master Shorts.

This module selects work, never authorizes publishing. Legacy rows are inert.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

BASE_HEADERS = ('topic', 'voice', 'privacy', 'status', 'youtube_url', 'date_posted',
                'script_title', 'script_desc', 'script_tags', 'script_hook')
MANAGED_HEADERS = ('episode_id', 'type', 'publish_at', 'timezone', 'manifest_ref',
                   'manifest_sha256', 'master_sha256')
HELD = {'production_hold', 'awaiting_master', 'awaiting_review', 'failed', 'posted', 'done'}
SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
SHA256 = re.compile(r'^[a-f0-9]{64}$')



class QueueBlocked(RuntimeError):
    """Sanitized blocker. Never include row contents or private references."""


def publish_time(value, zone):
    if zone != 'Asia/Calcutta':
        raise QueueBlocked('episode_timezone_invalid')
    try:
        stamp = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise QueueBlocked('episode_publish_time_invalid') from None
    if stamp.tzinfo is None or stamp.utcoffset() != stamp.astimezone(ZoneInfo(zone)).utcoffset():
        raise QueueBlocked('episode_publish_offset_invalid')
    return stamp


def select_episode(values, now=None):
    if not values:
        raise QueueBlocked('sheet_empty')
    headers = [str(v).strip().lower() for v in values[0]]
    if len(headers) != len(set(headers)) or headers[:10] != list(BASE_HEADERS):
        raise QueueBlocked('sheet_schema_invalid')
    rows = []
    ids = set()
    for idx, cells in enumerate(values[1:], 2):
        if not any(str(v).strip() for v in cells):
            continue
        row = {h: str(cells[i] if i < len(cells) else '').strip() for i, h in enumerate(headers)}
        episode_id = row.get('episode_id', '')
        if not episode_id:
            if row.get('status', '').lower() not in HELD:
                raise QueueBlocked('unmanaged_active_row')
            continue
        if not SAFE_ID.fullmatch(episode_id) or episode_id in ids:
            raise QueueBlocked('episode_id_invalid_or_duplicate')
        ids.add(episode_id)
        if row.get('type', '').lower() != 'short':
            raise QueueBlocked('managed_episode_type_invalid')
        state = row.get('status', '').lower()
        if state == 'uploading':
            raise QueueBlocked('upload_reconciliation_required')
        if state in HELD:
            continue
        if state != 'ready_to_publish':
            raise QueueBlocked('episode_state_invalid')
        if not set(MANAGED_HEADERS).issubset(headers):
            raise QueueBlocked('managed_schema_missing')
        due = publish_time(row['publish_at'], row['timezone'])
        if row['privacy'].lower() != 'public' or row['voice'] != 'af_heart':
            raise QueueBlocked('episode_publication_parameters_invalid')
        if not SAFE_ID.fullmatch(row['manifest_ref']) or not all(SHA256.fullmatch(row[k]) for k in ('manifest_sha256', 'master_sha256')):
            raise QueueBlocked('episode_master_binding_invalid')
        if row.get('youtube_url') or row.get('youtube_video_id'):
            raise QueueBlocked('upload_reconciliation_required')
        rows.append((due, idx, row))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise QueueBlocked('clock_offset_missing')
    due_rows = sorted((due, idx, row) for due, idx, row in rows if due <= now)
    if not due_rows:
        return None
    _, idx, row = due_rows[0]
    return {'row_idx': idx, 'source': 'google-sheet', **row, 'managed_episode': True}


def verify_manifest(raw, row, expected_channel_id, verified_owner_evidence):
    """Verify exact immutable bytes and content binding; no network or effects."""
    if not expected_channel_id:
        raise QueueBlocked('channel_binding_unconfigured')
    if not verified_owner_evidence:
        raise QueueBlocked('owner_grant_unconfigured')
    if len(raw) > 256000 or hashlib.sha256(raw).hexdigest() != row['manifest_sha256']:
        raise QueueBlocked('manifest_hash_invalid')
    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError):
        raise QueueBlocked('manifest_json_invalid') from None
    if not isinstance(manifest, dict):
        raise QueueBlocked('manifest_shape_invalid')
    for key in ('episode_id', 'topic', 'publish_at', 'timezone', 'master_sha256'):
        if manifest.get(key) != row.get(key):
            raise QueueBlocked('manifest_row_binding_invalid')
    if manifest.get('channel_id') != expected_channel_id:
        raise QueueBlocked('manifest_channel_invalid')
    if manifest.get('privacy') != 'public' or manifest.get('voice') != 'af_heart':
        raise QueueBlocked('manifest_publication_parameters_invalid')
    if not SAFE_ID.fullmatch(str(manifest.get('master_ref', ''))):
        raise QueueBlocked('manifest_master_ref_invalid')
    metadata = manifest.get('metadata', {})
    if not isinstance(metadata, dict) or not all(isinstance(metadata.get(k), str) and metadata[k].strip() for k in ('title', 'description')) or not isinstance(metadata.get('tags'), list) or not all(isinstance(v, str) for v in metadata['tags']):
        raise QueueBlocked('manifest_metadata_invalid')
    if not isinstance(manifest.get('source_evidence'), list) or not manifest['source_evidence']:
        raise QueueBlocked('manifest_source_evidence_missing')
    evidence = manifest.get('owner_evidence', [])
    if not isinstance(evidence, list) or not all(isinstance(v, str) for v in evidence) or not set(verified_owner_evidence).issubset(set(evidence)):
        raise QueueBlocked('manifest_owner_evidence_missing')
    qc = manifest.get('qc', {})
    if not isinstance(qc, dict) or any(qc.get(k) is not True for k in ('frames_inspected', 'audio_inspected', 'real_generated_motion', 'facts_checked', 'final_cut_checked')):
        raise QueueBlocked('manifest_qc_missing')
    duration = qc.get('duration_seconds')
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 10 <= duration <= 30 or qc.get('master_sha256') != row['master_sha256']:
        raise QueueBlocked('manifest_qc_master_invalid')
    return manifest


def verify_master(raw, row):
    if hashlib.sha256(raw).hexdigest() != row['master_sha256']:
        raise QueueBlocked('master_hash_invalid')
