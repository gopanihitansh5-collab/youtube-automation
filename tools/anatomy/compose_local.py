"""Opt-in local authored asset composition. Never selected by a scene planner."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess


def validate(asset, manifest, duration):
    asset = Path(asset).resolve(strict=True)
    if asset.suffix.lower() != '.mp4':
        raise ValueError('Only a rendered local MP4 is accepted')
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Duration must be positive and finite')
    if manifest.get('asset_type') != 'anatomy-authored-illustration':
        raise ValueError('Asset needs explicit illustration provenance')
    for key in ('source_url', 'source_commit', 'license', 'illustration_limits'):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError('Missing provenance: ' + key)
    if hashlib.sha256(asset.read_bytes()).hexdigest() != manifest.get('sha256'):
        raise ValueError('Asset hash mismatch')
    data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', str(asset)], timeout=30))
    videos = [s for s in data['streams'] if s['codec_type'] == 'video']
    if len(videos) != 1:
        raise ValueError('Exactly one video stream required')
    video = videos[0]
    if video['width'] * 16 != video['height'] * 9:
        raise ValueError('Vertical adapter requires exact 9:16, no silent crop')
    frames = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
        '-select_streams', 'v:0', '-show_frames', '-show_entries',
        'frame=best_effort_timestamp_time,pkt_duration_time,duration_time',
        '-of', 'json', str(asset)], timeout=60)).get('frames', [])
    spans = []
    for frame in frames:
        start = float(frame['best_effort_timestamp_time'])
        length = float(frame.get('duration_time', frame.get('pkt_duration_time', 0)))
        if not math.isfinite(start) or not math.isfinite(length) or length <= 0:
            raise ValueError('Unverifiable decoded frame timing')
        spans.append((start, start+length))
    if not spans or any(b[0] < a[0] or b[0] > a[1]+0.001 for a,b in zip(spans, spans[1:])):
        raise ValueError('Missing, unordered or gapped decoded video frames')
    picture_span = spans[-1][1] - spans[0][0]
    if duration > picture_span + 0.001:
        raise ValueError('Asset too short, no silent looping')
    return asset


def compose(asset, manifest, duration, output):
    asset = validate(asset, manifest, duration)
    output = Path(output).resolve()
    if output == asset or output.exists() or output.with_suffix('.receipt.json').exists():
        raise ValueError('Output must be a new path, never replace reviewed assets')
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('anatomy_shorts_editor', repo/'src'/'editor.py')
    editor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(editor)
    # Existing local-video normalization, not authored_diagram or stock generation.
    editor._normalize((str(asset), 'video', 'anatomy-authored-illustration'), duration, str(output), 0)
    receipt = {'asset_type': manifest['asset_type'], 'input_sha256': manifest['sha256'],
        'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'duration_seconds': duration, 'composition': 'existing-shorts-local-video-normalizer',
        'publication_clearance': False, 'audio': 'discarded; narration composed separately'}
    output.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--duration', required=True, type=float)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    compose(args.asset, json.loads(Path(args.manifest).read_text()), args.duration, args.output)
