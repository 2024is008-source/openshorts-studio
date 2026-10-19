"""Local opportunity detection for the existing Editing Director (no API calls).

A speech claim is never promoted to visual action. Skills propose existing
adapters; auto_edit owns eligibility, conflicts, crop bounds and rendering.
"""
from pathlib import Path
import hashlib
import json
import math
import re

VERSION = 1
REGISTRY_PATH = Path(__file__).parent / 'assets/editing_pattern_library.json'
TYPES = {'HOOK','CHALLENGE_PREMISE','STAKES','IMPORTANT_NUMBER','ATTEMPT_START',
    'ATTEMPT_PROGRESS','FAILURE','SUCCESS','UNEXPECTED_REACTION','COMEDIC_REACTION',
    'EMOTIONAL_MOMENT','BEFORE_AFTER_COMPARISON','MILESTONE','TRANSFORMATION_REVEAL',
    'SURPRISE','SCENE_CHANGE','NATURAL_PAUSE','STORY_PAYOFF','ENDING'}
# These are linguistic situations, not verified events. Retain original wording.
RULES = {
 'CHALLENGE_PREMISE':r'\b(challenge|contestants?|goal|if .{1,80}(?:win|lose|complete))\b',
 'STAKES':r'\b(win|prize|risk|nothing|dollars?|consequence)\b|\$',
 'ATTEMPT_START':r'\b(ready to start|let.s (?:start|try|do it)|first attempt)\b',
 'ATTEMPT_PROGRESS':r'\b(progress|keep going|working|consistent|steps today)\b',
 'FAILURE':r'\b(failed|couldn.t|hard pass|give up)\b',
 'SUCCESS':r'\b(we did it|congratulations|succeeded|completed)\b',
 'EMOTIONAL_MOMENT':r'\b(proud|love|special|afraid|scared|miss you|crying)\b',
 'MILESTONE':r'\b(day\s+\d+|first month|entire size|milestone|halfway)\b',
 'STORY_PAYOFF':r'\b(result|collectively lost|finally|we did it)\b',
 'SURPRISE':r'\b(oh my god|what the heck|unexpected|surprise)\b',
}
NUMBER = re.compile(r'(?<!\w)(?:[$£€]?\d[\d,.]*(?:\s*(?:pounds?|lbs|steps?|dollars?|percent|%|XL))?|(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred|thousand|million)(?:[ -]+(?:and|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|dollars?|pounds?))*)(?!\w)',re.I)


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))


def validate(record,duration):
    if record is None:return
    if record.get('version')!=1 or record.get('registry_version')!=1:raise ValueError('Unsupported skill-plan version')
    if len(json.dumps(record,allow_nan=False))>524288:raise ValueError('Skill plan exceeds evidence budget')
    opportunities=record.get('opportunities',[]);decisions=record.get('decisions',[])
    if len(opportunities)>256 or len(decisions)>128:raise ValueError('Skill plan exceeds count budget')
    identities=set();skills={s['id'] for s in registry()['skills']}
    for row in opportunities+decisions:
        if not all(type(row.get(k)) in (int,float) and math.isfinite(row[k]) for k in ('start','end','source_start','source_end')):raise ValueError('Invalid skill timestamps')
        if not 0<=row['start']<row['end']<=duration+.001 or not 0<=row['source_start']<row['source_end']:raise ValueError('Skill range exceeds retained timeline')
    for row in opportunities:
        if row['type'] not in TYPES or row['id'] in identities:raise ValueError('Invalid opportunity identity/type')
        identities.add(row['id'])
    for row in decisions:
        if row['skill'] not in skills or row['opportunity'] not in identities:raise ValueError('Skill decision has no evidence')


def utterances(captions):
    rows=[];group=[]
    for word in sorted(captions,key=lambda c:c['start']):
        if not word.get('aligned') or not isinstance(word.get('text'),str) or not all(k in word for k in ('source_start','source_end')):continue
        if group and (word['start']-group[-1]['end']>.65 or word.get('segment_index')!=group[-1].get('segment_index') or word['source_start']<group[-1]['source_start'] or word['start']-group[0]['start']>10):
            rows.append(group);group=[]
        group.append(word)
        if re.search(r'[.!?]$',word['text'].strip()):rows.append(group);group=[]
    if group:rows.append(group)
    return rows


