import importlib.util,tempfile,os,subprocess,json,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('editor_smoke',ROOT/'long-videos/editor_long.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
@unittest.skipUnless(os.environ.get('EDITOR_INTEGRATION'),'Set EDITOR_INTEGRATION for actual measured timeline smoke')
class EditorSmoke(unittest.TestCase):
 def test_render_boundaries_audio_captions_and_chapters(self):
  with tempfile.TemporaryDirectory() as temp:
   cwd=os.getcwd();os.chdir(temp)
   try:
    video=Path(temp)/'visual.mp4';audio=Path(temp)/'voice.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=24:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1','-ar','48000',str(audio)],check=True)
    chapters=[{'title':'One','scenes':[{}]},{'title':'Two','scenes':[{}]}]
    with patch.object(e,'W',320),patch.object(e,'H',180),patch.object(e,'_font',return_value=None),patch.object(e,'_pick_music',return_value=None):
     out=e.build(chapters,[(str(video),'video','test')]*2,[str(audio)]*2,[[('hello',0,0.7)]]*2,[[1],[1]],'','output_long/final.mp4')
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_chapters','-show_format','-of','json',out]));self.assertAlmostEqual(float(data['format']['duration']),8,places=1)
    self.assertEqual([float(c['start_time']) for c in data['chapters']],[0,4])
    subs=Path('output_long/subs.ass').read_text();self.assertIn('0:00:03.00',subs);self.assertIn('0:00:07.00',subs)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',out,'-f','null','-'],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-ss','3.3','-i',out,'-frames:v','1','/tmp/editor-smoke-proof.jpg'],check=True)
   finally:os.chdir(cwd)
