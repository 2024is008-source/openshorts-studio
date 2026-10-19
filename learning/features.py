"""One deterministic, versioned input transformation for training and inference."""
import hashlib
import json
import math
from learning.policies import category

VERSION=1
NUMERIC=('scene_duration','face_count','subject_count','crop_motion','framing_confidence',
    'visual_complexity','speech_activity','relative_loudness','quiet_fraction','speaker_change',
    'speech_rate','caption_density','effect_spacing','candidate_duration','candidate_intensity',
    'safe_zoom','supported','cue_confidence')
SCALE={'scene_duration':60,'face_count':10,'subject_count':10,'crop_motion':1000,
    'speech_rate':5,'caption_density':5,'effect_spacing':10,'candidate_duration':6,'safe_zoom':2}
CATEGORICAL=('category','intent','beat','shot_type','boundary','effect_type')
VECTOR_SIZE=len(NUMERIC)*2+32


def finite(value):
    return float(value) if type(value) in (int,float) and math.isfinite(value) else None


def scene_contexts(settings):
    """The same effect-spacing context is used for observation and inference."""
    previous=None
    for scene in settings.get('scenes',[]):
        effects=[e for e in settings.get('effects',[]) if e['source_scene']==scene['id']]
        yield scene,effects,previous
        previous=max((e['end'] for e in effects),default=previous)


def extract(scene,candidate=None,kind='general',previous_end=None):
    import auto_edit
    candidate=candidate or {'type':'none'}
    duration=max(0.,float(scene['end'])-float(scene['start']))
    words=scene.get('speech') or [];motion=scene.get('motion') or {}
    cues=scene.get('cues') or [];observations=scene.get('observations') or []
    speech_seconds=sum(max(0,min(scene['end'],w['end'])-max(scene['start'],w['start'])) for w in words)
    quiet=sum(max(0,min(scene['end'],b)-max(scene['start'],a)) for a,b in motion.get('quiet_intervals',[]))
    first=observations[0] if observations else {}
    effect=candidate.get('type','none')
    values=dict(scene_duration=duration,face_count=len(scene.get('visible_subjects') or []),
        subject_count=len(scene.get('visible_subjects') or []) or None,
        crop_motion=finite(motion.get('camera_pan_pixels')),framing_confidence=finite(scene.get('framing_confidence')),
        visual_complexity=finite(scene.get('visual_complexity')),speech_activity=min(1,speech_seconds/duration) if duration and 'speech' in scene else None,
        relative_loudness=finite(motion.get('relative_audio_peak')),quiet_fraction=min(1,quiet/duration) if duration and 'quiet_intervals' in motion else None,
        speaker_change=finite(scene.get('speaker_change')),speech_rate=len(words)/duration if words and duration else None,
        caption_density=len(words)/duration if duration else None,
        effect_spacing=max(0,scene['start']-previous_end) if previous_end is not None else None,
        candidate_duration=finite(candidate.get('duration')),candidate_intensity=finite(candidate.get('intensity')),
        safe_zoom=finite(scene.get('safe_zoom')),supported=float(effect=='none' or effect in auto_edit.SUPPORTED),
        cue_confidence=max((finite(c.get('confidence')) or 0 for c in cues),default=None))
    return validate(dict(version=VERSION,values=values,category=category(kind),intent=first.get('layout_intent','unknown'),
        beat=first.get('role','unknown'),shot_type=scene.get('shot_type','unknown'),boundary=scene.get('transition','unknown'),
        effect_type=effect,cues=sorted({c.get('kind') for c in cues if isinstance(c.get('kind'),str)})))


def validate(value):
    if isinstance(value,dict) and value.get('task')=='highlight-ranking':
        from learning.highlight_features import validate as clip_validate
        return clip_validate(value)
    if not isinstance(value,dict) or value.get('version')!=VERSION:raise ValueError('Incompatible feature schema')
    if set(value)!=set(CATEGORICAL)|{'version','values','cues'}:raise ValueError('Unexpected feature field; labels are not input features')
    if set(value['values'])!=set(NUMERIC):raise ValueError('Invalid numeric features')
    for n,v in value['values'].items():
        if v is not None and (finite(v) is None or abs(v)>1e9):raise ValueError('Nonfinite feature')
    for n in CATEGORICAL:
        if not isinstance(value[n],str) or len(value[n])>80:raise ValueError('Invalid feature category')
    if not isinstance(value['cues'],list) or len(value['cues'])>16 or any(c not in ('explanation','reveal','surprise','reaction','serious','action','number','pause') for c in value['cues']):raise ValueError('Invalid cue feature')
    return value


def vector(value):
    if isinstance(value,dict) and value.get('task')=='highlight-ranking':
        from learning.highlight_features import vector as clip_vector
        return clip_vector(value)
    value=validate(value);out=[]
    for name in NUMERIC:
        v=value['values'][name];out.extend([max(-10,min(10,v/SCALE.get(name,1))) if v is not None else 0.,float(v is None)])
    hashed=[0.]*32
    for token in [*(f'{n}:{value[n]}' for n in CATEGORICAL),*(f'cue:{c}' for c in value['cues'])]:
        index=int(hashlib.sha256(token.encode()).hexdigest()[:8],16)%32;hashed[index]+=1
    return out+hashed


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