def detect(plan, scenes):
    """Return bounded opportunities in both source and assembled output clocks."""
    result=[];seen=set();duration=plan['duration']
    category=(plan.get('evidence',{}).get('category_selection') or {}).get('primary_category',plan.get('kind','general'))
    def add(kind,a,b,sa,sb,evidence,channel,confidence,missing=()):
        if kind not in TYPES or len(result)>=256:return
        if not all(type(v) in (float,int) and math.isfinite(v) for v in (a,b,sa,sb,confidence)):return
        if not 0<=a<b<=duration+.001 or not 0<=sa<sb or not 0<=confidence<=1:return
        key=(kind,round(a,4),round(b,4),channel)
        if key in seen:return
        seen.add(key)
        result.append(dict(id=hashlib.sha256(repr(key).encode()).hexdigest()[:16],type=kind,
            start=a,end=b,source_start=sa,source_end=sb,source_ref=Path(plan.get('source_ref','source.mp4')).name,
            category=category,evidence=str(evidence)[:500],evidence_source=channel,confidence=confidence,
            certainty='observed' if channel in ('retained_visual_cue','measured_audio','timeline') else 'inferred',
            importance=3 if kind in ('HOOK','STAKES','STORY_PAYOFF','EMOTIONAL_MOMENT') else 2,
            missing_evidence=list(missing),supported_skills=[]))
    for group in utterances(plan.get('captions',[])):
        quote=' '.join(w['text'].strip() for w in group);a=group[0]['start'];b=group[-1]['end'];sa=group[0]['source_start'];sb=group[-1]['source_end']
        for kind,pattern in RULES.items():
            if re.search(pattern,quote,re.I):add(kind,a,b,sa,sb,quote,'aligned_transcript',.8,('visual_event_not_verified',))
        if a<=3 and re.search(RULES['CHALLENGE_PREMISE']+'|'+RULES['STAKES'],quote,re.I):
            add('HOOK',a,b,sa,sb,quote,'aligned_transcript',.8,('visual_event_not_verified',))
        # Each match maps to exact retained word timestamps, not a whole sentence.
        text='';spans=[]
        for word in group:
            text+=(' ' if text else '');start=len(text);text+=word['text'].strip();spans.append((start,len(text),word))
        for match in NUMBER.finditer(text):
            words=[w for lo,hi,w in spans if lo<match.end() and hi>match.start()]
            if words:add('IMPORTANT_NUMBER',words[0]['start'],words[-1]['end'],words[0]['source_start'],words[-1]['source_end'],
                ' '.join(w['text'].strip() for w in words),'aligned_transcript',.85,('ASR_value_requires_review_if_uncertain',))
    comparisons={}
    for index,scene in enumerate(scenes):
        a,b,sa,sb=(scene[k] for k in ('start','end','source_start','source_end'))
        if index:add('SCENE_CHANGE',a,min(b,a+.1),sa,min(sb,sa+.1),'Retained shot boundary','timeline',1.)
        for lo,hi in scene.get('motion',{}).get('quiet_intervals',[]):
            if a<=lo<hi<=b:add('NATURAL_PAUSE',lo,hi,sa+lo-a,sa+hi-a,'Measured quiet interval; not proof of unwanted silence','measured_audio',.9)
        for cue in scene.get('cues',[]):
            # These cues were produced by the visual-analysis path, never local ASR.
            kind={'reaction':'UNEXPECTED_REACTION','action':'ATTEMPT_PROGRESS','reveal':'TRANSFORMATION_REVEAL','surprise':'SURPRISE','serious':'EMOTIONAL_MOMENT'}.get(cue.get('kind'))
            lo,hi=cue.get('start'),cue.get('end');conf=cue.get('confidence',0)
            if kind and isinstance(cue.get('evidence'),str) and cue['evidence'].strip() and type(lo) in (int,float) and type(hi) in (int,float) and type(conf) in (int,float) and conf>=.8:
                lo=max(a,lo);hi=min(b,hi)
                # A generic reveal does not establish a physical transformation.
                if kind=='TRANSFORMATION_REVEAL':kind='STORY_PAYOFF'
                add(kind,lo,hi,sa+lo-a,sa+hi-a,cue['evidence'],'retained_visual_cue',conf)
                if cue.get('kind')=='reaction' and plan.get('kind')=='comedy':
                    add('COMEDIC_REACTION',lo,hi,sa+lo-a,sa+hi-a,cue['evidence'],'retained_visual_cue',conf,('comic_intent_is_model_interpretation',))
        for observation in scene.get('observations',[]):
            identity=observation.get('comparison_id');phase=observation.get('comparison_phase')
            conf=observation.get('confidence',0)
            if not isinstance(identity,str) or not identity or phase not in ('before','after') or type(conf) not in (int,float) or not .8<=conf<=1:continue
            if not observation.get('event'):continue
            lo=max(sa,observation.get('source_start',sa));hi=min(sb,observation.get('source_end',sb))
            if hi<=lo:continue
            comparisons.setdefault(identity,{}).setdefault(phase,(a+lo-sa,a+hi-sa,lo,hi,observation['event'],conf))
    for pair in comparisons.values():
        if set(pair)!= {'before','after'}:continue
        before,after=pair['before'],pair['after']
        if before[1]>after[0] or before[3]>after[2]:continue
        evidence=f'Before: {before[4]}; After: {after[4]}'
        add('BEFORE_AFTER_COMPARISON',before[0],after[1],before[2],after[3],evidence,'retained_visual_cue',min(before[5],after[5]),('No synthesized earlier-body image or measurement',))
        add('TRANSFORMATION_REVEAL',after[0],after[1],after[2],after[3],after[4],'retained_visual_cue',after[5])
    if scenes:
        s=scenes[-1];a=max(s['start'],duration-1.)
        add('ENDING',a,duration,s['source_start']+a-s['start'],s['source_end'],'End of selected source; semantic closure unknown','timeline',1.,('semantic_completion_unknown',))
    return sorted(result,key=lambda o:(o['start'],-o['importance'],o['type']))


