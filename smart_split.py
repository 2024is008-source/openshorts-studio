"""Smart Split extension of existing pacing/recut. No models or extra Director.

Every accepted operation changes the source recipe consumed by native FFmpeg.
Uncertain material is retained. No sentence is rewritten or scene fabricated.
"""
import copy
import hashlib
import json
import math
import re

VERSION=1
REMOVABLE={'opening_silence','irrelevant_pause','trailing_silence','duplicate_explanation','off_topic','redundant_visual','empty','redundant_attempt'}
PROTECTED={'hook','stakes','setup','punchline','attempt','action','obstacle','result','reaction','before','after','milestone','emotional','explanation'}


def valid(a,b,duration):
    return all(type(x) in (int,float) and math.isfinite(x) for x in (a,b,duration)) and 0<=a<b<=duration


def overlap(a,b,rows):return any(a<y and b>x for x,y in rows)


def mapping(segments):
    offset=0.;rows=[]
    for i,s in enumerate(segments):
        end=round(offset+s['end']-s['start'],6)
        rows.append(dict(index=i,source_start=s['start'],source_end=s['end'],start=offset,end=end))
        offset=end
    return rows


def subtract(parts,a,b):
    out=[]
    for s in parts:
        if b<=s['start'] or a>=s['end']:out.append(s);continue
        if a>s['start']:out.append(dict(start=s['start'],end=a))
        if b<s['end']:out.append(dict(start=b,end=s['end']))
    return out


def category(analysis):
    import category_intelligence as ci
    choice=(analysis or {}).get('category_selection') or {}
    try:
        primary,sub=ci.resolve(choice.get('primary_category','general'),choice.get('subcategory','auto'))
        return dict(primary_category=primary,subcategory=sub)
    except ValueError:return dict(primary_category='general',subcategory='auto')


def plan(clip,transcript,duration,analysis=None,measure=None,profile='balanced'):
    """Conservative source-clock removals inside an already selected candidate."""
    import recut,pacing,editing_skills
    from clip_selection import speech_units
    analysis=analysis or {};choice=category(analysis)
    original=copy.deepcopy((clip.get('recipe') or {}).get('segments') or [dict(start=clip['start'],end=clip['end'])])
    # Manual and locked recipes are authoritative; regeneration never overwrites.
    locked=clip.get('manual_override') is True or clip.get('assembly_locked') is True or (clip.get('recipe') or {}).get('origin')=='manual'
    for s in original:
        if not valid(s.get('start'),s.get('end'),duration):raise ValueError('Invalid Smart Split source range')
    if any(y['start']<x['end'] for x,y in zip(original,original[1:])):
        locked=True  # Existing user-ordered recipes remain untouched.
    units=speech_units(transcript,duration)
    words=recut.transcript_words(transcript)
    speech=[(u['start'],u['end']) for u in units]
    protected=editing_skills.protect_dialogue(units)
    protected_roles=[]
    for moment in analysis.get('moments',[]):
        if not isinstance(moment,dict) or not valid(moment.get('start'),moment.get('end'),duration):continue
        if moment.get('preserve_context') or moment.get('role') in PROTECTED:
            protected.append((moment['start'],moment['end']));protected_roles.append(dict(start=moment['start'],end=moment['end'],role=moment.get('role','context')))
        for cue in moment.get('editing_cues',[]):
            if cue.get('kind') in ('serious','reaction','reveal','action') and valid(cue.get('start'),cue.get('end'),duration):protected.append((cue['start'],cue['end']))
    scenes=analysis.get('scene_observations',[])
    for scene in scenes:
        if not isinstance(scene,dict) or not valid(scene.get('start'),scene.get('end'),duration):continue
        if scene.get('preserve_context') or scene.get('editorial_role') in PROTECTED:
            protected.append((scene['start'],scene['end']))
            protected_roles.append(dict(start=scene['start'],end=scene['end'],role=scene.get('editorial_role','context')))
    parts=copy.deepcopy(original);operations=[];skipped=[]
    sports=choice['primary_category']=='sports_highlights'
    comedy=choice['primary_category']=='podcast' and choice['subcategory']=='comedy'
    conservative=profile=='minimal' or sports or comedy or locked
    def remove(a,b,kind,evidence):
        nonlocal parts
        if conservative or kind not in REMOVABLE or not valid(a,b,duration):return False
        if overlap(a,b,protected):return False
        if any(w['s']<a<w['e'] or w['s']<b<w['e'] for w in words):return False
        if not any(s['start']<=a<b<=s['end'] for s in parts):return False
        proposed=subtract(parts,a,b)
        if not proposed or len(proposed)>recut.MAX_SEGMENTS or any(s['end']-s['start']<recut.MIN_SEGMENT_SECONDS for s in proposed):return False
        if recut.total_duration(proposed)<1:return False
        parts=proposed
        operations.append(dict(type='remove',reason=kind,source_start=a,source_end=b,evidence=evidence,origin='automatic',review='unreviewed'))
        return True
    cuts=[x for x in analysis.get('scene_cuts',[]) if type(x) in (int,float) and math.isfinite(x)]
    for selected in original:
        a,b=selected['start'],selected['end']
        if conservative:continue
        measured=measure(a,b) if measure and b-a<=180 else {}
        if not isinstance(measured,dict) or measured.get('available') is not True:continue
        for interval in measured.get('intervals',[]):
            if not isinstance(interval,(list,tuple)) or len(interval)!=2:continue
            lo,hi=interval
            if not valid(lo,hi,duration):continue
            lo=max(a,lo);hi=min(b,hi)
            if hi-lo<2.5 or overlap(lo,hi,speech):continue
            if any(lo<t<hi for t in cuts):continue
            # Silence alone cannot establish that unseen footage is empty.
            # Require an inspected low-value shot, or stable speech-turn gap.
            watched=any(isinstance(s,dict) and s.get('editorial_role') in ('empty','irrelevant_pause')
                and type(s.get('confidence')) in (float,int) and .9<=s['confidence']<=1
                and valid(s.get('start'),s.get('end'),duration) and s['start']<=lo and s['end']>=hi for s in scenes)
            left=max((u for u in units if u['end']<=lo+.05),key=lambda u:u['end'],default=None)
            right=min((u for u in units if u['start']>=hi-.05),key=lambda u:u['start'],default=None)
            same=left and right and left.get('speaker') is not None and left.get('speaker')==right.get('speaker') and left['complete'] and right['complete'] and hi-lo<15
            # A speaker can pause while a challenge/action continues on screen.
            # Audio-only gap evidence is sufficient only for non-comedy podcast.
            if not watched and not (same and choice['primary_category']=='podcast'):continue
            padding=.6 if choice['primary_category']=='podcast' else .4
            remove(round(lo+padding,3),round(hi-padding,3),'irrelevant_pause','Measured quiet audio and inspected empty footage or complete same-speaker turns; no protected beat.')
    # Semantically optional footage is usable only when explicitly marked by
    # existing analysis and it does not intersect a necessary source beat.
    for scene in scenes:
        if not isinstance(scene,dict):continue
        kind=scene.get('editorial_role');a,b=scene.get('start'),scene.get('end')
        if kind not in REMOVABLE or not valid(a,b,duration) or type(scene.get('confidence')) not in (float,int) or not .95<=scene['confidence']<=1:continue
        if not scene.get('layout_evidence') or not scene.get('event'):continue
        if kind in ('off_topic','duplicate_explanation','redundant_attempt'):
            contained=[u for u in units if a<=u['start'] and u['end']<=b]
            if not contained or any(not u['complete'] for u in contained):continue
            if any(u['start']<a<u['end'] or u['start']<b<u['end'] for u in units):continue
            # General/podcast explanations are not silently removed as digressions.
            if choice['primary_category']!='challenge':continue
            if kind=='duplicate_explanation':
                ref=scene.get('duplicate_of_start')
                other=next((u for u in units if type(ref) in (int,float) and abs(u['start']-ref)<.1),None)
                normalize=lambda x:re.sub(r'\W+',' ',x.casefold()).strip()
                if not other or other['start']>=a or not any(s['start']<=other['start']<other['end']<=s['end'] for s in parts):continue
                if normalize(other['text'])!=normalize(' '.join(u['text'] for u in contained)):continue
                if any(u.get('speaker') is None or u.get('speaker')!=other.get('speaker') for u in contained):continue
        elif overlap(a,b,speech):continue
        if not remove(a,b,kind,'Explicit high-confidence source observation; complete speech and protected-story checks passed.'):
            skipped.append(dict(start=a,end=b,reason='Protected context, boundary, profile or source-range constraint.'))
    mapping_rows=mapping(parts)
    for i,row in enumerate(mapping_rows):
        operations.append(dict(type='retain' if not i else 'split_join',source_start=row['source_start'],source_end=row['source_end'],
            output_start=row['start'],output_end=row['end'],reason='Keep source chronology and complete selected context.',transition='hard_cut'))
    return dict(version=VERSION,category=choice,profile=profile,original_segments=original,segments=parts,
        output_duration=round(sum(s['end']-s['start'] for s in parts),3),mapping=mapping_rows,operations=operations,
        story_order=sorted([r for r in protected_roles if any(s['start']<r['end'] and s['end']>r['start'] for s in parts)],key=lambda r:r['start']),
        locked=locked,skipped=skipped[:64],source_order_preserved=True,
        limitations=['No missing beat is fabricated. Uncertain repetition, reactions, sporting play and emotion are retained.'])


