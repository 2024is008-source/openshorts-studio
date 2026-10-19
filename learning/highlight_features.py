"""Prediction-time clip evidence. No dialogue, paths, labels or export outcomes."""
import hashlib
import math
from learning.features import finite

TASK='highlight-ranking'
VERSION=1
NUMERIC=('duration','speech_coverage','sentence_ending','leading_pause','trailing_pause','speech_gap',
 'hook','story','ending','visual','scene_changes','visual_activity','framing_feasibility','redundancy',
 'verified_visual','complete_story','payoff_evidence','transcript_relevance','event_verified','speaker_change')
SCALE={'duration':120,'leading_pause':10,'trailing_pause':10,'speech_gap':10,'scene_changes':20}
VECTOR_SIZE=len(NUMERIC)*2+32
CATEGORIES={'general':('default_clipping','auto'),'challenge':('challenge','auto'),
 'podcast':('podcast','auto'),'podcast-motivation':('podcast','motivation'),
 'podcast-education':('podcast','education'),'podcast-comedy':('podcast','comedy'),
 'sports_highlights':('sports_highlights','auto'),'cricket':('sports_highlights','cricket'),'football':('sports_highlights','football')}

def category(value,subtype='auto'):
    from category_intelligence import resolve
    try:cat,sub=resolve(value,subtype)
    except (ValueError,TypeError):return 'default_clipping','auto'
    return ('default_clipping' if cat=='general' else cat),sub


def extract(clip,pool=(),kind='general'):
    import clip_ranking
    report=clip.get('selection_report') or {};evidence=report.get('evidence') or {}
    components=report.get('components') or {};story=clip.get('story_report') or {}
    visual=clip.get('verification_status')=='model_observed' and bool(clip.get('visual_evidence'))
    # Never infer an event from audio peaks, titles or unverified Gemini suggestions.
    event=clip.get('event_verified') if visual and type(clip.get('event_verified')) is bool else None
    def proportion(name):
        v=finite(components.get(name));return max(0,min(1,v/100)) if v is not None else None
    signals=story.get('signals') or {};cuts=signals.get('scene_cuts')
    cat,sub=category(kind)
    references={e['id'] for e in story.get('evidence',[]) if isinstance(e,dict) and isinstance(e.get('id'),str) and e.get('channel') in ('transcript','visual','audio')}
    roles={b.get('role') for b in story.get('beats',[]) if isinstance(b,dict) and b.get('evidence_ids') and all(key in references for key in b['evidence_ids'])}
    desired='takeaway' if (cat,sub)==('podcast','motivation') else 'explanation' if (cat,sub)==('podcast','education') else 'punchline' if (cat,sub)==('podcast','comedy') else 'outcome' if cat=='challenge' else None
    category_payoff=1. if desired in roles else None
    from category_intelligence import candidate_features
    category_signals=candidate_features(clip,kind)
    signal={'takeaway':'takeaway','explanation':'explanation','punchline':'punchline'}.get(desired)
    if signal and category_signals.get(signal) is True:category_payoff=1.
    values=dict(duration=finite(clip.get('end',0)-clip.get('start',0)),
        speech_coverage=finite(evidence.get('speech_coverage')),
        sentence_ending=float(evidence['sentence_ending']) if type(evidence.get('sentence_ending')) is bool else None,
        leading_pause=finite(evidence.get('leading_pause')),trailing_pause=finite(evidence.get('trailing_pause')),
        speech_gap=finite(evidence.get('max_speech_gap')),hook=proportion('hook'),story=proportion('story'),
        ending=proportion('ending'),visual=proportion('visual') if visual else None,
        scene_changes=len(cuts) if isinstance(cuts,list) else None,
        visual_activity=finite(clip.get('measured_visual_activity')),
        framing_feasibility=finite(clip.get('framing_feasibility')),
        redundancy=max((clip_ranking.redundancy(clip,c)/100 for c in pool if c is not clip),default=None),
        verified_visual=float(visual) if 'verification_status' in clip else None,
        complete_story=float(clip['story_complete']) if type(clip.get('story_complete')) is bool else None,
        payoff_evidence=category_payoff if category_payoff is not None else finite(clip.get('payoff_evidence')) if visual or evidence.get('provider_ratings') else None,
        transcript_relevance=finite(clip.get('transcript_relevance')),
        event_verified=float(event) if event is not None else None,
        speaker_change=finite(clip.get('measured_speaker_change')))
    return validate(dict(task=TASK,version=VERSION,category=cat,subcategory=sub,values=values))

def validate(value):
    if not isinstance(value,dict) or set(value)!={'task','version','category','subcategory','values'} or value.get('task')!=TASK or value.get('version')!=VERSION:raise ValueError('Incompatible highlight feature schema')
    if set(value['values'])!=set(NUMERIC):raise ValueError('Unexpected highlight features')
    if value['category'] not in ('default_clipping','podcast','sports_highlights','challenge'):raise ValueError('Unknown highlight category')
    if value['subcategory'] not in ('auto','motivation','education','comedy','cricket','football','competition','survival','experiment','general'):raise ValueError('Unknown highlight subtype')
    if value['category']=='podcast' and value['subcategory'] not in ('auto','motivation','education','comedy') or value['category']=='sports_highlights' and value['subcategory'] not in ('auto','cricket','football') or value['category']=='challenge' and value['subcategory'] not in ('auto','competition','survival','experiment','general') or value['category']=='default_clipping' and value['subcategory']!='auto':raise ValueError('Incompatible highlight category/subtype')
    if any(v is not None and (finite(v) is None or abs(v)>1e6) for v in value['values'].values()):raise ValueError('Invalid highlight feature')
    return value

def vector(value):
    value=validate(value);out=[]
    for name in NUMERIC:
        v=value['values'][name];out.extend([max(-10,min(10,v/SCALE.get(name,1))) if v is not None else 0.,float(v is None)])
    hashed=[0.]*32
    for token in (value['category'],value['category']+':'+value['subcategory']):hashed[int(hashlib.sha256(token.encode()).hexdigest()[:8],16)%32]+=1
    return out+hashed
