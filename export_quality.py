"""Bounded, local post-render validation shared by Python and Remotion exports.

Metadata/decode failures block delivery. Content heuristics warn unless an
aligned reference establishes that the export introduced the defect.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

VERSION = 1
SUFFIX = '.quality.json'


class QualityError(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__('Export validation failed: ' + ', '.join(
            p['code'] for p in report['problems'] if p['severity'] == 'FAIL'))


def failure_report(path, clip_id, code, message, action):
    try: stamp=fingerprint(path)
    except OSError: stamp=None
    return dict(version=VERSION,clip_id=str(clip_id),file=Path(path).name,
        status='FAIL',accepted=False,fingerprint=stamp,expected={},measurements={},
        thresholds=thresholds(),attempts=0,checked_at=time.time(),
        problems=[dict(code=code,severity='FAIL',message=message,action=action,timestamps=[])])


def number(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def rate(value):
    try:
        a, b = str(value).split('/')
        return number(a) / number(b) if number(b) else None
    except (ValueError, TypeError):
        return number(value)


def thresholds():
    def setting(key, default, low, high):
        return max(low, min(number(os.getenv(key), default), high))
    return dict(duration_seconds=setting('QUALITY_DURATION_TOLERANCE', .35, .05, 2),
                av_seconds=setting('QUALITY_AV_TOLERANCE', .35, .05, 2),
                aspect_relative=.01, fps_relative=.02, fps_absolute=.5,
                max_samples=int(setting('QUALITY_MAX_SAMPLES', 8, 3, 12)),
                budget_seconds=setting('QUALITY_TIMEOUT_SECONDS', 45, 10, 60),
                window_seconds=.5, sample_fps=8, dark_luma=12,
                blank_luma=3, freeze_difference=.5, silence_dbfs=-60,
                clipping_fraction=.01, max_probe_attempts=2,
                max_pixels=7680*4320, max_dimension=16384, decode_threads=2)


def fingerprint(path):
    stat = os.stat(path)
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def probe(path, timeout=10):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-max_alloc', '268435456', '-threads', '2',
        '-protocol_whitelist', 'file,pipe,crypto,data', '-show_entries',
        'format=format_name,duration,size,bit_rate,start_time:stream=index,codec_type,codec_name,'
        'width,height,avg_frame_rate,r_frame_rate,duration,start_time,bit_rate,'
        'sample_rate,channels,sample_aspect_ratio,pix_fmt', '-of', 'json', os.path.abspath(path)],
        check=True, capture_output=True, timeout=timeout)
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('probe response exceeds limit')
    return json.loads(result.stdout)


def streams(info):
    videos = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
    audios = [s for s in info.get('streams', []) if s.get('codec_type') == 'audio']
    return (videos[0] if videos else None), (audios[0] if audios else None)


def expectations(info, *, duration=None, size=None, speech_expected=False):
    video, audio = streams(info)
    if not video:
        raise ValueError('reference has no video stream')
    width, height = size or (video.get('width'), video.get('height'))
    sar = 1 if size else rate(str(video.get('sample_aspect_ratio','1:1')).replace(':','/')) or 1
    return dict(width=width, height=height, aspect=width*sar/height,
                fps=rate(video.get('r_frame_rate')) or rate(video.get('avg_frame_rate')),
                duration=duration if duration is not None else number(
                    video.get('duration'), number(info.get('format', {}).get('duration'))),
                audio_expected=bool(audio), speech_expected=bool(speech_expected))


def sample_times(duration, transitions=(), limit=8):
    """Include endpoints, distributed periodic samples, then scene boundaries."""
    last = max(0., duration - min(.5, duration))
    anchors = [0., last, last/2]
    cuts = sorted(set(max(0., min(last, float(t))) for t in transitions
                      if number(t) is not None and 0 < float(t) < duration))
    # Subsample long scene lists uniformly; never let them consume every slot.
    if cuts:
        count = min(len(cuts), max(1, limit//3))
        anchors += [cuts[round(i*(len(cuts)-1)/max(1,count-1))] for i in range(count)]
    anchors += [last*.25,last*.75] + [last*i/max(1,limit-1) for i in range(limit)]
    selected=[]
    for t in anchors:
        t=round(t,3)
        if t not in selected: selected.append(t)
        if len(selected)==limit: break
    return sorted(selected)


def _run(command, deadline, per_call=6):
    left = deadline - time.monotonic()
    if left <= 0:
        raise subprocess.TimeoutExpired(command[0], 0)
    return subprocess.run(command, check=True, capture_output=True,
                          timeout=min(left, per_call)).stdout


def _frames(path, t, width, height, deadline):
    scale = min(192/width, 192/height, 1.)
    w, h = max(2, round(width*scale)), max(2, round(height*scale))
    raw = _run(['ffmpeg', '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode',
        '-max_alloc', '268435456', '-threads', '2', '-filter_threads', '1',
        '-protocol_whitelist', 'file,pipe,crypto,data',
        '-ss', str(t), '-i', os.fspath(path), '-t', '0.5', '-map', '0:v:0',
        '-vf', f'scale={w}:{h},fps=8,format=gray', '-frames:v', '4', '-an',
        '-f', 'rawvideo', 'pipe:1'], deadline)
    stride = w*h
    return [raw[i:i+stride] for i in range(0, len(raw)-stride+1, stride)], w, h


def _difference(a, b):
    return sum(abs(x-y) for x,y in zip(a,b))/len(a) if a and len(a)==len(b) else 255.


def _visual(frames, width, height):
    if not frames:
        return None
    means = [statistics.fmean(f) for f in frames]
    differences = [_difference(a,b) for a,b in zip(frames,frames[1:])]
    f = frames[len(frames)//2]
    sx, sy = max(1, width//20), max(1, height//20)
    edges = [f[:width*sy], f[-width*sy:],
             bytes(f[y*width+x] for y in range(height) for x in range(sx)),
             bytes(f[y*width+x] for y in range(height) for x in range(width-sx,width))]
    center = [f[y*width+x] for y in range(height//4,3*height//4)
              for x in range(width//4,3*width//4)]
    borders = [name for name, edge in zip(('top','bottom','left','right'),edges)
               if statistics.fmean(edge) < 12 and statistics.pstdev(edge) < 4
               and statistics.fmean(center) > 32]
    return dict(mean=round(statistics.fmean(means),3),
                blank=all((m <= 3 or m >= 252) and statistics.pstdev(f) < 2 for m,f in zip(means,frames)),
                motion=round(statistics.fmean(differences),3) if differences else None,
                borders=borders, decoded_frames=len(frames))


def _audio(path, t, deadline):
    raw = _run(['ffmpeg', '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode',
        '-max_alloc', '268435456', '-threads', '2', '-filter_threads', '1',
        '-protocol_whitelist', 'file,pipe,crypto,data',
        '-ss', str(t), '-i', os.fspath(path), '-t', '0.5', '-map', '0:a:0',
        # Measure interleaved stereo samples rather than a mono downmix, which
        # can cancel perfectly valid out-of-phase audio into apparent silence.
        '-vn', '-ac', '2', '-ar', '8000', '-f', 's16le', 'pipe:1'], deadline)
    pcm = array.array('h')
    pcm.frombytes(raw[:len(raw)//2*2])
    if sys.byteorder != 'little': pcm.byteswap()
    if not pcm:
        return None
    rms = math.sqrt(sum((s/32768)**2 for s in pcm)/len(pcm))
    return dict(rms_dbfs=round(20*math.log10(max(rms, 1e-10)),2),
                peak=max(abs(s) for s in pcm)/32768,
                clipping_fraction=sum(abs(s)>=32760 for s in pcm)/len(pcm))


def validate(path, clip_id, expected=None, *, reference=None, transitions=()):
    limits = thresholds()
    expected = dict(expected or {})
    report = dict(version=VERSION, clip_id=str(clip_id), file=Path(path).name,
                  status='PASS', accepted=True, problems=[], measurements={},
                  thresholds=limits, expected=expected, attempts=0,
                  checked_at=time.time(), coverage='targeted samples; not a full decode')
    deadline = time.monotonic() + limits['budget_seconds']

    def problem(code, severity, message, action, timestamps=()):
        report['problems'].append(dict(code=code, severity=severity, message=message,
            timestamps=[round(float(t),3) for t in timestamps], action=action))

    def finish():
        levels = {p['severity'] for p in report['problems']}
        report['status'] = 'FAIL' if 'FAIL' in levels else 'WARNING' if 'WARNING' in levels else 'PASS'
        report['accepted'] = report['status'] != 'FAIL'
        report['elapsed_seconds'] = round(limits['budget_seconds']-(deadline-time.monotonic()),3)
        return report

    try:
        report['fingerprint'] = fingerprint(path)
        if not report['fingerprint']['size']:
            problem('EMPTY_FILE','FAIL','Output is empty.','Render the clip again.')
            return finish()
        with open(path, 'rb') as handle: handle.read(1)
    except OSError:
        problem('UNREADABLE_FILE','FAIL','Output is missing or unreadable.','Restore or rerender this clip.')
        return finish()
    for attempt in range(2):
        report['attempts'] += 1
        try:
            info = probe(path, timeout=min(10, max(.01, deadline-time.monotonic())))
            break
        except subprocess.TimeoutExpired:
            if attempt == 0 and time.monotonic() < deadline:
                continue  # Retry only this known transient, at most once.
            problem('PROBE_TIMEOUT','FAIL','Metadata inspection timed out.','Close other processing jobs and revalidate.')
            return finish()
        except FileNotFoundError:
            problem('DEPENDENCY_MISSING','FAIL','FFprobe is unavailable.','Install FFmpeg/FFprobe and revalidate.')
            return finish()
        except (OSError, subprocess.CalledProcessError, ValueError):
            problem('INVALID_CONTAINER','FAIL','FFprobe could not read the output.','Rerender from the source; do not retry this damaged file automatically.')
            return finish()
    if report['attempts'] > 1:
        problem('TRANSIENT_RETRY','WARNING','Metadata inspection succeeded on its second attempt.',
                'Review system load if this happens repeatedly.')
    video, audio = streams(info)
    if not video:
        problem('MISSING_VIDEO','FAIL','No video stream exists.','Render with a video stream.')
        return finish()
    container=info.get('format',{}).get('format_name')
    if Path(path).suffix.lower()=='.mp4' and container and not {'mp4','mov'}.intersection(container.split(',')):
        problem('WRONG_CONTAINER','FAIL','The file is not a compatible MP4 container.',
                'Export an MP4 container rather than renaming another format.')
    w, h = number(video.get('width'),0), number(video.get('height'),0)
    fps = rate(video.get('avg_frame_rate')) or rate(video.get('r_frame_rate'))
    duration = number(video.get('duration'), number(info.get('format',{}).get('duration')))
    m = report['measurements']
    m.update(width=w, height=h, fps=fps, duration=duration,
             bytes=report['fingerprint']['size'], audio_present=bool(audio))
    m.update(video_codec=video.get('codec_name'),pixel_format=video.get('pix_fmt'),
             audio_codec=audio.get('codec_name') if audio else None)
    for field,observed,code in [('video_codec',m['video_codec'],'WRONG_VIDEO_CODEC'),
            ('pixel_format',m['pixel_format'],'WRONG_PIXEL_FORMAT'),
            ('audio_codec',m['audio_codec'],'WRONG_AUDIO_CODEC')]:
        if expected.get(field) and (field!='audio_codec' or audio) and observed!=expected[field]:
            problem(code,'FAIL',f'Unexpected {field}: {observed}; expected {expected[field]}.',
                'Render again with the selected codec/pixel format; do not relabel color-range metadata without conversion.')
    if w*h>limits['max_pixels'] or max(w,h)>limits['max_dimension']:
        problem('RESOURCE_LIMIT','FAIL','Output dimensions exceed the bounded validator decode limit.',
                'Use a lower export resolution, such as 1080x1920, and render again.')
    for key, observed in [('width',w),('height',h)]:
        if observed < 2 or (expected.get(key) is not None and observed != expected[key]):
            problem('WRONG_DIMENSIONS','FAIL',f'Unexpected {key}: {observed}; expected {expected.get(key)}.',
                    'Render again using the selected export dimensions.')
    sar = rate(str(video.get('sample_aspect_ratio','1:1')).replace(':','/')) or 1
    aspect = w*sar/h if h else 0
    m['display_aspect'] = aspect
    if expected.get('aspect') and abs(aspect/expected['aspect']-1) > limits['aspect_relative']:
        problem('WRONG_ASPECT','FAIL','Display aspect ratio differs from the export preset.',
                'Correct crop/scale and square-pixel metadata, then rerender.')
    target_fps = number(expected.get('fps'))
    if (not fps or not 0 < fps <= 240 or (target_fps and
            abs(fps-target_fps)>max(limits['fps_absolute'],target_fps*limits['fps_relative']))):
        problem('WRONG_FPS','FAIL',f'Frame rate {fps} does not match the export preset.',
                'Rerender at the selected frame rate.')
    target_duration = number(expected.get('duration'))
    tolerance = max(limits['duration_seconds'], 2/(fps or 30))
    m['duration_tolerance_seconds']=tolerance
    if not duration or duration <= 0 or (target_duration and abs(duration-target_duration)>tolerance):
        problem('WRONG_DURATION','FAIL',f'Duration {duration} differs from expected {target_duration}.',
                'Check clip boundaries and render the complete clip.')
    bitrate = number(video.get('bit_rate')) or number(info.get('format',{}).get('bit_rate'))
    m['bitrate'] = bitrate or (round(m['bytes']*8/duration) if duration and duration>0 else None)
    m['bitrate_source'] = 'metadata' if bitrate else 'estimated from container size'
    if m['bitrate'] is None or m['bitrate'] <= 0:
        problem('INVALID_BITRATE','FAIL','The reported bitrate is not usable.','Rerender the output.')
    if expected.get('audio_expected') and not audio:
        problem('MISSING_AUDIO','FAIL','The source/preset requires audio, but the output has none.',
                'Render again with the expected audio track mapped.')
    if 'audio_expected' in expected and expected['audio_expected'] is None:
        problem('AUDIO_EXPECTATION_UNKNOWN','WARNING','Whether this source requires audio is unknown.',
                'Confirm whether the source should have audio and recheck.')
    if audio:
        ad = number(audio.get('duration'))
        vs, aus = number(video.get('start_time'),0), number(audio.get('start_time'),0)
        m.update(audio_duration=ad, video_start=vs, audio_start=aus)
        if ad is None:
            problem('UNKNOWN_AUDIO_DURATION','WARNING','Audio duration is not available in stream metadata.',
                    'Review playback and revalidate a remuxed MP4 if needed.')
        elif duration:
            m['av_end_delta'] = round((aus+ad)-(vs+duration),4)
            if abs(m['av_end_delta'])>limits['av_seconds'] or abs(aus-vs)>limits['av_seconds']:
                problem('AV_TIMING','FAIL','Audio/video start or end times exceed the configured tolerance.',
                        'Correct audio mapping/timestamps and rerender.',[max(0,min(duration,ad))])
    if any(p['severity']=='FAIL' for p in report['problems']): return finish()

    times = sample_times(duration,transitions,limits['max_samples'])
    m['video_samples'], m['audio_samples'] = [], []
    ref_video = ref_audio = None
    if reference:
        try: ref_video,ref_audio = streams(probe(reference, timeout=min(6,max(.01,deadline-time.monotonic()))))
        except (OSError, ValueError, subprocess.SubprocessError): pass
    m['reference_available']=bool(ref_video)
    audio_times = {times[0],times[len(times)//2],times[-1]}
    try:
        for t in times:
            frames, sw, sh = _frames(path,t,w,h,deadline)
            v = _visual(frames,sw,sh)
            if v is None:
                problem('UNDECODABLE_VIDEO','FAIL','No frames could be decoded at a required sample.',
                        'Rerender the clip from the source.',[t])
                continue
            ref = None
            if ref_video and time.monotonic()+1 < deadline:
                try:
                    rf,rw,rh = _frames(reference,t,ref_video['width'],ref_video['height'],deadline)
                    ref = _visual(rf,rw,rh)
                except (OSError, subprocess.SubprocessError): pass
            m['video_samples'].append({'time':t,**v})
            if v['blank'] and not (ref and ref['blank']):
                problem('BLANK_FRAMES','WARNING','A sampled window is fully dark/blank; it may be intentional.',
                        'Compare this moment with the source.',[t])
            new_edges = set(v['borders']) - set(ref['borders'] if ref else [])
            if new_edges:
                problem('DARK_BORDERS','WARNING','Uniform dark edges detected: '+', '.join(sorted(new_edges))+'.',
                        'Review whether these are source borders or unintended padding.',[t])
            if (v['motion'] is not None and v['motion']<limits['freeze_difference']
                    and ref and ref['motion'] is not None and ref['motion']>2):
                problem('POSSIBLE_FREEZE','WARNING','The output is static while the aligned source is moving.',
                        'Review this scene for a frozen frame or intentional static composition.',[t])
            if audio and t in audio_times:
                a = _audio(path,t,deadline)
                if a is None:
                    problem('UNDECODABLE_AUDIO','FAIL','No audio samples decoded inside the audio stream.',
                            'Check the audio stream and rerender.',[t])
                else:
                    m['audio_samples'].append({'time':t,**a})
                    activity_expected=expected.get('speech_expected',False)
                    if a['rms_dbfs'] < limits['silence_dbfs'] and ref_audio and not activity_expected:
                        try:
                            ref_level=_audio(reference,t,deadline)
                            activity_expected=bool(ref_level and ref_level['rms_dbfs']>-45)
                        except (OSError,subprocess.SubprocessError): pass
                    if a['rms_dbfs'] < limits['silence_dbfs'] and activity_expected:
                        problem('UNEXPECTED_SILENCE','WARNING','A speech export contains a silent sampled window.',
                                'Check for an intentional pause or missing speech.',[t])
                    if a['clipping_fraction']>limits['clipping_fraction']:
                        problem('AUDIO_CLIPPING','WARNING','A high fraction of samples hit the PCM limit.',
                                'Compare the source and reduce gain/limit audio before rerendering.',[t])
    except FileNotFoundError:
        problem('DEPENDENCY_MISSING','FAIL','FFmpeg is unavailable.','Install FFmpeg and revalidate.')
    except subprocess.TimeoutExpired:
        problem('SAMPLING_TIMEOUT','FAIL','Sample decoding exceeded the validation budget.',
                'Close other processing jobs and revalidate; no rerender is needed to retry validation.')
    except (OSError, ValueError, subprocess.CalledProcessError):
        problem('DECODE_ERROR','FAIL','A required sampled video/audio window could not be decoded.',
                'Rerender this clip from the source.')
    try: unchanged = fingerprint(path) == report['fingerprint']
    except OSError: unchanged = False
    if not unchanged:
        problem('FILE_CHANGED','FAIL','The file changed during validation.','Wait for rendering to finish and revalidate.')
    return finish()


def read_report(path, *, fresh=True):
    try:
        sidecar = Path(os.fspath(path)+SUFFIX)
        if sidecar.stat().st_size > 256*1024: return None
        report = json.loads(sidecar.read_text(encoding='utf-8'))
        if not isinstance(report, dict): return None
        if (report.get('version') == VERSION and report.get('status') in ('PASS','WARNING','FAIL')
                and report.get('accepted') is (report['status'] != 'FAIL') and (not fresh or (
                report.get('fingerprint') == fingerprint(path) and report.get('thresholds') == thresholds()))):
            return report
    except (OSError, ValueError, TypeError): pass
    return None


def save_report(path, report):
    sidecar = os.fspath(path)+SUFFIX
    fd, tmp = tempfile.mkstemp(prefix='.quality_',dir=os.path.dirname(os.path.abspath(sidecar)))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle:
            json.dump(report,handle,ensure_ascii=False,allow_nan=False)
        os.replace(tmp,sidecar)
    finally:
        if os.path.exists(tmp): os.remove(tmp)


def enforce(path, clip_id, expected=None, *, reference=None, transitions=(), force=False, master_audio=False, audio_config=None):
    audio_report = None
    previous = read_report(path)
    render_report=previous.get('render') if previous else None
    try:
        sidecar=Path(os.fspath(path)+'.render.json')
        if sidecar.stat().st_size<=256*1024:
            value=json.loads(sidecar.read_text(encoding='utf-8'))
            if isinstance(value,dict) and value.get('fingerprint')==fingerprint(path):render_report=value
    except (OSError,ValueError):pass
    if master_audio:
        import audio_mastering
        try:
            audio_report = audio_mastering.master(path,config=audio_config)
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
            failed = failure_report(path, clip_id, "AUDIO_MASTERING_FAILED",
                "Audio mastering did not pass its peak, decode or synchronization checks.",
                "Check FFmpeg and source audio, then retry rendering; original media was preserved.")
            if isinstance(exc,audio_mastering.TimingError):
                failed['measurements']['audio_mastering_timing']=exc.measurements
                failed['problems'][0]['message']=str(exc)
                print(f'   ⚠️ {exc}',flush=True)
            save_report(path, failed)
            raise QualityError(failed)
    report = None if force else read_report(path)
    if report is None or (expected is not None and report.get('expected') != expected):
        report = validate(path,clip_id,expected,reference=reference,transitions=transitions)
        save_report(path,report)
    elif report.get('clip_id') != str(clip_id):
        report=dict(report,clip_id=str(clip_id))
        save_report(path,report)
    if audio_report is None:
        if previous:
            audio_report = previous.get('audio_mastering')
        sidecar = Path(os.fspath(path)+'.audio.json')
        try:
            if sidecar.stat().st_size <= 256*1024:
                value = json.loads(sidecar.read_text(encoding='utf-8'))
                if isinstance(value,dict) and value.get('fingerprint') == fingerprint(path):
                    audio_report = value
        except (OSError,ValueError): pass
    if audio_report is not None:
        report['audio_mastering'] = audio_report
        save_report(path, report)
    if render_report is not None:
        report['render']=render_report
        save_report(path,report)
    if not report['accepted']: raise QualityError(report)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--clip-id')
    parser.add_argument('--expected')
    parser.add_argument('--reference')
    parser.add_argument('--force',action='store_true')
    parser.add_argument('--master-audio',action='store_true',help='Master a newly rendered export before validation; omit for read-only rechecks.')
    args=parser.parse_args()
    previous=read_report(args.input,fresh=False) or {}
    clip_id=args.clip_id or previous.get('clip_id') or 'export'
    try:
        contract=(json.loads(args.expected) if args.expected is not None else
                  previous.get('expected',{}))
        if args.reference:
            contract['audio_expected'] = bool(streams(probe(args.reference))[1])
        result=enforce(args.input,clip_id,contract,reference=args.reference,force=args.force,master_audio=args.master_audio)
    except QualityError as exc:
        result=exc.report
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        result=failure_report(args.input,clip_id,'VALIDATOR_SETUP',
            'Validation or its reference/persistence could not be read.',
            'Check FFmpeg, the reference file and write access, then revalidate.')
    print(json.dumps(result,allow_nan=False))
    sys.exit(1 if result['status']=='FAIL' else 0)
