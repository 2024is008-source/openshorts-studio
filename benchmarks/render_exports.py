"""Reproducible local TASK-010 benchmarks; no AI, downloads or user media.

Run from the repository venv: python benchmarks/render_exports.py
Preparation is excluded; encoding and end-to-end validation timings are separate.
GPU telemetry is whole-device nvidia-smi utilization, not process attribution.
"""
import argparse
import json
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import caption_renderer
import export_quality as quality
import ffmpeg_utils as encoder
import reframe_v2
import render_runtime
import split_layout

CASES={'simple-30':30,'caption-heavy-60':60,'multi-scene-30':30}


class Telemetry:
    def __enter__(self):
        self.samples=[];self.stop=threading.Event()
        def sample():
            while not self.stop.is_set():
                try:
                    result=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,utilization.encoder,memory.used','--format=csv,noheader,nounits'],
                        check=True,capture_output=True,text=True,timeout=2)
                    gpu,encoding,memory=map(float,result.stdout.splitlines()[0].split(','))
                    self.samples.append(dict(utilization_percent=gpu,encoder_percent=encoding,memory_mib=memory))
                except (OSError,ValueError,subprocess.SubprocessError,IndexError):pass
                self.stop.wait(.5)
        self.worker=threading.Thread(target=sample,daemon=True);self.worker.start();return self
    def __exit__(self,*args):self.stop.set();self.worker.join(timeout=3)
    def report(self):
        return dict(scope='whole GPU; includes desktop/other workloads',samples=len(self.samples),
            mean_utilization_percent=round(statistics.mean(s['utilization_percent'] for s in self.samples),2) if self.samples else None,
            peak_utilization_percent=max((s['utilization_percent'] for s in self.samples),default=None),
            mean_encoder_utilization_percent=round(statistics.mean(s['encoder_percent'] for s in self.samples),2) if self.samples else None,
            peak_encoder_utilization_percent=max((s['encoder_percent'] for s in self.samples),default=None),
            peak_device_memory_mib=max((s['memory_mib'] for s in self.samples),default=None))


def prepare(folder,case):
    duration=CASES[case];source=folder/f'source-{case}.mp4'
    if source.is_file():
        try:
            info=quality.probe(source);video,audio=quality.streams(info)
            if video and audio and abs(float(video['duration'])-duration)<.1:return source
        except (OSError,ValueError,subprocess.SubprocessError):pass
    if case=='simple-30':
        picture=f'color=c=0x304050:s=1080x1920:r=30:d={duration},drawbox=x=360:y=480:w=360:h=640:color=0x507080:t=fill'
    elif case=='caption-heavy-60':picture=f'testsrc2=s=540x960:r=30:d={duration},scale=1080:1920'
    else:picture=f'testsrc2=s=960x540:r=30:d={duration}'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',picture,'-f','lavfi','-i',
        f'sine=frequency=440:sample_rate=48000:duration={duration}','-c:v','libx264','-preset','ultrafast','-crf','18',
        '-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(source)],
        check=True,capture_output=True,timeout=180)
    return source


def captions(path,duration):
    words=[dict(word=' '+['OpenShorts','clear','synchronized','caption','sample.'][i%5],start=i*.2,end=i*.2+.17)
           for i in range(int(duration*5))]
    caption_renderer.generate({'segments':[dict(start=0,end=duration,words=words)]},0,duration,str(path),
        1080,1920,'openshorts-dynamic',max_words=5)


def execute(source,output,case,folder):
    duration=CASES[case];profile=encoder.video_encode_args(encoder.QUALITY_FAST)
    common=['-c:a','aac','-ar','48000','-b:a','192k','-pix_fmt','yuv420p','-movflags','+faststart']
    receipts=[]
    def run(command):
        render_runtime.run(command,timeout=300,duration=duration if case!='multi-scene-30' else None)
        sidecar=Path(command[-1]+'.render.json')
        receipts.append(json.loads(sidecar.read_text(encoding='utf-8')))
    if case!='multi-scene-30':
        args=[]
        if case=='caption-heavy-60':
            ass=folder/'captions.ass';captions(ass,duration)
            args=['-vf',f"ass=filename='{encoder.escape_filter_value(str(ass))}'"]
        run(['ffmpeg','-v','error','-y','-i',str(source),*args,*profile,*common,str(output)])
    else:
        graphs=[reframe_v2.general_filtergraph(1080,1920),
            split_layout.split_filtergraph(960,540,1080,1920,(240,270),(720,270)),
            reframe_v2.editorial_filtergraph(960,540,1080,1920)]
        parts=[]
        for i,graph in enumerate(graphs):
            part=folder/f'part-{i}.mp4';parts.append(part)
            run(['ffmpeg','-v','error','-y','-ss',str(i*10),'-t','10','-i',str(source),
                '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-map','0:a:0',*profile,*common,str(part)])
        listing=folder/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in parts),encoding='utf-8')
        run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(output)])
    return receipts