def apply(clips,transcript,duration,source,cache_dir,analysis=None,profile='balanced'):
    import pacing,recut
    result=[]
    for original in clips:
        clip=copy.deepcopy(original)
        chosen_profile=(clip.get('auto_edit') or {}).get('profile',profile)
        report=plan(clip,transcript,duration,analysis,lambda a,b:pacing.detect_silence(source,a,b,cache_dir),chosen_profile)
        if report['segments']!=report['original_segments']:
            clip['recipe']={**(clip.get('recipe') or {}),'v':1,'segments':report['segments'],'source_montage':True,
                'canonical_range':dict(start=0.,end=report['output_duration']),'pacing_audio_continuity':True}
            clip.update(start=0.,end=report['output_duration'],duration=report['output_duration'])
            if clip.get('story_report'):
                clip['story_report']['source_ranges']=copy.deepcopy(report['segments'])
                clip['story_report'].setdefault('limitations',[]).append('Smart Split removed optional intervals after source selection; original ranking is not an assembly quality score.')
            clip['ranking_stale']=True
        clip['assembly_report']=report
        result.append(clip)
        observe(report,source)
        removed=sum(o['source_end']-o['source_start'] for o in report['operations'] if o['type']=='remove')
        print(f"   Smart Split: {len(report['segments'])} source sections; {removed:.2f}s removed; chronology preserved.",flush=True)
    return result


def observe(report,source,store=None):
    import os
    if os.getenv('OPENSHORTS_LEARNING_DISABLED')=='1':return
    try:
        from learning.database import Store
        store=store or Store()
        if not store.preferences()['collect']:return
        identity=hashlib.sha256(str(source).encode()).hexdigest()
        data=dict(task='smart-split',source_group=identity,report=report,review='unreviewed',training_label=False)
        token=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        store.put('editing_decisions',token,data,category=report['category']['primary_category'],status='unreviewed')
    except (OSError,ValueError,__import__('sqlite3').Error):pass
