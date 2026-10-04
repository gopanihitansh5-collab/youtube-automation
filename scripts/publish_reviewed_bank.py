"""Manual exact-hash bank publisher. No generation or blind retries."""
import hashlib,json,os,subprocess
from pathlib import Path
import requests
from src import youtube_upload
from src.upload_ledger import UploadConflict

BANK={
 'dark-matter-corrected':('240f78db91484acf3a4d064c91bbc34d28a45d207f35b3be31897ada93523865','REVIEWED_DARK_MATTER_URL'),
 'passkeys-oct4':('3d7db25a7b988f8781a8436a9ac3f7111a08ee94e95d5287e8a5d82c064e880c','REVIEWED_PASSKEYS_URL'),
 'ai-sandbox-private':('c89c0a45076eeffeea67f40a9870d046f4d9ee40d5e6826e240212cb5d733fd0','REVIEWED_AI_SANDBOX_URL')}
UPLOAD_ONLY={'ai-sandbox-private'}  # private insert with upload scope only; no channel/dedup reads
def main():
 episode=os.environ['BANK_EPISODE'];expected,secret=BANK[episode];url=os.environ.get(secret)
 if not url:raise UploadConflict('Reviewed bank transport is not provisioned')
 # Verify encrypted runtime route before downloading or starting an insert.
 from src.private_upload_store import PrivateGitHubStore
 PrivateGitHubStore()
 root=Path('output_reviewed');root.mkdir(exist_ok=True);path=root/'final.mp4';digest=hashlib.sha256()
 try:
  response=requests.get(url,stream=True,timeout=60);response.raise_for_status()
  with path.open('wb') as stream:
   for chunk in response.iter_content(1048576):
    stream.write(chunk);digest.update(chunk)
    if stream.tell()>25000000:raise ValueError()
 except Exception:raise UploadConflict('Reviewed bank download failed') from None
 if digest.hexdigest()!=expected:raise UploadConflict('Reviewed bank hash mismatch')
 subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,timeout=300)
 meta=json.loads(Path('reviewed-bank/'+episode+'.json').read_text())
 if episode in UPLOAD_ONLY:
  result=youtube_upload.upload(str(path),meta['title'],meta['description'],meta.get('tags',[]),'private',episode_id='reviewed:'+episode,verify_readback=False)
  (root/'result.json').write_text(json.dumps({'url':result,'episode':episode,'state':'private_uploaded_readback_skipped'}))
  print('Private upload recorded:',result)
  return
 service=youtube_upload._service(extra_scopes=['https://www.googleapis.com/auth/youtube.readonly'])
 channels=service.channels().list(part='id,contentDetails',mine=True).execute().get('items',[])
 if len(channels)!=1 or channels[0]['id']!='UCslmke9cOovN4gBowddLKiA':raise UploadConflict('Channel binding mismatch')
 # Runtime duplicate check by exact title as well as uploader's durable marker.
 playlist=channels[0]['contentDetails']['relatedPlaylists']['uploads'];token=None
 for _ in range(10):
  page=service.playlistItems().list(part='snippet',playlistId=playlist,maxResults=50,pageToken=token).execute()
  matching=[i for i in page.get('items',[]) if i.get('snippet',{}).get('title')==meta['title']]
  if matching:
   from src.upload_ledger import Ledger
   store=PrivateGitHubStore();ledger=Ledger(path,'reviewed:'+episode,'/tmp/youtube-upload-ledger',store=store)
   ids={i['snippet']['resourceId']['videoId'] for i in matching}
   if not ledger.data.get('video_id') or ids!={ledger.data['video_id']}:
    raise UploadConflict('Exact title already exists without matching durable receipt; inspect, no insert')
  token=page.get('nextPageToken')
  if not token:break
 else:raise UploadConflict('Channel history incomplete; no insert')
 result=youtube_upload.upload(str(path),meta['title'],meta['description'],meta['tags'],'public',episode_id='reviewed:'+episode)
 (root/'result.json').write_text(json.dumps({'url':result,'episode':episode,'state':'public_media_verified_stack_review_pending'}))
 print('Existing or new public media verified:',result,'; full stack UI review pending')
if __name__=='__main__':main()
