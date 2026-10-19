"""Measured final-export audio mastering. Local FFmpeg only; never trims speech.

The input remains intact until the encoded AAC has passed peak and timing checks.
Analysis/receipts are identity- and settings-bound. Revalidation never remasters.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import export_quality as quality

VERSION = 2
SUFFIX = '.audio.json'
PRESETS = {'natural': (-16, -2, 18), 'dialogue': (-16, -2, 11),
           'original': (-16, -2, 18)}


class TimingError(ValueError):
    """Nonsecret, structured sync diagnostics suitable for a quality report."""
    def __init__(self, stream, field, before, after):
        self.measurements=dict(stream=stream,field=field,before=before,after=after,
                               difference_seconds=round(after-before,6),tolerance_seconds=.06)
        super().__init__(f'Audio mastering changed {stream} {field} by {after-before:+.6f}s (tolerance 0.060s)')


def options(preset=None, target=None, ceiling=None, fade=None, noise=None):
    """Validate API/CLI controls; no arbitrary FFmpeg expressions or media paths."""
    result = {}
    if preset is not None:
        if not isinstance(preset,str) or preset not in PRESETS:
            raise ValueError('audio_preset must be natural, dialogue or original')
        result['AUDIO_PRESET'] = preset
    for value, key, lo, hi in ((target,'AUDIO_TARGET_LUFS',-24,-12),
                               (ceiling,'AUDIO_TRUE_PEAK',-6,-1),
                               (fade,'AUDIO_FADE_SECONDS',0,2)):
        if value is None: continue
        try: number = float(value)
        except (TypeError, ValueError): raise ValueError(f'{key} must be a number')
        if not math.isfinite(number) or not lo <= number <= hi:
            raise ValueError(f'{key} must be between {lo} and {hi}')
        result[key] = str(number)
    if noise is not None:
        if str(noise).lower() not in ('0','1','true','false'):
            raise ValueError('audio_noise_reduction must be a boolean')
        result['AUDIO_NOISE_REDUCTION'] = '1' if str(noise).lower() in ('1','true') else '0'
    return result


def settings(overrides=None):
    env = dict(os.environ)
    if overrides is not None and not isinstance(overrides,dict):
        raise ValueError('Invalid audio settings')
    env.update(overrides or {})
    preset = env.get('AUDIO_PRESET','natural')
    options(preset)
    target, ceiling, lra = PRESETS.get(preset, PRESETS['natural'])
    validated = options(preset, env.get('AUDIO_TARGET_LUFS',target),
                        env.get('AUDIO_TRUE_PEAK',ceiling),
                        env.get('AUDIO_FADE_SECONDS',0),env.get('AUDIO_NOISE_REDUCTION','0'))
    return dict(preset=preset,target=float(validated['AUDIO_TARGET_LUFS']),
                ceiling=float(validated['AUDIO_TRUE_PEAK']),lra=lra,
                fade=float(validated['AUDIO_FADE_SECONDS']),noise=validated['AUDIO_NOISE_REDUCTION']=='1',
                enabled=env.get('AUDIO_MASTERING','1')!='0' and env.get('AUDIO_NORMALIZE','1')!='0')


def enabled():
    return os.getenv('AUDIO_MASTERING','1') != '0' and os.getenv('AUDIO_NORMALIZE','1') != '0'


def export_settings(path):
    """Recover only validated nonsecret settings, without mutating process env."""
    for metadata in Path(path).parent.glob('*_metadata.json'):
        if metadata.stat().st_size > 16*1024*1024: raise ValueError('Oversized project metadata')
        data=json.loads(metadata.read_text(encoding='utf-8'))
        if not isinstance(data,dict): raise ValueError('Invalid project metadata')
        overrides=data.get('job_options',{})
        if not isinstance(overrides,dict): raise ValueError('Invalid project audio settings')
        return settings({k:v for k,v in overrides.items() if isinstance(k,str) and k.startswith('AUDIO_')})
    return settings()


def _run(command, deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0: raise TimeoutError('Audio mastering budget exhausted')
    return subprocess.run(command,check=True,capture_output=True,timeout=remaining)


def _read(path):
    try:
        if path.stat().st_size > 256*1024: return {}
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}


def _valid_measurements(value):
    if not isinstance(value,dict): return False
    if any(not isinstance(value.get(k),bool) for k in ('silent','possible_existing_clipping')): return False
    for key in ('integrated_lufs','true_peak_dbtp','lra','threshold','offset'):
        if key not in value: return False
        number=value[key]
        if number is not None and (not isinstance(number,(float,int)) or not math.isfinite(number)): return False
        if number is None and not value['silent']: return False
    silence=value.get('silences')
    return isinstance(silence,list) and all(isinstance(s,dict) and all(
        isinstance(s.get(k),(float,int)) and math.isfinite(s[k]) for k in ('start','end')) for s in silence)


def _save(path, value):
    fd, tmp = tempfile.mkstemp(prefix='.audio-report-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as file: json.dump(value,file,allow_nan=False)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.remove(tmp)


def _graph(cfg, duration, music=False):
    # No timestamp reset: a delayed source track keeps its picture-relative offset.
    graph='[0:a:0]anull[base];'
    if music:
        # Only an explicitly supplied separate music stem can be ducked. Never
        # pretend to separate music already mixed into the source dialogue.
        graph+=('[base]asplit=2[voice][side];'
                f'[1:a:0]aresample=48000,apad,atrim=duration={duration},volume=0.15[music];'
                '[music][side]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=300[ducked];'
                '[voice][ducked]amix=inputs=2:duration=first:normalize=0[mixed];')
        label='mixed'
    else: label='base'
    filters=[]
    if cfg['noise']: filters.append('afftdn=nr=6:nf=-50:tn=1')
    fade=min(cfg['fade'],duration/2)
    if fade:
        filters += [f'afade=t=in:st=0:d={fade}',f'afade=t=out:st={duration-fade}:d={fade}']
    graph+=f'[{label}]'+(','.join(filters) if filters else 'anull')+'[prepared];'
    return graph


def measure(path, cfg, duration, deadline, *, music=None, prepared=True):
    inputs=['-i',str(path)] + (['-i',str(music)] if music else [])
    graph=_graph(cfg,duration,bool(music)) if prepared else '[0:a:0]anull[prepared];'
    graph+=('[prepared]silencedetect=noise=-50dB:d=0.75,astats=metadata=0:reset=0,'
            f'loudnorm=I={cfg["target"]}:TP={cfg["ceiling"]}:LRA={cfg["lra"]}:print_format=json[measured]')
    process=_run(['ffmpeg','-hide_banner','-nostdin','-nostats','-threads','2',
                  '-filter_complex_threads','1',*inputs,'-filter_complex',graph,
                  '-map','[measured]','-vn','-f','null','-'],deadline)
    log=process.stderr.decode('utf-8',errors='replace')
    blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',log)
    if not blocks: raise ValueError('FFmpeg did not return loudness measurements')
    raw=json.loads(blocks[-1])
    def finite(value): return quality.number(value)
    silence=[]; start=None
    for match in re.finditer(r'silence_(start|end):\s*(-?[\d.]+)',log):
        kind,value=match[1],max(0,float(match[2]))
        if kind=='start': start=value
        elif start is not None:
            silence.append(dict(start=start,end=min(value,duration)));start=None
    if start is not None: silence.append(dict(start=start,end=duration))
    peaks=re.findall(r'Peak level dB:\s*([^\s]+)',log)
    counts=re.findall(r'Peak count:\s*([^\s]+)',log)
    peak=finite(peaks[-1]) if peaks else None
    return dict(integrated_lufs=finite(raw.get('input_i')),true_peak_dbtp=finite(raw.get('input_tp')),
                lra=finite(raw.get('input_lra')),threshold=finite(raw.get('input_thresh')),
                offset=finite(raw.get('target_offset')),silences=silence,
                sample_peak_dbfs=peak,peak_count=finite(counts[-1]) if counts else None,
                possible_existing_clipping=bool(peak is not None and peak>=-.01),
                silent=finite(raw.get('input_i')) is None)


def _normalizer(cfg, measured, ceiling):
    required=('integrated_lufs','true_peak_dbtp','lra','threshold','offset')
    if any(measured.get(key) is None for key in required): raise ValueError('Incomplete loudness analysis')
    return (f'loudnorm=I={cfg["target"]}:TP={ceiling}:LRA={cfg["lra"]}:'
            f'measured_I={measured["integrated_lufs"]}:measured_TP={measured["true_peak_dbtp"]}:'
            f'measured_LRA={measured["lra"]}:measured_thresh={measured["threshold"]}:'
            f'offset={measured["offset"]}:linear=true')


def master(path, *, config=None, music=None):
    """Master one final local MP4 atomically; at most two AAC encode attempts.

    music is an explicit trusted local stem, never a user-controlled FFmpeg arg.
    Returned report records silence as a review item, not a request to delete it.
    """
    path=Path(path).resolve(strict=True)
    cfg=config or export_settings(path)
    if not cfg.get('enabled',enabled()) or cfg['preset']=='original': return dict(status='DISABLED')
    if music is not None:
        music=Path(music).resolve(strict=True)
        if not music.is_file(): raise ValueError('Music stem must be a local file')
    identity=quality.fingerprint(path)
    key=dict(version=VERSION,settings=cfg,music=quality.fingerprint(music) if music else None,
             music_path=str(music) if music else None)
    sidecar=Path(str(path)+SUFFIX); previous=_read(sidecar)
    if previous.get('key')==key and previous.get('fingerprint')==identity and previous.get('status') in ('PASS','SILENT','NO_AUDIO'):
        return previous
    deadline=time.monotonic()+120
    info=quality.probe(path,timeout=10); video,audio=quality.streams(info)
    report=dict(key=key,fingerprint=identity,status='NO_AUDIO',attempts=0,warnings=[])
    if not audio:
        _save(sidecar,report);return report
    duration=quality.number((video or {}).get('duration'),quality.number(info.get('format',{}).get('duration')))
    if duration is None or not 0<duration<=10800: raise ValueError('Audio mastering requires a valid bounded video duration')
    audio_duration=quality.number(audio.get('duration'))
    if audio_duration is not None and not 0<audio_duration<=10800:
        raise ValueError('Audio mastering requires a valid bounded audio duration')
    # Analysis is cached independently so interrupted encodes can reuse it.
    analysis_path=Path(str(path)+'.audio-analysis.json'); cached=_read(analysis_path)
    if (cached.get('key')==key and cached.get('fingerprint')==identity
            and _valid_measurements(cached.get('measurements'))):
        before=cached['measurements']
    else:
        before=measure(path,cfg,duration,deadline,music=music)
        _save(analysis_path,dict(key=key,fingerprint=identity,measurements=before))
    report['before']=before
    if before['possible_existing_clipping']: report['warnings'].append('Source may already contain clipped peaks; normalization cannot reconstruct them.')
    if before['silences']: report['warnings'].append('Quiet intervals detected; review against speech context. No audio was removed.')
    if before['silent']:
        report.update(status='SILENT',after=before);_save(sidecar,report);return report
    if (not music and not cfg['noise'] and not cfg['fade']
            and abs(before['integrated_lufs']-cfg['target'])<=.5
            and before['true_peak_dbtp'] is not None and before['true_peak_dbtp']<=cfg['ceiling']):
        report.update(status='PASS',after=before)
        _save(sidecar,report);return report
    fd, tmp=tempfile.mkstemp(prefix='.audio-master-',suffix='.mp4',dir=path.parent);os.close(fd)
    try:
        ceiling=cfg['ceiling']-.8  # AAC intersample headroom, verified after encoding.
        for attempt in range(2):
            # loudnorm's resampling/lookahead can append an encoded tail. Limit
            # only to the original AUDIO duration (not video length); preserve
            # delayed starts and intentionally shorter source tracks.
            trim=f',atrim=duration={audio_duration:.9f}' if audio_duration is not None else ''
            graph=_graph(cfg,duration,bool(music))+'[prepared]'+_normalizer(cfg,before,ceiling)+trim+'[mastered]'
            _run(['ffmpeg','-v','error','-nostdin','-y','-copyts','-start_at_zero',
                  '-threads','2','-filter_complex_threads','1','-i',str(path),
                  *(['-i',str(music)] if music else []),'-filter_complex',graph,
                  '-map','0:v:0','-map','[mastered]','-c:v','copy','-c:a','aac',
                  '-ar','48000','-b:a','192k','-map_metadata','0','-movflags','+faststart',tmp],deadline)
            after=measure(tmp,cfg,duration,deadline,prepared=False)
            report.update(attempts=attempt+1,after=after)
            peak=after['true_peak_dbtp']
            if peak is not None and peak<=cfg['ceiling']+.05: break
            if peak is None: raise ValueError('Encoded audio peak could not be verified')
            ceiling-=max(1.,peak-cfg['ceiling']+.8)
        else: raise ValueError('AAC true peak still exceeds the configured ceiling after two attempts')
        out=quality.probe(tmp,timeout=10); out_video,out_audio=quality.streams(out)
        origin=quality.number(info.get('format',{}).get('start_time'),0)
        output_origin=quality.number(out.get('format',{}).get('start_time'),0)
        for original,encoded in ((video,out_video),(audio,out_audio)):
            if not original or not encoded: raise ValueError('Mastering lost an expected stream')
            for field in ('start_time','duration'):
                a,b=quality.number(original.get(field)),quality.number(encoded.get(field))
                if field=='start_time' and a is not None and b is not None:
                    a-=origin; b-=output_origin
                if a is not None and b is not None and abs(a-b)>.06:
                    raise TimingError(original.get('codec_type','stream'),field,a,b)
        if quality.fingerprint(path)!=identity: raise ValueError('Source changed during mastering')
        if abs(after['integrated_lufs']-cfg['target'])>1.5:
            report['warnings'].append('Loudness target limited by peak headroom or source dynamics.')
        os.replace(tmp,path)
        report.update(status='PASS',fingerprint=quality.fingerprint(path))
        _save(sidecar,report)
        return report
    finally:
        if os.path.exists(tmp): os.remove(tmp)