def prepare(plan,scenes):
    """Explainable recommendations and existing-renderer cues, not a second EDL."""
    lib=registry();opportunities=detect(plan,scenes);decisions=[];cues=[]
    selected=(plan.get('evidence',{}).get('category_selection') or {}).get('primary_category',plan.get('kind','general'))
    eligible=selected=='challenge' or (selected not in ('podcast','sports_highlights') and plan.get('kind') in ('challenge','emotional','comedy'))
    for opportunity in opportunities:
        for skill in lib['skills']:
            if opportunity['type'] not in skill['triggers']:continue
            if not eligible:continue
            if skill['visual_required'] and opportunity['evidence_source']!='retained_visual_cue':continue
            opportunity['supported_skills'].append(skill['id'])
            candidate=None
            if skill['id']=='important_number':candidate='number'
            elif skill['id']=='reaction' and opportunity['evidence_source']=='retained_visual_cue':candidate='reaction'
            elif skill['id']=='reveal' and opportunity['evidence_source']=='retained_visual_cue':candidate='reveal'
            elif skill['id']=='emotional':candidate='serious'
            if candidate:
                cues.append(dict(kind=candidate,start=opportunity['start'],end=opportunity['end'],
                    evidence=f"Skill {skill['id']}: {opportunity['evidence_source']}; preserve source meaning.",
                    quote=opportunity['evidence'] if candidate=='number' else '',confidence=opportunity['confidence'],local_skill=True))
            decisions.append(dict(skill=skill['id'],version=1,opportunity=opportunity['id'],
                start=opportunity['start'],end=opportunity['end'],source_start=opportunity['source_start'],source_end=opportunity['source_end'],
                source_ref=opportunity['source_ref'],candidate_adapter=skill['adapter'],effect_ids=[],status='preserve_source',
                reason='Retain existing source order, layout and timing; optional effects still require renderer validation.',
                conflicts=skill['conflicts'],evidence_source=opportunity['evidence_source']))
            if len(decisions)>=128:break
        if len(decisions)>=128:break
    # Suppress decorative camera cues during locally grounded emotional speech.
    for scene in scenes:
        for cue in cues:
            lo=max(scene['start'],cue['start']);hi=min(scene['end'],cue['end'])
            if hi>lo and not any(c.get('kind')==cue['kind'] and c.get('start',0)<hi and c.get('end',0)>lo for c in scene['cues']):
                scene['cues'].append(dict(cue,start=lo,end=hi))
    return dict(version=1,registry_version=lib['version'],opportunities=opportunities,decisions=decisions,
        limitations=['English lexical narrative candidates are interpretations, not physical-event verification.',
          'Paired visual before/after, comic intent and transformation require explicit verified evidence; no synthetic comparison is created.',
          'No source resequencing, speed change, new music or virality claim.'])


def reconcile(record, effects):
    if not record:return
    adapters={s['id']:s['adapter'] for s in registry()['skills']}
    for decision in record['decisions']:
        decision['status']='preserve_source'
        decision['reason']='Retain source timing and composition; no eligible optional effect was applied.'
        decision['effect_ids']=[e['id'] for e in effects if e.get('origin')=='ai' and e['type']==adapters[decision['skill']] and e['start']<decision['end'] and e['end']>decision['start']]
        decision['applied_parameters']=[dict(effect_id=e['id'],adapter=e['type'],start=e['start'],end=e['end'],
            intensity=e['intensity'],easing=e['easing'],parameters=e['parameters']) for e in effects if e['id'] in decision['effect_ids']]
        if decision['effect_ids']:
            decision['status']='applied';decision['reason']='Evidence matched retained source timing and passed existing crop, category and conflict gates.'


def protect_dialogue(units):
    """Conservative pacing veto, not a new cutter. Preserve emotional/decision gaps."""
    protected=[]
    for i,unit in enumerate(units):
        text=unit.get('text','')
        if re.search(RULES['EMOTIONAL_MOMENT']+'|'+RULES['STAKES'],text,re.I):
            a=units[max(0,i-1)]['start'];b=units[min(len(units)-1,i+1)]['end']
            protected.append((a,b))
    return protected
