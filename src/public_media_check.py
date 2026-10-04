"""Bounded anonymous public-media proof. Does not claim caption/pin review."""
import datetime,json,subprocess,tempfile
from pathlib import Path
from src.upload_ledger import UploadConflict

def verify(video_id,source_path):
    if not video_id or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in video_id):
        raise UploadConflict('Invalid video identity; review required')
    def run(args,timeout=180):
        try:return subprocess.run(args,check=True,capture_output=True,timeout=timeout).stdout
        except Exception:raise UploadConflict('Public served-media verification failed; no new upload allowed') from None
    def duration(path):
        data=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],30))
        types={s.get('codec_type') for s in data.get('streams',[])}
        if not {'video','audio'}.issubset(types):raise UploadConflict('Public media missing video/audio')
        return float(data['format']['duration'])
    with tempfile.TemporaryDirectory(prefix='public-media-proof-') as temp:
        target=Path(temp)/'served.mp4'
        run(['yt-dlp','--no-playlist','--no-progress','--no-warnings','--retries','1','--socket-timeout','20','-f','worstvideo+worstaudio/worst','--merge-output-format','mp4','--remux-video','mp4','-o',str(target),'https://www.youtube.com/watch?v='+video_id],240)
        served=duration(target);source=duration(source_path)
        if abs(served-source)>max(1.0,source*.01):raise UploadConflict('Public media duration mismatch; review required')
        run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],240)
        run(['ffmpeg','-v','error','-i',str(target),'-vf','fps=1/10,scale=160:90','-an','-f','framemd5',str(Path(temp)/'frames.md5')],120)
        rows=[r for r in (Path(temp)/'frames.md5').read_text().splitlines() if not r.startswith('#')]
        hashes={r.rsplit(',',1)[-1].strip() for r in rows}
        if source>20 and len(hashes)<2:raise UploadConflict('Public video lacks changing decoded frames; review required')
        return {'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'served_duration_sec':served,'decoded_frame_hashes':len(hashes),'anonymous':True}
