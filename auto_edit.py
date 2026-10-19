"""Evidence-driven effects for the existing director and timeline compositors.

No media discovery, model calls, transcript generation or shell commands. All
times are assembled clip seconds; source observations are mapped at the boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from difflib import SequenceMatcher
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION=1
PROFILES=json.loads((Path(__file__).parent/'assets/auto_edit_profiles.json').read_text())
CAMERA={'smooth_zoom_in','smooth_zoom_out','fast_punch_in','snap_zoom','zoom_bounce','smart_camera_pan','face_tracking','subject_tracking'}
VIDEO={'controlled_shake','motion_blur','fade'}
TEXT={'kinetic_captions','word_pop','keyword_highlight','animated_hook','number_highlight','text_reveal'}
NATIVE={'smart_split','picture_in_picture','blurred_background','scene_aware_crop','context_wide','clean_jump_cut'}
AUDIO={'dialogue_normalization','music_ducking'}
UNSUPPORTED={'whip_pan','freeze_frame','speed_ramp','slow_motion','cross_dissolve','beat_cut','directional_transition','whoosh','impact_accent','pop_sound'}
SUPPORTED=CAMERA|VIDEO|TEXT|NATIVE|AUDIO
DELEGATED=NATIVE|{'animated_hook','music_ducking'}
EASINGS=('linear','ease_in','ease_out','ease_in_out','smoothstep','overshoot')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class Limits(Strict):
    max_effects: int=Field(default=5,ge=0,le=24,strict=True)
    camera_gap: float=Field(default=5,ge=1,le=60)
    max_zoom: float=Field(default=1.10,ge=1,le=1.18)
    max_shake: float=Field(default=.002,ge=0,le=.006)
    min_duration: float=Field(default=.35,ge=.15,le=3)
    max_duration: float=Field(default=5,ge=.3,le=12)
    motion_sensitivity: float=Field(default=.75,ge=.5,le=1)

    @model_validator(mode='after')
    def ordered(self):
        if self.max_duration<self.min_duration:raise ValueError('Effect duration limits are reversed.')
        return self


class Scene(Strict):
    id: str=Field(min_length=1,max_length=64)
    start: float=Field(ge=0)
    end: float=Field(gt=0)
    source_start: float=Field(ge=0)
    source_end: float=Field(gt=0)
    shot_type: str=Field(max_length=40)
    visible_subjects: list[dict]=Field(default_factory=list,max_length=32)
    important_regions: list[dict]=Field(default_factory=list,max_length=32)
    speech: list[dict]=Field(default_factory=list,max_length=500)
    motion: dict=Field(default_factory=dict)
    transition: Literal['source_cut','shot_boundary','edit_join','unknown']='unknown'
    confidence: float=Field(ge=0,le=1)
    safe_zoom: float=Field(default=1,ge=1,le=1.18)
    cues: list[dict]=Field(default_factory=list,max_length=64)
    observations: list[dict]=Field(default_factory=list,max_length=32)
    caption_regions: list[dict]=Field(default_factory=list,max_length=32)


class Parameters(Strict):
    zoom: float=Field(default=1.06,ge=1,le=1.18)
    x: float=Field(default=.5,ge=0,le=1)
    y: float=Field(default=.5,ge=0,le=1)
    amount: float=Field(default=.002,ge=0,le=.006)
    direction: Literal['in','out']='in'
    quote: str=Field(default='',max_length=300)


class Effect(Strict):
    id: str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    type: str=Field(min_length=1,max_length=40)
    category: Literal['camera','motion','transition','text','audio','composition']
    source_scene: str=Field(min_length=1,max_length=64)
    start: float=Field(ge=0)
    end: float=Field(gt=0)
    duration: float=Field(gt=0)
    intensity: float=Field(default=.65,ge=0,le=1)
    easing: Literal['linear','ease_in','ease_out','ease_in_out','smoothstep','overshoot']='smoothstep'
    anchor: list[float]=Field(default_factory=lambda:[.5,.5],min_length=2,max_length=2)
    target_subject: str | None=Field(default=None,max_length=80)
    reason: str=Field(min_length=1,max_length=600)
    confidence: float=Field(ge=0,le=1)
    parameters: Parameters=Field(default_factory=Parameters)
    origin: Literal['ai','manual']='ai'
    enabled: bool=Field(default=True,strict=True)

    @model_validator(mode='after')
    def safe(self):
        if self.type not in SUPPORTED|UNSUPPORTED:raise ValueError('Unknown effect type.')
        if self.end<=self.start or abs(self.duration-(self.end-self.start))>.001:raise ValueError('Effect duration does not match its interval.')
        if any(not math.isfinite(v) or not 0<=v<=1 for v in self.anchor):raise ValueError('Effect anchors must be normalized.')
        expected=category(self.type)
        if self.type in SUPPORTED and self.category!=expected:raise ValueError('Effect category does not match its renderer.')
        return self


class AutoEdit(Strict):
    version: Literal[1]=1
    enabled: bool=Field(default=True,strict=True)
    profile: Literal['minimal','balanced','dynamic','cinematic','custom']='balanced'
    zoom: bool=Field(default=True,strict=True)
    tracking: bool=Field(default=True,strict=True)
    transitions: bool=Field(default=True,strict=True)
    text: bool=Field(default=True,strict=True)
    audio: bool=Field(default=False,strict=True)
    limits: Limits=Field(default_factory=Limits)
    effects: list[Effect]=Field(default_factory=list,max_length=100)
    scenes: list[Scene]=Field(default_factory=list,max_length=2000)
    skipped: list[dict]=Field(default_factory=list,max_length=100)
    source_segments: list[dict]=Field(default_factory=list,max_length=12)
    skill_plan: dict | None = None


def category(kind):
    if kind in CAMERA:return 'camera'
    if kind in TEXT:return 'text'
    if kind in AUDIO:return 'audio'
    if kind in NATIVE:return 'composition' if kind!='clean_jump_cut' else 'transition'
    return 'transition' if kind=='fade' else 'motion'


def ease(value,kind='smoothstep'):
    t=max(0.,min(1.,value))
    if kind=='linear':return t
    if kind=='ease_in':return t*t
    if kind=='ease_out':return 1-(1-t)**2
    if kind=='ease_in_out':return 2*t*t if t<.5 else 1-(-2*t+2)**2/2
    if kind=='overshoot':return 1+2.2*(t-1)**3+1.2*(t-1)**2
    return t*t*(3-2*t)


def defaults(profile='balanced'):
    return AutoEdit(profile=profile,limits=Limits(**PROFILES.get(profile,PROFILES['balanced']))).model_dump(mode='json')


def normalize(value,duration):
    result=AutoEdit.model_validate(value).model_dump(mode='json')
    import editing_skills
    editing_skills.validate(result['skill_plan'],duration)
    scenes={s['id']:s for s in result['scenes']}
    if len(scenes)!=len(result['scenes']):raise ValueError('Duplicate scene IDs.')
    for s in scenes.values():
        if not 0<=s['start']<s['end']<=duration+.001 or s['source_end']<=s['source_start']:raise ValueError('Scene exceeds the clip.')
    seen=set()
    for e in result['effects']:
        if e['id'] in seen:raise ValueError('Duplicate effect IDs.')
        seen.add(e['id']);s=scenes.get(e['source_scene'])
        if not s or e['start']<s['start']-.001 or e['end']>s['end']+.001:raise ValueError('An effect crosses its scene boundary.')
        if e['type'] in UNSUPPORTED|DELEGATED:
            if len(result['skipped'])<100 and not any(r.get('effect_id')==e['id'] for r in result['skipped']):
                result['skipped'].append(dict(effect_id=e['id'],type=e['type'],reason=
                    'Use the existing layout, hook or imported music controls; this timed override is not supported.' if e['type'] in DELEGATED else
                    'No safe timing/asset adapter is available; this optional effect is skipped.'))
    return result


def scene_records(plan,analysis=None):
    """Reuse sampled tracking, protected regions, words and Gemini observations."""
    output=[]
    clip_speech=[dict(text=c['text'],start=c['start'],end=c['end']) for c in plan['captions']]
    for i,shot in enumerate(plan['shots']):
        keys=shot['keyframes'];motion={'method':'retained_crop_path','samples':len(keys),'camera_pan_pixels':0.0}
        audio=plan.get('audio') or {};window=audio.get('window_seconds',.2)
        values=audio.get('energy',[])[int(shot['start']/window):int(shot['end']/window)+1]
        motion['relative_audio_peak']=max(values,default=None)
        motion['quiet_intervals']=[r for r in audio.get('quiet_intervals',[]) if r[0]>=shot['start'] and r[1]<=shot['end']]
        motion['beat_evidence']='Unavailable; loudness peaks are not assumed to be music beats.'
        if keys:motion['camera_pan_pixels']=round(max(k['x'] for k in keys)-min(k['x'] for k in keys),3)
        cues=[];observations=[]
        for moment in ((analysis or {}).get('scene_observations') or (analysis or {}).get('moments',[])):
            if not isinstance(moment,dict):continue
            try:
                if float(moment['start'])<shot['source_end'] and float(moment['end'])>shot['source_start']:
                    observations.append({('source_'+k if k in ('start','end') else k):moment[k] for k in ('start','end','event','role','visual_evidence','layout_intent','layout_evidence','preserve_context','comparison_id','comparison_phase','confidence') if k in moment})
            except (ValueError,KeyError,TypeError):pass
            for cue in moment.get('editing_cues') or []:
                try:
                    a,b=float(cue['start']),float(cue['end'])
                    if cue.get('kind')=='number':
                        numeric=number_quote(cue.get('quote',''))
                        match=grounded_quote(clip_speech,numeric,
                            shot['start']+a-shot['source_start'],shot['start']+b-shot['source_start'],tolerance=2.) if numeric else None
                        if match:
                            a=shot['source_start']+match[0]-shot['start']
                            b=shot['source_start']+match[1]-shot['start']
                    if not math.isfinite(a+b) or b<=a or b<=shot['source_start'] or a>=shot['source_end']:continue
                    a=max(a,shot['source_start']);b=min(b,shot['source_end'])
                    row=copy.deepcopy(cue);row['start']=shot['start']+a-shot['source_start'];row['end']=shot['start']+b-shot['source_start']
                    cues.append(row)
                except (ValueError,KeyError,TypeError):continue
        # Narration can span a picture cut. Assign each word once by its midpoint
        # while retaining its real audio timestamps for exact emphasis alignment.
        speech=[dict(start=c['start'],end=c['end'],text=c['text'],aligned=c['aligned']) for c in plan['captions']
                if shot['start']<=(c['start']+c['end'])/2<shot['end']]
        caption_regions=[]
        if shot['renderer']=='TRACK':
            for face in shot['faces']+shot['protected_regions']:
                views=[((face['x']-k['x'])/k['width'],(face['y']-k['y'])/k['height'],
                    (face['x']+face['width']-k['x'])/k['width'],(face['y']+face['height']-k['y'])/k['height']) for k in keys]
                if views:
                    left=max(0,min(v[0] for v in views));top=max(0,min(v[1] for v in views))
                    right=min(1,max(v[2] for v in views));bottom=min(1,max(v[3] for v in views))
                    if right>left and bottom>top:caption_regions.append(dict(start=shot['start'],end=shot['end'],x=left,y=top,width=right-left,height=bottom-top))
        output.append(Scene(id=f'scene-{i}',start=shot['start'],end=shot['end'],source_start=shot['source_start'],
            source_end=shot['source_end'],shot_type=shot['renderer'],visible_subjects=shot['faces'],
            important_regions=shot['protected_regions'],speech=speech[:500],motion=motion,
            transition='edit_join' if i and plan['shots'][i-1]['segment_index']!=shot['segment_index'] else 'shot_boundary' if i else 'unknown',
            confidence=max([float(c['confidence']) for c in cues if type(c.get('confidence')) in (int,float) and math.isfinite(c['confidence']) and 0<=c['confidence']<=1]+[0.]),
            observations=observations[:32],caption_regions=caption_regions[:32],safe_zoom=next((scale for scale in (1.18,1.14,1.10,1.07,1.04) if safe_zoom(shot,scale)),1),
            cues=cues[:64]).model_dump(mode='json'))
    return output


def safe_zoom(shot,scale):
    """No extra zoom unless all retained face/object boxes survive every keyframe."""
    if shot['renderer']!='TRACK' or not shot['keyframes'] or not shot['faces']:return False
    for key in shot['keyframes']:
        pad_x=key['width']*(1-1/scale)/2;pad_y=key['height']*(1-1/scale)/2
        for face in shot['faces']+shot['protected_regions']:
            if (face['x']<key['x']+pad_x or face['y']<key['y']+pad_y or
                face['x']+face['width']>key['x']+key['width']-pad_x or
                face['y']+face['height']>key['y']+key['height']-pad_y):return False
    return True


def aligned_quote(speech,quote,start,end,tolerance=1.):
    matched=grounded_quote(speech,quote,start,end,tolerance)
    return matched[:2] if matched else None


def quote_tokens(value):
    return re.findall(r"\w+(?:'\w+)*",str(value).casefold().replace('’',"'"))


def grounded_quote(speech,quote,start,end,tolerance=1.):
    """Exact retained words, tolerating punctuation and picture cuts, not paraphrase."""
    if not isinstance(quote,str):return None
    wanted=quote_tokens(quote)
    if not wanted:return None
    tokens=[(word,row['start'],row['end']) for row in speech for word in quote_tokens(row['text'])]
    retained=[r[0] for r in tokens];choices=[]
    def candidate(i,length,exact):
        rows=tokens[i:i+length]
        if not rows:return
        a,b=rows[0][1],rows[-1][2]
        if a>=end+tolerance or b<=start-tolerance:return
        distance=abs((a+b)-(start+end))
        choices.append(((exact,length,-distance),(a,b,' '.join(r[0] for r in rows))))
    for i in range(len(tokens)-len(wanted)+1):
        if retained[i:i+len(wanted)]==wanted:candidate(i,len(wanted),True)
    if not choices:
        # Provider quotes can contain an extra word not present in ASR. Only
        # retain a substantial contiguous exact fragment, never fuzzy words.
        for block in SequenceMatcher(None,wanted,retained,autojunk=False).get_matching_blocks():
            phrase=wanted[block.a:block.a+block.size]
            if block.size>=3 and (block.size>=6 or block.size>=len(wanted)*.35) and any(len(w)>3 for w in phrase):
                candidate(block.b,block.size,False)
    return max(choices,key=lambda item:item[0])[1] if choices else None


NUMBER_WORDS=set('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion trillion'.split())


def number_quote(quote):
    tokens=quote_tokens(quote)
    for i,word in enumerate(tokens):
        if any(c.isdigit() for c in word) or word in NUMBER_WORDS:
            end=i+1
            while end<len(tokens) and (tokens[end] in NUMBER_WORDS|{'and','point','dollars','dollar','percent'} or any(c.isdigit() for c in tokens[end])):end+=1
            return ' '.join(tokens[i:end]).strip()
    return ''


def generate(plan,analysis=None,settings=None):
    value=defaults() if settings is None else copy.deepcopy(settings)
    old_scenes={s['id']:s for s in value.get('scenes',[])}
    value['scenes']=scene_records(plan,analysis);value['skipped']=[]
    value['source_segments']=[dict(start=s['source_start'],end=s['source_end']) for s in plan.get('segments',[])]
    # Manual records are never replaced by regeneration.
    value['effects']=[e for e in value.get('effects',[]) if e.get('origin')=='manual' and
                      any(s['id']==e.get('source_scene') and s['start']<=e['start']<e['end']<=s['end'] and
                          (not old_scenes or all(s[k]==old_scenes.get(s['id'],{}).get(k) for k in ('start','end','source_start','source_end')))
                          for s in value['scenes'])]
    import editing_skills
    value['skill_plan']=editing_skills.prepare(plan,value['scenes'])
    cfg=AutoEdit.model_validate(value).model_dump(mode='json');limits=cfg['limits']
    selection=(plan.get('evidence') or {}).get('category_selection') or (analysis or {}).get('category_selection')
    category_policy=None
    if selection:
        from category_intelligence import editing_policy
        category_policy=editing_policy(selection['primary_category'],selection.get('subcategory','auto'))
        limits['max_zoom']=min(limits['max_zoom'],category_policy['max_zoom'])
    count=0;last_camera=-100.
    def skip(kind,scene,reason):
        if len(cfg['skipped'])<100:cfg['skipped'].append(dict(type=kind,source_scene=scene['id'],reason=reason))
    def add(kind,scene,a,b,reason,confidence,**params):
        nonlocal count,last_camera
        if category_policy and kind not in category_policy['allowed_effects']:
            skip(kind,scene,'Category policy preserves context/pacing; no effect is a valid decision.');return
        if count>=limits['max_effects']:return
        b=min(b,scene['end'],a+limits['max_duration'])
        if b-a<limits['min_duration']:return
        if kind in CAMERA and a-last_camera<limits['camera_gap']:return
        if any(e['enabled'] and e['category']==category(kind) and e['start']<b and e['end']>a for e in cfg['effects']):return
        token=hashlib.sha256(f'{scene["id"]}:{a:.4f}:{kind}'.encode()).hexdigest()[:16]
        row=Effect(id='ai-'+token,type=kind,category=category(kind),source_scene=scene['id'],
            start=a,end=b,duration=b-a,reason=reason[:600],confidence=confidence,parameters=Parameters(**params)).model_dump(mode='json')
        cfg['effects'].append(row);count+=1
        if kind in CAMERA:last_camera=a
    for scene,shot in zip(cfg['scenes'],plan['shots']):
        # Story category reduces effects, but never creates an event by itself.
        serious=plan.get('kind')=='emotional' or any(c.get('kind')=='serious' and not c.get('local_skill') for c in scene['cues'])
        for cue in sorted(scene['cues'],key=lambda c:c.get('start',0)):
            kind=cue.get('kind');evidence=cue.get('evidence','');confidence=cue.get('confidence',0)
            if not isinstance(evidence,str) or not evidence.strip() or type(confidence) not in (float,int) or not math.isfinite(confidence) or not limits['motion_sensitivity']<=confidence<=1:continue
            a,b=cue['start'],cue['end'];quote=cue.get('quote','')
            if kind=='number':quote=number_quote(quote)
            if kind=='number' and not quote:
                skip('number_highlight',scene,'The proposed number cue contains no retained numeric token.');continue
            # Speech is continuous even when the picture cuts. Match on the
            # complete retained clip, then constrain the effect to this shot.
            matched=grounded_quote([dict(text=c['text'],start=c['start'],end=c['end']) for c in plan['captions']],quote,a,b)
            if matched and not (matched[0]<scene['end'] and matched[1]>scene['start']):matched=None
            grounded=matched is not None
            local_serious=any(c.get('kind')=='serious' and c.get('local_skill') and c['start']<b and c['end']>a for c in scene['cues'])
            if serious or local_serious:
                skip(kind or 'unknown',scene,'Serious dialogue: preserve pauses and natural camera timing.');continue
            target={'explanation':'smooth_zoom_in','reveal':'smooth_zoom_out','surprise':'fast_punch_in','reaction':'snap_zoom','action':'subject_tracking'}.get(kind)
            if target and cfg['zoom'] and (target!='subject_tracking' or cfg['tracking']):
                zoom=1+(limits['max_zoom']-1)*(.6 if kind=='explanation' else 1)
                if safe_zoom(shot,zoom):add(target,scene,a,b,evidence,confidence,zoom=zoom)
                else:skip(target,scene,'Extra magnification would discard a retained subject/object or shared scene.')
            if cfg['text'] and grounded and kind in ('surprise','explanation','number'):
                qa,qb,retained_quote=matched
                qa=max(scene['start'],qa);qb=min(scene['end'],max(qb,qa+limits['min_duration']))
                add('number_highlight' if kind=='number' else 'keyword_highlight',scene,qa,qb,evidence,confidence,quote=retained_quote)
            elif cfg['text'] and quote and kind in ('surprise','explanation','number'):
                skip('text_emphasis',scene,'The proposed quote did not match retained speech near this cue inside the shot.')
            quiet=any(lo<=a and hi>=b for lo,hi in scene['motion'].get('quiet_intervals',[]))
            if kind=='pause' and quiet and cfg['transitions'] and cfg['profile']=='cinematic' and not any(c['start']<b and c['end']>a for c in scene['speech']) and a<=scene['start']+.05:
                add('fade',scene,a,min(b,a+.6),evidence,confidence,direction='in')
    result=normalize(cfg,plan['duration'])
    editing_skills.reconcile(result['skill_plan'],active(result))
    if __import__('os').getenv('OPENSHORTS_LEARNING_DISABLED')=='1':return result
    try:
        from learning.integration import apply
        result=apply(plan,result)
        editing_skills.reconcile(result['skill_plan'],active(result))
        return result
    except Exception:return result


def active(settings):
    if not settings or not settings.get('enabled',True):return []
    result=[];last={};scenes={s['id']:s for s in settings['scenes']}
    limits=settings['limits']
    if limits['max_effects']==0:return []
    for e in sorted(settings['effects'],key=lambda e:(e['start'],e['id'])):
        if not e['enabled'] or e['intensity']<=0 or e['type'] in UNSUPPORTED|DELEGATED:continue
        toggle='tracking' if e['type'] in ('face_tracking','subject_tracking','smart_camera_pan') else 'zoom' if e['category']=='camera' else 'transitions' if e['category']=='transition' else 'text' if e['category']=='text' else 'audio' if e['category']=='audio' else 'zoom'
        if not settings[toggle]:continue
        if e['type'] in CAMERA|{'controlled_shake'} and (e['parameters']['zoom']>scenes[e['source_scene']]['safe_zoom'] or e['anchor']!=[.5,.5]):continue
        if e['duration']<limits['min_duration'] or e['duration']>limits['max_duration']:continue
        group='visual' if e['type'] in CAMERA|VIDEO else e['category']
        if e['start']<last.get(group,-1):continue
        result.append(e);last[group]=e['end']+(limits['camera_gap'] if e['type'] in CAMERA else 0)
        if len(result)>=limits['max_effects']:break
    return result


def _ease_expr(t,kind):
    if kind=='linear':return t
    if kind=='ease_in':return f'pow({t},2)'
    if kind=='ease_out':return f'(1-pow(1-({t}),2))'
    if kind=='ease_in_out':return f'if(lt({t},0.5),2*pow({t},2),1-pow(-2*({t})+2,2)/2)'
    if kind=='overshoot':return f'(1+2.2*pow(({t})-1,3)+1.2*pow(({t})-1,2))'
    return f'(({t})*({t})*(3-2*({t})))'


def video_filter(settings,size,fps):
    """Bounded zoompan uses seconds, preserving exactly one frame per input frame."""
    selected=active(settings);camera=[e for e in selected if e['type'] in CAMERA|{'controlled_shake'}]
    filters=[]
    if camera:
        z='1';x='iw/2-iw/zoom/2';y='ih/2-ih/zoom/2'
        for e in reversed(camera):
            a,b=e['start'],e['end'];d=b-a;t=f'min(1,max(0,(in_time-{a:.6f})/{d:.6f}))'
            curve=_ease_expr(t,e['easing']);kind=e['type']
            # Return to the base crop at both endpoints; no snap-back cut afterwards.
            envelope=f'pow(sin(PI*({curve})),2)'
            if kind in ('smooth_zoom_in','smooth_zoom_out','fast_punch_in','snap_zoom'):
                rise,release={'smooth_zoom_in':(.65,.35),'smooth_zoom_out':(.15,.85),
                    'fast_punch_in':(.1,.3),'snap_zoom':(.035,.25)}[kind]
                up=_ease_expr(f'min(1,max(0,(in_time-{a:.6f})/{d*rise:.6f}))',e['easing'])
                down=_ease_expr(f'min(1,max(0,(in_time-{b-d*release:.6f})/{d*release:.6f}))',e['easing'])
                envelope=f'(({up})*(1-({down})))'
            if kind=='zoom_bounce':envelope=f'min(1,max(0,sin(PI*({t}))*(1+0.06*sin(6*PI*({t})))))'
            zoom=min(e['parameters']['zoom'],settings['limits']['max_zoom'])
            peak=1+(zoom-1)*e['intensity']
            gate=f'between(in_time,{a:.6f},{b:.6f})'
            if kind=='controlled_shake':
                amount=min(e['parameters']['amount'],settings['limits']['max_shake'])*e['intensity']
                peak=max(peak,1+amount*4)
                x=f'if({gate},(iw-iw/zoom)/2+iw*{amount}*sin(31*in_time)*({envelope}),{x})'
                y=f'if({gate},(ih-ih/zoom)/2+ih*{amount}*sin(23*in_time)*({envelope}),{y})'
            z=f'if({gate},1+{peak-1:.8f}*({envelope}),{z})'
        filters.append(f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,{x}))':y='max(0,min(ih-ih/zoom,{y}))':d=1:s={size[0]}x{size[1]}:fps={fps:.8f}")
    for e in selected:
        if e['type']=='motion_blur':filters.append(f"tmix=frames=2:weights='1 1':enable='between(t,{e['start']:.6f},{e['end']:.6f})'")
        if e['type']=='fade':filters.append(f"fade=t={e['parameters']['direction']}:st={e['start']:.6f}:d={e['duration']:.6f}:enable='between(t,{e['start']:.6f},{e['end']:.6f})'")
    return ','.join(filters)


def render(input_path,output_path,settings,size,fps,runner,encoder):
    """Single optional stage shared by generation, editor preview and export."""
    filters=video_filter(settings,size,fps)
    audio=any(e['type']=='dialogue_normalization' for e in active(settings))
    if not filters and not audio:return str(input_path)
    command=['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_threads','1','-i',str(input_path)]
    if filters:command+=['-vf',filters]
    command+=['-map','0:v:0','-map','0:a?',*(encoder if filters else ['-c:v','copy'])]
    command+=['-af','loudnorm=I=-16:TP=-2:LRA=11','-c:a','aac'] if audio else ['-c:a','copy']
    try:
        runner([*command,'-movflags','+faststart',str(output_path)])
        import export_quality as quality
        before=quality.probe(input_path);after=quality.probe(output_path)
        video,audio=quality.streams(after);_,source_audio=quality.streams(before)
        duration=quality.number(before.get('format',{}).get('duration'))
        output_duration=quality.number(after.get('format',{}).get('duration'))
        if (not video or (video['width'],video['height'])!=tuple(size) or
            bool(audio)!=bool(source_audio) or duration is None or output_duration is None or
            abs(duration-output_duration)>max(.15,2/fps)):
            raise ValueError('Optional effect output changed dimensions, audio availability or timing.')
    except (subprocess.CalledProcessError,ValueError):
        # One correction only: discard the optional effect pass, retain base media.
        Path(output_path).unlink(missing_ok=True)
        from story_director import atomic_json
        atomic_json(str(input_path)+'.effects-skipped.json',{'reason':'Effect filter failed; retained the validated base composition.','effect_ids':[e['id'] for e in active(settings)]})
        return str(input_path)
    return str(output_path)


def emphasize(transcript,settings):
    result=copy.deepcopy(transcript)
    retained=[(token,word) for segment in result.get('segments',[]) for word in segment.get('words',[])
              for token in quote_tokens(word.get('word',''))]
    for effect in active(settings):
        if effect['type'] not in ('keyword_highlight','number_highlight'):continue
        tokens=quote_tokens(effect['parameters']['quote'])
        if not tokens:continue
        for i in range(len(retained)-len(tokens)+1):
            chunk=retained[i:i+len(tokens)]
            if [t for t,_ in chunk]!=tokens:continue
            for _,word in chunk:
                if word['start']<effect['end'] and word['end']>effect['start']:word['emphasis']=True
    return result


def caption_regions(faces,settings):
    """Reserve the whole face/object envelope over additional camera movement."""
    result=copy.deepcopy(faces)
    cameras=[e for e in active(settings) if e['type'] in CAMERA|{'controlled_shake'}]
    for region in result:
        zoom=max([1.]+[1+(min(e['parameters']['zoom'],settings['limits']['max_zoom'])-1)*e['intensity']
            for e in cameras if e['start']<region['end'] and e['end']>region['start']])
        left=region['x'];top=region['y'];right=left+region['width'];bottom=top+region['height']
        x=max(0,min(left,.5+(left-.5)*zoom));y=max(0,min(top,.5+(top-.5)*zoom))
        region.update(x=x,y=y,width=min(1,max(right,.5+(right-.5)*zoom))-x,
                      height=min(1,max(bottom,.5+(bottom-.5)*zoom))-y)
    return result


def remap_plan(plan,segments):
    """Map retained observations through manual trim/reorder without decoding."""
    result=copy.deepcopy(plan);shots=[];captions=[];offset=0.
    for segment in segments:
        for shot in plan['shots']:
            a=max(segment['start'],shot['source_start']);b=min(segment['end'],shot['source_end'])
            if b<=a:continue
            row=copy.deepcopy(shot);delta=a-shot['source_start']
            row.update(start=offset+a-segment['start'],end=offset+b-segment['start'],source_start=a,source_end=b)
            if row['keyframes']:
                # Include held endpoints so a trim never loses its current crop.
                keys=row['keyframes'];first=max((k for k in keys if k['time']<=delta),key=lambda k:k['time'],default=keys[0])
                row['keyframes']=[dict(first,time=0.)]+[dict(k,time=k['time']-delta) for k in keys if delta<k['time']<delta+b-a]
            shots.append(row)
        for c in plan['captions']:
            if segment['start']<=c['source_start']<c['source_end']<=segment['end']:
                captions.append(dict(c,start=offset+c['source_start']-segment['start'],end=offset+c['source_end']-segment['start']))
        offset+=segment['end']-segment['start']
    result.update(shots=sorted(shots,key=lambda s:s['start']),captions=captions,duration=offset,
        segments=[dict(source_start=s['start'],source_end=s['end']) for s in segments])
    return result


def observations(plan):
    scenes=(plan.get('auto_edit') or {}).get('scenes',[])
    moments=[];seen=set()
    for scene in scenes:
        for row in scene.get('observations',[]):
            key=json.dumps(row,sort_keys=True)
            if key in seen:continue
            seen.add(key)
            moments.append({('start' if k=='source_start' else 'end' if k=='source_end' else k):v for k,v in row.items()})
        moments.append({'editing_cues':[dict(c,start=scene['source_start']+c['start']-scene['start'],
            end=scene['source_start']+c['end']-scene['start']) for c in scene['cues']]})
    return {'moments':moments}


def retime(value,segments):
    """Keep effect/source correspondence when the manual editor trims or reorders."""
    value=copy.deepcopy(value)
    if value.get('source_segments',[])==segments or not value.get('scenes'):return value
    scenes=[];effects=[];offset=0.
    for index,segment in enumerate(segments):
        for scene in value['scenes']:
            a=max(segment['start'],scene['source_start']);b=min(segment['end'],scene['source_end'])
            if b<=a:continue
            new=copy.deepcopy(scene);sid=f'{index}-{scene["id"]}'[-64:]
            new.update(id=sid,start=offset+a-segment['start'],end=offset+b-segment['start'],source_start=a,source_end=b,cues=[],speech=[])
            new['caption_regions']=[dict(r,start=new['start'],end=new['end']) for r in new.get('caption_regions',[])]
            scenes.append(new)
            for effect in value['effects']:
                if effect['source_scene']!=scene['id']:continue
                source_a=scene['source_start']+effect['start']-scene['start'];source_b=source_a+effect['duration']
                # Do not cut an animation in half: skip a partially trimmed effect.
                if source_a<a-.001 or source_b>b+.001:continue
                e=copy.deepcopy(effect);ea=new['start']+source_a-a
                e.update(id=f'{index}-{e["id"]}'[-80:],source_scene=sid,start=ea,end=ea+e['duration'])
                effects.append(e)
        offset+=segment['end']-segment['start']
    value.update(scenes=scenes,effects=effects,source_segments=copy.deepcopy(segments))
    # Trim/reorder invalidates narrative mappings; regeneration rebuilds them.
    value['skill_plan']=None
    return value
