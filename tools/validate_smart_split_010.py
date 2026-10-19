from pathlib import Path
import sys,os,json,subprocess,time
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['OPENSHORTS_LEARNING_DISABLED']='1'
import recut,smart_split,export_quality as q
OUT=ROOT/'build/smart-split-010';OUT.mkdir(exist_ok=True)
def run(cmd):return subprocess.run(cmd,check=True,capture_output=True,timeout=120)
source=OUT/'source.mp4'
run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=12','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=12','-af',"volume=0:enable='between(t,2,6)'",'-c:v','libx264','-preset','fast','-threads','2','-c:a','aac','-pix_fmt','yuv420p',str(source)])
transcript={'segments':[dict(start=a,end=b,text=text,speaker='A',words=[dict(word=text,start=a,end=b,aligned=True)]) for a,b,text in [(0.,2.,'Here is the goal.'),(6.,8.,'Here is the result.')]]}
analysis=dict(category_selection=dict(primary_category='challenge',subcategory='general'),moments=[],scene_cuts=[],
    scene_observations=[dict(start=2.,end=6.,editorial_role='irrelevant_pause',confidence=.92)])
# Known synthetic speech intervals are timing controls; audio is a test tone,
# not a claim that the generated source contains spoken words.
report=smart_split.plan(dict(start=0.,end=8.),transcript,12.,analysis,lambda a,b:dict(available=True,intervals=[[2.,6.]]))
(OUT/'assembly-plan.json').write_text(json.dumps(report,indent=2));receipts=[]
for encoder,args in [('cpu',['-c:v','libx264','-preset','fast','-threads','2']),('nvenc',['-c:v','h264_nvenc','-preset','p4'])]:
 target=OUT/f'assembled-{encoder}.mp4';started=time.perf_counter()
 recut.run_cut_concat(str(source),report['segments'],str(target),str(OUT),runner=run,video_args=args,continuous_audio=True)
 elapsed=time.perf_counter()-started;expected=q.expectations(q.probe(source),duration=report['output_duration'])
 receipt=q.validate(target,'smart-split',expected);(OUT/(target.name+'.quality.json')).write_text(json.dumps(receipt,indent=2))
 assert receipt['accepted'],receipt
 receipts.append(dict(kind='smart-split',encoder=encoder,seconds=elapsed,status=receipt['status'],file=target.name))
base=[dict(start=0.,end=3.),dict(start=8.,end=11.)]
for kind in ('j_cut','l_cut'):
 plan=recut.track_edit(base,12.,[dict(index=1,type=kind,duration=.2,visual_handles_verified=True)])
 for label,size in [('preview',(160,90)),('export',(320,180))]:
  target=OUT/f'{kind}-{label}.mp4';args=['-vf',f'scale={size[0]}:{size[1]}','-c:v','libx264','-preset','fast','-threads','2']
  # filter_complex output scaling is part of the same tested track renderer.
  cmd=recut.track_command(str(source),plan,str(target),['-c:v','libx264','-preset','fast','-threads','2'])
  pos=cmd.index('-filter_complex')+1;cmd[pos]=cmd[pos].replace('concat=n=2:v=1:a=0[v]',f'concat=n=2:v=1:a=0[vc];[vc]scale={size[0]}:{size[1]}[v]')
  started=time.perf_counter();run(cmd)
  receipt=q.validate(target,kind,q.expectations(q.probe(source),duration=6.,size=size))
  assert receipt['accepted'],receipt
  receipts.append(dict(kind=kind,mode=label,seconds=time.perf_counter()-started,status=receipt['status'],file=target.name))
 (OUT/f'{kind}-plan.json').write_text(json.dumps(plan,indent=2))
# Verify video at the J/L boundary comes from the planned visual source clock.
def frame(path,t):
 raw=run(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-vf','scale=80:45','-pix_fmt','rgb24','-f','rawvideo','-']).stdout
 return np.frombuffer(raw,np.uint8).astype(float)
checks=[]
for encoder in ('cpu','nvenc'):
 for t in (2.3,2.4,2.5,4.7):
  row=next(r for r in report['mapping'] if r['start']<=t<r['end'])
  source_t=round(row['source_start']+t-row['start'],6)
  diff=float(np.abs(frame(OUT/f'assembled-{encoder}.mp4',t)-frame(source,source_t)).mean())
  assert diff<15,(encoder,t,diff)
  checks.append(dict(kind='smart-split',encoder=encoder,output_time=t,expected_source_time=source_t,mean_rgb_error=diff))
for kind,t,source_t in [('j_cut',3.1,3.1),('l_cut',2.9,7.9)]:
 actual=frame(OUT/f'{kind}-export.mp4',t);wanted=frame(source,source_t)
 diff=float(np.abs(actual-wanted).mean());assert diff<15,(kind,diff)
 checks.append(dict(kind=kind,output_time=t,expected_source_time=source_t,mean_rgb_error=diff))
for kind in ('j_cut','l_cut'):
 audio=[]
 for mode in ('preview','export'):
  audio.append(run(['ffmpeg','-v','error','-i',str(OUT/f'{kind}-{mode}.mp4'),'-vn','-ac','1','-ar','48000','-f','s16le','-']).stdout)
 assert audio[0]==audio[1]
(OUT/'receipt.json').write_text(json.dumps(dict(renders=receipts,source_mapping_checks=checks,preview_export_audio_identical=True,notes=['Synthetic tone and test-pattern footage, not acted aesthetic validation.','J/L adapter verified separately; automatic native activation remains gated.']),indent=2))
print(json.dumps(receipts),flush=True)
