"""Source-clock pacing plans consumed by the existing recut/director pipeline."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from clip_selection import valid_range, speech_units

VERSION=1
MODES={
    'fast':dict(lead=.10,tail=.20,min_gap=1.,keep=.4),
    'balanced':dict(lead=.15,tail=.35,min_gap=1.8,keep=.8),
    'emotional':dict(lead=.35,tail=.85,min_gap=float('inf'),keep=2.),
    'educational':dict(lead=.20,tail=.55,min_gap=2.5,keep=1.2),
}


def settings(mode=None,trim=None):
    mode=mode or os.getenv('PACING_MODE','balanced')
    if mode not in MODES:raise ValueError('pacing_mode must be fast, balanced, emotional or educational')
    if trim is None:trim=os.getenv('PACING_TRIM_SILENCE','0')=='1'
    return dict(mode=mode,trim_silence=bool(trim),allow_incomplete=os.getenv('PACING_ALLOW_INCOMPLETE_END','0')=='1')


def detect_silence(source,start,end,cache_dir=None):
    """Bounded, source-timed FFmpeg audio measurement; failed probes are not silence."""
    if not valid_range(start,end,1e12) or end-start>180:return dict(available=False,intervals=[])
    try:
        stat=Path(source).stat()
        key=hashlib.sha256(json.dumps([VERSION,str(Path(source).resolve()),stat.st_size,stat.st_mtime_ns,start,end,-42,.35]).encode()).hexdigest()
        path=Path(cache_dir)/'pacing_silence.json' if cache_dir else None
        cache={}
        if path:
            try:cache=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        if not isinstance(cache,dict):cache={}
        saved=cache.get(key)
        if isinstance(saved,dict) and saved.get('available') is True and isinstance(saved.get('intervals'),list):
            if all(isinstance(r,list) and len(r)==2 and all(type(v) in (float,int) for v in r)
                   and valid_range(r[0],r[1],end) and r[0]>=start for r in saved['intervals']):
                return {**saved,'cache_hit':True}
        result=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-v','info','-ss',str(start),'-t',str(end-start),
            '-i',str(source),'-map','0:a:0','-vn','-sn','-dn','-af','silencedetect=noise=-42dB:d=0.35',
            '-f','null','-'],capture_output=True,timeout=45)
        if result.returncode:return dict(available=False,intervals=[])
        intervals=[];opened=None
        text=(result.stderr or b'').decode('utf-8','replace')
        for kind,value in re.findall(r'silence_(start|end):\s*(-?[0-9]+(?:\.[0-9]+)?)',text):
            at=max(float(start),min(float(end),float(start)+float(value)))
            if kind=='start':opened=at
            elif opened is not None:
                if at>opened:intervals.append([round(opened,4),round(at,4)])
                opened=None
        if opened is not None and end>opened:intervals.append([round(opened,4),float(end)])
        measured=dict(available=True,intervals=intervals,threshold_dbfs=-42,min_silence_seconds=.35)
        if path:
            cache[key]=measured
            # Bound retained measurements; no failures are cached.
            from story_director import atomic_json
            atomic_json(path,dict(list(cache.items())[-64:]))
        return measured
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):return dict(available=False,intervals=[])


def _overlaps(a,b,rows):
    return any(min(b,y)>max(a,x) for x,y in rows)


def story_protection(clip,units,moments,duration):
    """Only a shared timed evidence anchor can connect a nearby setup/payoff."""
    import story_director
    own=story_director.grounded_story(clip,units,moments)
    signature=lambda e:(e['start'],e['end'],e['channel'],e.get('quote') or e.get('description'))
    anchors={signature(e) for e in own['evidence']}
    protected=[];required=[]
    stories=[own]
    for moment in moments:
        if not isinstance(moment,dict) or not valid_range(moment.get('start'),moment.get('end'),duration):continue
        if moment['end']<=clip['start'] or moment['start']>=clip['end']:continue
        story=story_director.grounded_story(moment,units,moments)
        if anchors & {signature(e) for e in story['evidence']}:stories.append(story)
        if moment.get('preserve_context'):protected.append((moment['start'],moment['end']))
    for story in stories:
        evidence={e['id']:e for e in story['evidence']}
        if story['mode'] in ('emotional','comedy') and evidence:
            # Emotional hesitation and comedic setup-to-punchline timing are content.
            protected.append((min(e['start'] for e in evidence.values()),max(e['end'] for e in evidence.values())))
        for e in evidence.values():
            if e['channel']!='transcript':
                protected.append((e['start'],e['end']))
                required.append((e['start'],e['end']))
        for beat in story['beats']:
            for ident in beat['evidence_ids']:
                if ident not in evidence:continue
                e=evidence[ident];span=(e['start'],e['end'])
                if beat['role'] in ('setup','stakes','outcome','punchline','takeaway','reaction'):required.append(span)
                if beat['role'] in ('reaction','outcome','punchline'):protected.append(span)
    return protected,required


def repeated_dialogue(units,start,end):
    """Review cues only: repetition may be deliberate, or a second speaker's reply."""
    active=[u for u in units if start<=u['start'] and u['end']<=end]
    repeats=[]
    for left,right in zip(active,active[1:]):
        normalize=lambda text:re.sub(r'[^\w\s]','',text.casefold()).split()
        words=normalize(left['text'])
        if len(words)>=4 and words==normalize(right['text']) and right['start']-left['end']<=5:
            repeats.append(dict(first=[left['start'],left['end']],repeat=[right['start'],right['end']],
                same_known_speaker=left.get('speaker') is not None and left.get('speaker')==right.get('speaker'),
                action='preserved_for_review',reason='Repeated wording can be meaningful emphasis or an exchange.'))
    return repeats


