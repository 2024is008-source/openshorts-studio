from pathlib import Path
import sys,os,json,subprocess,time,copy
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['OPENSHORTS_LEARNING_DISABLED']='1'
import auto_edit as a,caption_renderer as captions,export_quality as quality
OUT=ROOT/'build/reference-study-009/validation'
def run(cmd):return subprocess.run(cmd,check=True,capture_output=True,timeout=120)
speech=OUT/'speech.wav';duration=float(json.loads(run(['ffprobe','-v','error','-show_format','-of','json',str(speech)]).stdout)['format']['duration'])
from faster_whisper import WhisperModel
model=WhisperModel(str(next((ROOT/'OpenShorts Library/models/whisper-small-pinned').glob('*'))),device='cpu',compute_type='int8',cpu_threads=6,local_files_only=True)
segments,_=model.transcribe(str(speech),word_timestamps=True,language='en');transcript={'segments':[dict(start=s.start,end=s.end,text=s.text,words=[dict(word=w.word,start=w.start,end=w.end,aligned=True) for w in s.words]) for s in segments]}
from subtitles import merge_continuation_words
transcript=json.loads(json.dumps(transcript))
for segment in transcript['segments']:segment['words']=merge_continuation_words(segment['words'])
(OUT/'transcript.json').write_text(json.dumps(transcript,indent=2))
source=OUT/'synthetic.mp4'
run(['ffmpeg','-y','-v','error','-f','lavfi','-i',f'testsrc2=size=360x640:rate=24:duration={duration}', '-i',str(speech),'-c:v','libx264','-preset','fast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)])
words=[dict(text=w['word'].strip(),start=w['start'],end=w['end'],source_start=w['start'],source_end=w['end'],aligned=True,segment_index=0) for s in transcript['segments'] for w in s['words'] if w['end']>w['start']]
plan=dict(source_ref=source.name,duration=duration,kind='challenge',evidence={'category_selection':{'primary_category':'challenge','subcategory':'general'}},segments=[dict(source_start=0.,source_end=duration)],captions=words,shots=[dict(start=0.,end=duration,source_start=0.,source_end=duration,renderer='TRACK',faces=[dict(x=160.,y=210.,width=35.,height=45.)],protected_regions=[],keyframes=[dict(time=0.,x=0.,y=0.,width=360.,height=640.)])])
# This generated chart has a known central region, not a claimed human reaction.
# Number emphasis exercises automatic detection; camera adapter is a separate
# explicitly authored synthetic control and is not mislabeled as AI evidence.
settings=a.generate(plan);(OUT/'automatic-plan.json').write_text(json.dumps(settings,indent=2))
assert any(e['type']=='number_highlight' for e in a.active(settings))
base=a.defaults();base['scenes']=settings['scenes']
receipts=[]
for label,config in [('baseline',base),('skills',settings)]:
 ass=OUT/(label+'.ass');captions.generate(a.emphasize(transcript,config),0,duration,str(ass),width=360,height=640,preset='clean-minimal',effect='none',auto_effects=a.active(config))
 # Run in the artifact directory to avoid drive-colon escaping in ASS filter.
 for encoder,args in [('cpu',['-c:v','libx264','-preset','fast']),('nvenc',['-c:v','h264_nvenc','-preset','p4'])]:
  target=OUT/f'{label}-{encoder}.mp4';start=time.perf_counter()
  command=['ffmpeg','-y','-v','error','-i',source.name,'-vf',f'ass={ass.name}','-threads','2','-filter_threads','1',*args,'-pix_fmt','yuv420p','-c:a','copy',target.name]
  p=subprocess.run(command,cwd=OUT,capture_output=True,timeout=120)
  if p.returncode:
   receipts.append(dict(label=label,encoder=encoder,status='unavailable',error=p.stderr.decode(errors='replace')[-500:]));continue
  elapsed=time.perf_counter()-start
  report=quality.validate(target,label,quality.expectations(quality.probe(source)))
  (OUT/(target.name+'.quality.json')).write_text(json.dumps(report,indent=2))
  receipts.append(dict(label=label,encoder=encoder,elapsed_seconds=elapsed,status=report['status'],accepted=report['accepted'],file=target.name))
# Decode comparisons establish real pixel changes and identical audio payload.
def decoded(path,stream):
 return run(['ffmpeg','-v','error','-i',str(path),*(['-an','-vf','scale=90:160','-pix_fmt','rgb24','-f','rawvideo'] if stream=='video' else ['-vn','-ac','1','-ar','16000','-f','s16le']),'-']).stdout
v0=np.frombuffer(decoded(OUT/'baseline-cpu.mp4','video'),np.uint8);v1=np.frombuffer(decoded(OUT/'skills-cpu.mp4','video'),np.uint8)
comparison=dict(video_bytes_same_length=len(v0)==len(v1),mean_pixel_difference=float(np.abs(v0.astype(float)-v1.astype(float)).mean()),audio_identical=decoded(OUT/'baseline-cpu.mp4','audio')==decoded(OUT/'skills-cpu.mp4','audio'),automatic_effects=[e['type'] for e in a.active(settings)],review='Independent human aesthetic review pending')
assert comparison['video_bytes_same_length'] and comparison['mean_pixel_difference']>0 and comparison['audio_identical']
# Existing safe camera filter, isolated from semantic detection.
control=copy.deepcopy(settings);control['effects']=[a.Effect(id='synthetic-camera',type='smooth_zoom_in',category='camera',source_scene='scene-0',start=.5,end=2.5,duration=2.,origin='manual',reason='Synthetic adapter control, not observed human reaction.',confidence=1.).model_dump(mode='json')]
a.render(source,OUT/'camera-control.mp4',control,(360,640),24.,run,['-c:v','libx264','-preset','fast','-threads','2','-pix_fmt','yuv420p'])
(OUT/'receipt.json').write_text(json.dumps(dict(renders=receipts,comparison=comparison,duration=duration),indent=2));print(json.dumps(comparison),flush=True)
