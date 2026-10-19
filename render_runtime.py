"""Bounded execution for the existing FFmpeg renderers, not another renderer.

Seekable inputs can retry once on CPU after NVENC fails. MP4 outputs are staged
beside the destination and only replaced after a stream/decode check. Progress
comes from FFmpeg's output clock; quality/content validation remains the shared
export gate. No command strings are passed to a shell or written to receipts.
"""
from contextlib import contextmanager
import importlib.util
import json
import hashlib
import math
import os
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import ffmpeg_utils as enc

VERSION=1
_gate_lock=threading.Lock()
_gate=None
_caps=None
_caps_lock=threading.Lock()
_context=threading.local()


class Cancelled(RuntimeError): pass


def check(cancel):
    if cancel is not None and cancel.is_set():raise Cancelled('Render cancelled')


@contextmanager
def progress_scope(callback=None):
    previous=getattr(_context,'callback',None)
    _context.callback=callback
    try:yield
    finally:_context.callback=previous


def limits():
    return dict(encoders=enc.bounded_int('RENDER_MAX_ENCODERS',2,1,4),
        threads=enc.bounded_int('FFMPEG_THREADS',min(4,os.cpu_count() or 2),1,16),
        clip_workers=enc.bounded_int('CLIP_WORKERS',2,1,4))


def capabilities():
    global _caps
    with _caps_lock:
        if _caps is not None:
            result=dict(_caps);result['nvenc_initialized']=enc.nvenc_available();return result
        def query(binary,args):
            try:
                proc=subprocess.run([binary,'-hide_banner',*args],capture_output=True,text=True,timeout=15)
                return proc.returncode==0,(proc.stdout+proc.stderr)[:256000]
            except (OSError,subprocess.SubprocessError):return False,''
        ffmpeg,version=query('ffmpeg',['-version']);ffprobe,_=query('ffprobe',['-version'])
        _,filters=query('ffmpeg',['-filters']) if ffmpeg else (False,'')
        cpu,_=query('ffmpeg',['-v','error','-f','lavfi','-i','color=s=192x320:r=24:d=0.1',
                             '-frames:v','1','-c:v','libx264','-pix_fmt','yuv420p','-threads','1','-f','null','-']) if ffmpeg else (False,'')
        required={name:any(name==part for line in filters.splitlines() for part in line.split()[:2])
                  for name in ('ass','crop','scale','concat','loudnorm')}
        _caps=dict(version=VERSION,ffmpeg=ffmpeg,ffprobe=ffprobe,
            ffmpeg_version=version.splitlines()[0] if version else None,
            libx264_initialized=cpu,nvenc_initialized=enc.nvenc_available() if ffmpeg else False,
            filters=required,opencv=importlib.util.find_spec('cv2') is not None,
            remotion_project=(Path(__file__).parent/'remotion'/'package.json').is_file(),
            remotion_service_installed=(Path(__file__).parent/'render-service'/'node_modules'/'@remotion'/'renderer').is_dir(),
            remotion_encoder='libx264 (installed Remotion has no Windows NVENC implementation)',
            browser_rendering='WebCodecs support must be checked in the client',limits=limits())
        return dict(_caps)


def encoder_signature():
    # Cache keys include quality/speed/thread policy, not runtime progress.
    return dict(version=VERSION,args=enc.video_encode_args(enc.QUALITY_FAST),threads=limits()['threads'])


def require_captions(transcript,start,end,enabled,generated):
    """Do not publish a requested, timed caption layer after its renderer failed."""
    if enabled and not generated and os.getenv('RENDER_STRICT_OVERLAYS','1')!='0':
        from caption_timing import relative_words
        if relative_words(transcript,start,end):raise ValueError('Requested captions were not rendered; export was not accepted')


def _is_ffmpeg(command):
    return Path(str(command[0])).stem.lower()=='ffmpeg'


