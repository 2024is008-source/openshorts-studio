"""Reusable source-time measurements. No objects/actions inferred from motion."""
import math
from pathlib import Path
import statistics
import time
from .runtime import digest,BudgetExceeded


def identity(source,check=lambda:None):
    import hashlib
    source=Path(source);before=source.stat();sha=hashlib.sha256()
    with source.open('rb') as stream:
        while chunk:=stream.read(1024*1024):check();sha.update(chunk)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed while indexing')
    return dict(sha256=sha.hexdigest(),size=after.st_size)


def measure_motion(source,duration,check=lambda:None):
    """Decode every source frame using PTS; retain bounded half-second bins.

    Tiny grayscale differences measure image change, including scene/camera
    changes. They are not subject velocity or physical camera-motion labels.
    """
    import av
    import numpy as np
    bins={};previous=None;frames=0;started=time.monotonic()
    with av.open(str(source)) as media:
        stream=media.streams.video[0];stream.thread_count=2
        origin=float(media.start_time/av.time_base) if media.start_time is not None else 0.
        for frame in media.decode(stream):
            check()
            if frame.time is None:continue
            t=float(frame.time)-origin
            if not math.isfinite(t) or not 0<=t<=duration:continue
            image=frame.reformat(width=96,height=54,format='gray').to_ndarray().astype(np.int16)
            if previous is not None:
                change=float(np.abs(image-previous).mean()/255)
                key=int(t*2);row=bins.setdefault(key,[0.,0.,0])
                row[0]+=change;row[1]=max(row[1],change);row[2]+=1
            previous=image;frames+=1
    return [dict(start=k/2,end=min(duration,(k+1)/2),mean_change=round(a/n,6),peak_change=round(b,6),frames=n)
        for k,(a,b,n) in sorted(bins.items()) if n],dict(decoded_frames=frames,elapsed_seconds=round(time.monotonic()-started,3),
            retained_frame_shape=[96,54],retained_image_buffers=2,method='all decoded frames, source PTS, grayscale image difference',device='cpu')


def measure_audio(source,duration,check=lambda:None):
    import av
    import numpy as np
    accum={}
    try:
        with av.open(str(source)) as media:
            if not media.streams.audio:return []
            origin=float(media.start_time/av.time_base) if media.start_time is not None else 0.
            for frame in media.decode(media.streams.audio[0]):
                check()
                if frame.time is None:continue
                array=frame.to_ndarray();info=np.iinfo(array.dtype) if np.issubdtype(array.dtype,np.integer) else None
                if not frame.format.is_planar and len(frame.layout.channels)>1:array=array.reshape(-1,len(frame.layout.channels)).T
                samples=array.astype(np.float32)/(max(abs(info.min),info.max) if info else 1.)
                for a in range(0,frame.samples,max(1,frame.sample_rate//4)):
                    t=float(frame.time)-origin+a/frame.sample_rate
                    if not 0<=t<duration:continue
                    part=samples[...,a:a+frame.sample_rate//4]
                    if not part.size:continue
                    k=int(t*2);square=float(np.mean(part*part));row=accum.setdefault(k,[0.,0])
                    row[0]+=square;row[1]+=1
    except (IndexError,ValueError):return []
    rms=[math.sqrt(a/n) for a,n in accum.values() if n];scale=max(rms,default=0.)
    return [dict(start=k/2,end=min(duration,(k+1)/2),relative_rms=round(math.sqrt(a/n)/scale,6) if scale else 0.,
        quiet=math.sqrt(a/n)<.01) for k,(a,n) in sorted(accum.items())]


def build(source,transcript,duration,cache,ledger,existing=None,scene_detector=None,motion_reader=None):
    from clip_selection import speech_units
    import export_quality
    existing=existing or {}
    key=digest([transcript or {},duration,existing])
    saved=cache.read('media-index',key)
    if isinstance(saved,dict) and saved.get('version')==1:
        ledger.cache_hits+=1;ledger.stage('detect_scenes',len(saved['scenes']),len(saved['scenes']),cache=True);return saved
    ledger.stage('detect_scenes',0,None)
    info=export_quality.probe(source);video,_=export_quality.streams(info)
    scenes=existing.get('scene_boundaries')
    if scenes is None:
        # Existing CPU detector does not download a model or allocate all source frames.
        if scene_detector is None:
            from scene_detection import _detect_pyscenedetect
            scene_detector=lambda path:_detect_pyscenedetect(path,check=ledger.check)
        raw,_=scene_detector(str(source))
        scenes=[dict(start=float(a.get_seconds()),end=float(b.get_seconds())) for a,b in raw]
    scenes=[s for s in scenes if 0<=s['start']<s['end']<=duration+.1]
    if not scenes:scenes=[dict(start=0.,end=duration)]
    ledger.check()
    if 'motion' in existing:motion=existing['motion'];resources=existing.get('motion_resources',{'method':'retained measurements'})
    else:motion,resources=(motion_reader or measure_motion)(source,duration,ledger.check)
    audio=existing.get('audio') if 'audio' in existing else measure_audio(source,duration,ledger.check)
    units=speech_units(transcript,duration);paragraphs=[]
    for number,unit in enumerate(units):
        if paragraphs and unit['start']-paragraphs[-1]['end']<1.5 and paragraphs[-1].get('speaker')==unit.get('speaker') and unit['end']-paragraphs[-1]['start']<=120:
            paragraphs[-1]['end']=unit['end'];paragraphs[-1]['unit_ids'].append(f'u{number}')
        else:paragraphs.append(dict(start=unit['start'],end=unit['end'],speaker=unit.get('speaker'),unit_ids=[f'u{number}']))
    index=dict(version=1,duration=duration,metadata={'width':video.get('width') if video else None,'height':video.get('height') if video else None},
        units=[dict(u,id=f'u{i}') for i,u in enumerate(units)],paragraphs=paragraphs,scenes=scenes,motion=motion,audio=audio,
        faces=existing.get('faces'),subjects=existing.get('subjects'),crop_paths=existing.get('crop_paths'),
        frame_observations=existing.get('frame_observations'),speaker_turns=[dict(start=u['start'],end=u['end'],speaker=u.get('speaker')) for u in units if u.get('speaker') is not None],
        speech_intervals=[dict(start=u['start'],end=u['end']) for u in units],resources=resources,
        limitations=['Image difference is not physical camera motion or an action label.','Audio energy is not a verified musical beat or sporting result.',
            'Object/ball/action/scoreboard detectors are unavailable unless retained observations supply them.'])
    ledger.stage('detect_scenes',len(scenes),len(scenes));cache.write('media-index',key,index);return index