def benchmark(folder,mode,case,source):
    os.environ['FFMPEG_ENCODER']=mode;encoder.reset_encoder_cache()
    directory=folder/f'{mode}-{case}';directory.mkdir(exist_ok=True)
    output=directory/'export.mp4';start=time.perf_counter()
    with Telemetry() as monitor:
        receipts=execute(source,output,case,directory)
        rendered=time.perf_counter()-start
        contract=quality.expectations(quality.probe(source),duration=CASES[case],size=(1080,1920))
        report=quality.enforce(output,case,contract,reference=source,master_audio=True,transitions=[10,20] if case=='multi-scene-30' else [])
        elapsed=time.perf_counter()-start
    actual=sorted({r['effective_encoder'] for r in receipts if r['effective_encoder']!='copy'})
    memory=[r['peak_ram_bytes'] for r in receipts if r['peak_ram_bytes'] is not None]
    return dict(case=case,requested_encoder=mode,effective_encoders=actual,
        status='CPU_FALLBACK' if mode=='nvenc' and actual!=['h264_nvenc'] else 'MEASURED',
        resolution=[1080,1920],source_fps=30,duration=CASES[case],render_seconds=round(rendered,3),
        end_to_end_seconds=round(elapsed,3),render_fps=round(CASES[case]*30/rendered,2),
        end_to_end_fps=round(CASES[case]*30/elapsed,2),
        peak_encoder_ram_mib=round(max(memory)/1048576,2) if memory else None,
        gpu=monitor.report(),output_bytes=output.stat().st_size,output=str(output.resolve()),
        validation_status=report['status'],accepted=report['accepted'],problems=report['problems'],
        audio_mastering=report.get('audio_mastering'),receipts=receipts)


def compare_outputs(result):
    """Three actual full-HD frames per case; outside all speed measurements.

    CPU standard output is a comparison reference, not a perceptual guarantee.
    No full-video duplicate decode is needed to check encoder/color consistency.
    """
    comparisons=[]
    for case,duration in CASES.items():
        rows={r.get('requested_encoder'):r for r in result['results'] if r.get('case')==case and r.get('accepted')}
        if set(rows)!= {'x264','nvenc'} or rows['nvenc'].get('status')!='MEASURED':continue
        samples=[]
        for t in [.5,duration/2,duration-.5]:
            process=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-threads','1','-ss',str(t),'-i',rows['x264']['output'],
                '-threads','1','-ss',str(t),'-i',rows['nvenc']['output'],'-filter_complex_threads','1',
                '-filter_complex','[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]ssim',
                '-frames:v','1','-an','-f','null','-'],check=True,capture_output=True,text=True,timeout=15)
            score=re.findall(r'All:([0-9.]+)',process.stderr)
            if score:samples.append(dict(time=t,ssim=float(score[-1])))
        comparisons.append(dict(case=case,reference='CPU CRF18 output, identical composition and captions',
            samples=samples,minimum_ssim=min((s['ssim'] for s in samples),default=None)))
    result['cpu_gpu_frame_comparison']=comparisons


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'output'/'task010-benchmark')
    parser.add_argument('--encoder',choices=['all','x264','nvenc'],default='all')
    parser.add_argument('--case',choices=['all',*CASES],default='all')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QUALITY_PRESET']='standard'
    os.environ.setdefault('FFMPEG_THREADS','4');os.environ['AUDIO_MASTERING']='1';os.environ['AUDIO_NORMALIZE']='1'
    caps=render_runtime.capabilities()
    try:
        device=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],text=True,timeout=5).strip()
    except (OSError,subprocess.SubprocessError):device=None
    result=dict(version=1,checked_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),capabilities=caps,gpu_device=device,python=sys.version.split()[0],
        method='Single run per case; preparation excluded; render includes FFmpeg composition/ASS and staging checks. End-to-end also includes mastering and targeted technical validation.',
        cpu_preset=os.getenv('FFMPEG_X264_PRESET','fast'),nvenc_preset=os.getenv('FFMPEG_NVENC_PRESET','p4'),
        cpu_crf=18,nvenc_cq=25,threads=render_runtime.limits()['threads'],results=[])
    for case in CASES if args.case=='all' else [args.case]:
        source=prepare(args.output,case)
        for mode in ['x264','nvenc'] if args.encoder=='all' else [args.encoder]:
            if mode=='nvenc' and not caps['nvenc_initialized']:
                result['results'].append(dict(case=case,requested_encoder=mode,status='UNAVAILABLE'));continue
            try:
                row=benchmark(args.output,mode,case,source);result['results'].append(row)
                print(f'{case} {mode}: {row["render_seconds"]}s / {row["render_fps"]} fps / {row["validation_status"]}',flush=True)
            except Exception as exc:
                result['results'].append(dict(case=case,requested_encoder=mode,status='FAIL',error=type(exc).__name__))
                print(f'{case} {mode}: FAIL {type(exc).__name__}',flush=True)
            (args.output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    compare_outputs(result)
    (args.output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':main()