def _duration(command):
    try:
        if command.count('-i')>1:return None
        if '-t' in command:value=float(command[command.index('-t')+1])
        elif '-to' in command:
            value=float(command[command.index('-to')+1])-(float(command[command.index('-ss')+1]) if '-ss' in command else 0)
        else:return None
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError,IndexError):return None


def hardware_failure(stderr):
    text=str(stderr).lower()
    return any(token in text for token in ('nvenc','nvcuda','no capable devices','openencodesession','cuda_error','cannot load libcuda'))


def _rss(pid):
    try:
        import psutil  # Optional existing dependency; never needed to render.
        proc=psutil.Process(pid)
        return proc.memory_info().rss+sum(c.memory_info().rss for c in proc.children(recursive=True) if c.is_running())
    except Exception:return None


def _execute(command,cancel,deadline,callback,duration,attempt):
    ffmpeg=_is_ffmpeg(command)
    progress_stream=ffmpeg and command[-1] not in ('pipe:1','-')
    command=list(command)
    if ffmpeg:
        prefix=['-nostdin','-threads','2']
        if '-filter_complex_threads' not in command:prefix+=['-filter_complex_threads','1']
        if '-filter_threads' not in command:prefix+=['-filter_threads','1']
        if progress_stream:prefix+=['-nostats','-progress','pipe:1']
        command[1:1]=prefix
    output=bytearray();latest={};lock=threading.Lock();peak=None;overflow=threading.Event()
    with tempfile.TemporaryFile() as errors:
        child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,
            **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        def read():
            source=child.stdout.readline if progress_stream else lambda:child.stdout.read(65536)
            for line in iter(source,b''):
                if progress_stream:
                    key,_,value=line.decode('utf-8','replace').strip().partition('=')
                    with lock:
                        if key=='progress':latest['updated']=True
                        elif key in ('frame','fps','out_time_us','speed'):latest[key]=value
                elif len(output)+len(line)<=64*1024*1024:output.extend(line)
                else:overflow.set()
        reader=threading.Thread(target=read,daemon=True);reader.start()
        try:
            while True:
                check(cancel)
                if overflow.is_set():raise ValueError('FFmpeg pipe output exceeds the bounded capture limit')
                if time.monotonic()>=deadline:raise TimeoutError('FFmpeg render exceeded its time budget')
                memory=_rss(child.pid)
                if memory is not None:peak=max(peak or 0,memory)
                finished=child.poll() is not None
                # A short render can exit between polls. Drain its final progress
                # before delivering callbacks so the last measured frame is kept.
                if finished:reader.join(timeout=2)
                with lock: row=dict(latest);latest['updated']=False
                if callback and row.get('updated'):
                    def number(key):
                        try:
                            value=float(row.get(key,0))
                            return max(0,value) if math.isfinite(value) else 0
                        except (TypeError,ValueError):return 0
                    seconds=number('out_time_us')/1e6
                    callback(dict(time_seconds=seconds,frame=int(number('frame')),
                        fps=number('fps'),speed=row.get('speed'),duration=duration,
                        fraction=min(.99,seconds/duration) if duration else None,attempt=attempt))
                if finished:break
                time.sleep(.05)
            reader.join(timeout=2)
            errors.seek(0,os.SEEK_END);length=errors.tell();errors.seek(max(0,length-128000))
            return dict(returncode=child.returncode,stdout=bytes(output),stderr=errors.read().decode('utf-8','replace'),
                        peak_ram_bytes=peak,progress=dict(latest))
        finally:
            if child.poll() is None:child.kill()
            child.wait();reader.join(timeout=2);child.stdout.close()