def boundaries(start,end,units,duration,config,required=(),scene_cuts=(),preserve_visual=False):
    """Grow onto complete speech/context, never manufacture a target-length cutoff."""
    if not valid_range(start,end,duration):raise ValueError('Invalid source range')
    a,b=float(start),float(end)
    if required:a=min(a,min(x for x,y in required));b=max(b,max(y for x,y in required))
    if not valid_range(a,b,duration):raise ValueError('Story evidence lies outside the source')
    touched=[u for u in units if u['end']>a and u['start']<b]
    if not touched:return round(a,3),round(b,3),['No timed speech: sentence checks are not applicable.']
    # Closure handles any number of overlapping speakers, including newly exposed turns.
    for _ in range(len(units)+1):
        active=[u for u in units if u['end']>a and u['start']<b]
        na=min([a]+[u['start'] for u in active]);nb=max([b]+[u['end'] for u in active])
        if (na,nb)==(a,b):break
        a,b=na,nb
    last=max((u for u in units if u['end']>a and u['start']<b),key=lambda u:u['end'])
    warnings=[]
    if not last['complete'] and not config['allow_incomplete']:
        completion=None;cursor=last['end']
        for unit in sorted((u for u in units if u['start']>=last['end']),key=lambda u:u['start']):
            different=(last.get('speaker') is not None and unit.get('speaker') is not None and last['speaker']!=unit['speaker'])
            if (unit['start']-cursor>1.2 or unit['end']-b>8 or different or
                    any(cursor<=t<=unit['start'] for t in scene_cuts)):break
            cursor=max(cursor,unit['end'])
            if unit['complete']:completion=unit;break
        if completion is None:raise ValueError('Abrupt ending: no connected complete final sentence is available')
        b=completion['end']
        # Extending for an ending must not expose half of an overlapping turn.
        for _ in range(len(units)+1):
            active=[u for u in units if u['end']>a and u['start']<b]
            nb=max([b]+[u['end'] for u in active])
            if nb==b:break
            b=nb
        last=max(active,key=lambda u:u['end'])
        if not last['complete']:raise ValueError('An overlapping speaker still has an incomplete ending')
    elif not last['complete']:warnings.append('Incomplete final sentence intentionally allowed by configuration.')
    active=[u for u in units if u['end']>a and u['start']<b]
    first=min(active,key=lambda u:u['start']);last=max(active,key=lambda u:u['end'])
    previous=max([0]+[u['end'] for u in units if u['end']<=first['start']])
    following=min([duration]+[u['start'] for u in units if u['start']>=last['end']])
    policy=MODES[config['mode']]
    left=max(previous,first['start']-policy['lead']);right=min(following,last['end']+policy['tail'])
    if preserve_visual:left=min(left,a);right=max(right,b)
    if required:left=min(left,min(x for x,y in required));right=max(right,max(y for x,y in required))
    def safe(t):return not any(u['start']<t<u['end'] for u in units)
    for side in ('left','right'):
        edge=left if side=='left' else right
        cuts=[float(t) for t in scene_cuts if valid_range(0,t,duration) and abs(float(t)-edge)<=.35 and safe(float(t))
              and (previous<=float(t)<=first['start'] if side=='left' else last['end']<=float(t)<=following)
              and not (preserve_visual and (float(t)>a if side=='left' else float(t)<b))
              and not any(float(t)>x if side=='left' else float(t)<y for x,y in required)]
        if cuts:
            if side=='left':left=min(cuts,key=lambda t:abs(t-edge))
            else:right=min(cuts,key=lambda t:abs(t-edge))
    if any(u['start']<left<u['end'] or u['start']<right<u['end'] for u in units):raise ValueError('A boundary intersects speech')
    if right-left>180:raise ValueError('Complete story exceeds the 180-second export limit')
    return round(max(0,left),3),round(min(duration,right),3),warnings