def _validate_container(path,command,deadline):
    import export_quality as quality
    info=quality.probe(path,timeout=min(10,max(.01,deadline-time.monotonic())))
    video,audio=quality.streams(info)
    if not video or not quality.number(video.get('duration'),quality.number(info.get('format',{}).get('duration'))):
        raise ValueError('Encoder did not finish a usable video stream')
    if any(codec in command for codec in ('libx264','h264_nvenc')):
        if video.get('codec_name')!='h264':raise ValueError('H.264 encoder produced an unexpected codec')
        if video.get('pix_fmt')!='yuv420p':raise ValueError('H.264 export is not yuv420p')
        # Full export quality validates expected dimensions/audio and samples.
        proc=subprocess.run(['ffmpeg','-v','error','-nostdin','-xerror','-threads','1','-i',str(path),
            '-frames:v','1','-an','-f','null','-'],check=True,capture_output=True,
            timeout=min(10,max(.01,deadline-time.monotonic())))
        del proc
    return dict(width=video.get('width'),height=video.get('height'),codec=video.get('codec_name'),
                duration=quality.number(video.get('duration')),audio=bool(audio))


def overlay_check(command,output,deadline):
    """Check known ASS assets and sampled raster changes; never infer freeform edits.

    Two sampled layers at most. Unmeasurable/very brief effects are disclosed,
    not claimed verified. An expected legible layer with no raster change fails.
    """
    import export_quality as quality
    filters=command[command.index('-vf')+1] if '-vf' in command else ''
    match=re.match(r"(?:ass|subtitles)=filename='([^']+\.ass)'",filters,re.I)
    if not match:return dict(status='NOT_APPLICABLE',method='known-ASS raster comparison only')
    path=Path(match[1].replace('\\:',':').replace("\\'","'"))
    if not path.is_file() or path.stat().st_size>8*1024*1024:raise ValueError('Caption/overlay asset is missing or oversized')
    asset=path.read_bytes();events=[];styles=set()
    def seconds(value):
        h,m,s=value.split(':');return int(h)*3600+int(m)*60+float(s)
    for line in asset.decode('utf-8-sig').splitlines():
        if not line.startswith('Dialogue:'):continue
        parts=line.split(',',9)
        if len(parts)!=10:raise ValueError('Malformed ASS caption event')
        if not re.sub(r'\{[^}]*\}','',parts[-1]).strip():continue
        start,end=seconds(parts[1]),seconds(parts[2])
        if end-start<.08 or parts[3] in styles:continue
        styles.add(parts[3]);events.append((start,end))
        if len(events)==2:break
    result=dict(status='NOT_REQUIRED' if not events else 'UNVERIFIED',asset_sha256=hashlib.sha256(asset).hexdigest(),samples=[])
    if not events:return result
    source=command[command.index('-i')+1]
    source_info=quality.probe(source,timeout=min(5,max(.01,deadline-time.monotonic())))
    out_info=quality.probe(output,timeout=min(5,max(.01,deadline-time.monotonic())))
    before,_=quality.streams(source_info);after,_=quality.streams(out_info)
    if (not before or min(after['width'],after['height'])<160 or
            (before['width'],before['height'])!=(after['width'],after['height'])):return result
    fps=quality.rate(after.get('avg_frame_rate')) or 30
    offset=float(command[command.index('-ss')+1]) if '-ss' in command else 0
    def pixels(file,t):
        return subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-ss',str(t),'-i',str(file),
            '-frames:v','1','-filter_threads','1','-vf','scale=192:342','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],
            check=True,capture_output=True,timeout=min(5,max(.01,deadline-time.monotonic()))).stdout
    for start,end in events:
        t=math.ceil((start+min(.15,(end-start)/2))*fps)/fps
        if t>=end:continue
        a,b=pixels(source,t+offset),pixels(output,t)
        if len(a)!=192*342*3 or len(b)!=len(a):continue
        changed=sum(abs(x-y)>12 for x,y in zip(a,b))
        result['samples'].append(dict(time=round(t,4),changed_channels=changed,threshold=12))
        if changed<5:raise ValueError('Expected caption/overlay produced no measurable raster change')
    if result['samples']:result['status']='PASS'
    return result


def run(command,cancel=None,timeout=180,*,progress=None,duration=None):
    """Existing runner contract: (stdout bytes, stderr text). One CPU fallback.

    Pipe input cannot be replayed; its caller must reconstruct frames on CPU.
    A cancelled/failed call never publishes staged MP4 bytes or a cache receipt.
    """
    global _gate
    check(cancel);deadline=time.monotonic()+timeout
    callback=progress or getattr(_context,'callback',None)
    ffmpeg=_is_ffmpeg(command)
    if not ffmpeg:
        result=_execute(command,cancel,deadline,None,None,1)
        if result['returncode']:raise subprocess.CalledProcessError(result['returncode'],command,stderr=result['stderr'])
        return result['stdout'],result['stderr']
    with _gate_lock:
        if _gate is None:_gate=threading.BoundedSemaphore(limits()['encoders'])
    while not _gate.acquire(timeout=.1):
        check(cancel)
        if time.monotonic()>=deadline:raise TimeoutError('Encoder queue exceeded the time budget')
    temporary=None;started=time.monotonic();original=list(map(str,command))
    target=Path(original[-1]) if original[-1].lower().endswith('.mp4') else None
    try:
        check(cancel)
        actual=list(original)
        measured_duration=duration or _duration(actual)
        if callback and measured_duration is None and actual.count('-i')==1:
            source=actual[actual.index('-i')+1]
            if Path(source).is_file():
                try:
                    import export_quality
                    info=export_quality.probe(source,timeout=min(5,max(.01,deadline-time.monotonic())))
                    measured_duration=export_quality.number(info.get('format',{}).get('duration'))
                except (OSError,ValueError,subprocess.SubprocessError):pass
        if target:
            fd,name=tempfile.mkstemp(prefix='.render-',suffix='.mp4',dir=target.resolve().parent);os.close(fd)
            temporary=Path(name);actual[-1]=str(temporary)
            extra=['-threads',str(limits()['threads']),'-movflags','+faststart']
            if any(c in actual for c in ('libx264','h264_nvenc')):extra+=['-pix_fmt','yuv420p']
            actual[-1:-1]=extra
        requested='h264_nvenc' if 'h264_nvenc' in actual else 'libx264' if 'libx264' in actual else 'copy'
        effective=requested;fallback=False;reports=[]
        for attempt in range(1,3):
            result=_execute(actual,cancel,deadline,callback,measured_duration,attempt);reports.append(result)
            if result['returncode']==0:break
            if attempt==1 and 'h264_nvenc' in actual and hardware_failure(result['stderr']) and not any(v in actual for v in ('pipe:0','-')):
                enc.nvenc_failed()
                actual=enc.cpu_fallback_command(actual);effective='libx264';fallback=True
                print('[Encoder] NVENC render failed; retrying once with libx264 at the matching quality tier.',flush=True)
                continue
            raise subprocess.CalledProcessError(result['returncode'],original,stderr=result['stderr'])
        check(cancel)
        receipt=dict(version=VERSION,requested_encoder=requested,effective_encoder=effective,
            selection_mode=os.getenv('FFMPEG_ENCODER','x264'),
            cpu_fallback=fallback,attempts=len(reports),elapsed_seconds=round(time.monotonic()-started,4),
            peak_ram_bytes=max([r['peak_ram_bytes'] for r in reports if r['peak_ram_bytes'] is not None],default=None),
            frame=int(result['progress'].get('frame',0)),threads=limits()['threads'])
        if target:
            if temporary.stat().st_size==0:raise ValueError('Encoder produced an empty output')
            receipt['media']=_validate_container(temporary,actual,deadline)
            receipt['overlay']=overlay_check(original,temporary,deadline)
            check(cancel)
            os.replace(temporary,target)
            from story_director import atomic_json
            import export_quality
            receipt.update(fingerprint=export_quality.fingerprint(target),bytes=target.stat().st_size)
            atomic_json(str(target)+'.render.json',receipt)
        return result['stdout'],result['stderr']
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
        _gate.release()