def plan(clip,transcript,duration,config=None,moments=(),scene_cuts=(),measure=None):
    """Pure decisions plus injected measurement. Output source ranges are authoritative."""
    import recut
    config=config or settings()
    units=speech_units(transcript,duration)
    scene_cuts=[float(t) for t in (scene_cuts or ()) if valid_range(0,t,duration)]
    original=(clip.get('recipe') or {}).get('segments') or [dict(start=clip['start'],end=clip['end'])]
    if any(not valid_range(s.get('start'),s.get('end'),duration) for s in original):raise ValueError('Invalid source segment')
    if any(right['start']<left['end'] for left,right in zip(original,original[1:])):
        raise ValueError('Automatic pacing requires chronological non-overlapping source segments')
    parts=[];warnings=[];removed=[];repeat=[];audio_available=False
    for selected in original:
        source_clip={**clip,**selected}
        protected,required=story_protection(source_clip,units,moments,duration)
        import editing_skills
        protected.extend(editing_skills.protect_dialogue(units))
        a,b,notes=boundaries(selected['start'],selected['end'],units,duration,config,required,scene_cuts,
            preserve_visual=bool(clip.get('visual_evidence') or not transcript))
        warnings.extend(notes);repeat.extend(repeated_dialogue(units,a,b))
        measured=measure(a,b) if measure and b-a<=180 and (config['trim_silence'] or len(original)>1) else dict(available=False,intervals=[])
        audio_available=audio_available or measured.get('available',False)
        ranges=[[a,b]]
        if config['trim_silence'] and config['mode']!='emotional' and measured.get('available'):
            policy=MODES[config['mode']]
            active=[u for u in units if a<=u['start'] and u['end']<=b]
            for left,right in zip(active,active[1:]):
                lo,hi=left['end'],right['start']
                # Same known speaker, complete adjacent sentences, same shot,
                # no protected reaction/action, AND measured quiet audio.
                if (hi-lo<policy['min_gap'] or not left['complete'] or not right['complete'] or
                    left.get('speaker') is None or left.get('speaker')!=right.get('speaker') or
                    _overlaps(lo,hi,protected) or any(lo<=t<=hi for t in scene_cuts)):continue
                cut_a=round(lo+policy['keep']/2,3);cut_b=round(hi-policy['keep']/2,3)
                quiet=any(valid_range(x,y,duration) and x<=cut_a and y>=cut_b for x,y in measured.get('intervals',[]))
                if not quiet or cut_b-cut_a<.35 or any(_overlaps(cut_a,cut_b,[(u['start'],u['end'])]) for u in units):continue
                if len(parts)+len(ranges)>=recut.MAX_SEGMENTS:break
                if ranges[-1][1]-cut_b<recut.MIN_SEGMENT_SECONDS or cut_a-ranges[-1][0]<recut.MIN_SEGMENT_SECONDS:continue
                ranges[-1][1]=cut_a;ranges.append([cut_b,b]);removed.append(dict(start=cut_a,end=cut_b,reason='Measured silence between complete same-speaker sentences.'))
        elif config['trim_silence'] and not measured.get('available'):
            warnings.append('Silence measurement unavailable: source pauses preserved.')
        for x,y in ranges:
            if parts and x<parts[-1]['end']:
                # Boundary extensions may overlap; merge instead of replaying dialogue.
                parts[-1]['end']=max(parts[-1]['end'],y)
            else:parts.append(dict(start=x,end=y))
    parts=recut.normalize_segments(parts,duration)
    total=recut.total_duration(parts)
    if config['trim_silence'] and not removed:
        warnings.append('No eligible quiet gap established; source pauses preserved.')
    return dict(version=VERSION,mode=config['mode'],segments=parts,output_duration=total,
        original_segments=original,removed_silence=removed,repeated_dialogue=repeat,
        warnings=list(dict.fromkeys(warnings)),audio_available=audio_available,
        transition='straight',audio_join_fade_ms=8 if len(parts)>1 and audio_available else 0,
        validation=dict(no_half_spoken_boundaries=True if units else None,complete_ending=not any('intentionally allowed' in w for w in warnings) if units else None,
            source_order=True,source_ranges_valid=True),target_policy='Soft target; complete speech and protected source beats take priority.')


def prepare_clips(clips,transcript,duration,source,cache_dir,analysis=None,config=None):
    """One post-selection pass, preserving renderer/editor source recipes."""
    config=config or settings();accepted=[];rejected=[]
    for original in clips:
        clip=copy.deepcopy(original)
        if clip.get('manual_override') is True or clip.get('assembly_locked') is True or (clip.get('recipe') or {}).get('origin')=='manual':
            accepted.append(clip);continue
        try:
            report=plan(clip,transcript,duration,config,(analysis or {}).get('moments',()),
                (analysis or {}).get('scene_cuts',()),lambda a,b:detect_silence(source,a,b,cache_dir))
            parts=report['segments']
            changed=parts!=((clip.get('recipe') or {}).get('segments') or [dict(start=clip['start'],end=clip['end'])])
            if changed or clip.get('recipe'):
                clip['recipe']={**(clip.get('recipe') or {}),'v':1,'segments':parts,'source_montage':True,
                    'canonical_range':dict(start=0.,end=report['output_duration']),
                    'pacing_audio_continuity':report['audio_available']}
                clip.update(start=0.,end=report['output_duration'],duration=report['output_duration'])
                if clip.get('story_report'):
                    clip['story_report']['source_ranges']=parts
                    clip['story_report'].setdefault('limitations',[]).append('Pacing adjusted source ranges; scores retain the source analysis before pacing.')
            clip['pacing_report']=report;accepted.append(clip)
        except (ValueError,TypeError,KeyError) as exc:
            rejected.append(dict(start=original.get('start'),end=original.get('end'),reason=str(exc)))
    return accepted,rejected
