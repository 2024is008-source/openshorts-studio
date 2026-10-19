"""Knowledge, provenance and explicit feedback. No automatic positive labels."""
import math
import time
from learning.database import Store
from learning import features as f
from learning.policies import policy

ACTIONS={'approve','reject','remove','replace','adjust_intensity','adjust_duration','adjust_timing',
    'caption_style','caption_text','quality','approve_none'}


def safe_effect(effect):
    # Text quotes and explanations can contain transcript content: retain only
    # operational parameters and short evidence types, never source dialogue.
    return {k:effect[k] for k in ('id','type','category','source_scene','start','end','duration','intensity','confidence','origin','enabled') if k in effect}|{
        'parameters':{k:v for k,v in effect.get('parameters',{}).items() if k!='quote'}}


def observe(plan,settings,store=None):
    store=store or Store()
    if not store.preferences()['collect']:return []
    group=f.digest(plan.get('source_identity') or plan.get('source_ref') or 'unknown-source')
    project=f.digest([group,plan.get('segments',[])]);identities=[]
    selection=(plan.get('evidence') or {}).get('category_selection') or {}
    kind=selection.get('primary_category',plan.get('kind'))
    subtype=selection.get('subcategory','auto')
    p=policy(kind,subtype)
    if selection:
        from category_intelligence import editing_policy
        p['category_editing_policy']=editing_policy(kind,subtype)
    with store.connect() as db:
        skill_plan=settings.get('skill_plan')
        if skill_plan:
            import editing_skills
            for definition in editing_skills.registry()['skills']:
                store.put('category_policies','reference-skill:'+definition['id']+':1',definition,
                    category='challenge',status='design-heuristic-not-training-label',db=db)
        store.put('category_policies',f'{p["category"]}:{subtype}:{p["version"]}',p,category=p['category'],status='active',db=db)
        for scene,effects,previous in f.scene_contexts(settings):
            identity=f.digest([project,scene['source_start'],scene['source_end'],f.VERSION])
            feature=f.extract(scene,kind=kind,previous_end=previous)
            db.execute('INSERT OR IGNORE INTO scene_features VALUES(?,?,?,?,?,?,?,?)',
                (identity,group,project,scene['id'],feature['category'],f.VERSION,__import__('json').dumps(feature,allow_nan=False),time.time()))
            candidates=[*effects,dict(id='none',type='none')]
            for candidate in candidates:
                cid=f.digest([identity,candidate.get('id'),safe_effect(candidate)])
                data=dict(features=f.extract(scene,candidate,kind,previous),effect=safe_effect(candidate),
                    baseline_score=candidate.get('confidence',0.5) if candidate['type']!='none' else (1. if not effects else .25),
                    policy_version=p['version'],feature_version=f.VERSION,category_contract=dict(version=1,category=p['category'],subcategory=subtype))
                store.put('effect_candidates',cid,data,scene=identity,category=p['category'],db=db)
                identities.append(dict(id=cid,scene=identity,effect=candidate['id']))
            origins={e.get('origin','ai') for e in effects}
            origin=next(iter(origins)) if len(origins)==1 else 'mixed' if origins else 'ai'
            store.put('editing_decisions',f.digest([identity,[safe_effect(e) for e in effects]]),
                dict(selected=[safe_effect(e) for e in effects],origin=origin,review='unreviewed',policy_version=1),scene=identity,category=p['category'],db=db)
            if skill_plan:
                # Keep operational provenance only: no source dialogue or paths.
                opportunities=[{k:o[k] for k in ('id','type','start','end','source_start','source_end','evidence_source','confidence','supported_skills')}
                    for o in skill_plan['opportunities'] if o['start']<scene['end'] and o['end']>scene['start']]
                decisions=[{k:d[k] for k in ('skill','version','opportunity','start','end','source_start','source_end','candidate_adapter','effect_ids','status','evidence_source')}
                    for d in skill_plan['decisions'] if d['start']<scene['end'] and d['end']>scene['start']]
                record=dict(task='reference-editing-skills',version=1,opportunities=opportunities,decisions=decisions,review='unreviewed',training_label=False)
                store.put('editing_decisions',f.digest([identity,record]),record,scene=identity,category=p['category'],db=db)
    return identities


def feedback(store,event,candidate_id,action,before=None,after=None,rating=None):
    if action not in ACTIONS or not isinstance(event,str) or not 8<=len(event)<=128:raise ValueError('Invalid explicit feedback action')
    if not store.preferences()['collect']:raise ValueError('Learning collection is disabled')
    rows=store.rows('effect_candidates','id=?',(candidate_id,))
    if not rows:raise ValueError('Unknown effect candidate; refresh learning status first')
    row=rows[0];candidate=row['data'];scene=row['scene_id']
    if action=='quality' and (type(rating) not in (int,float) or not math.isfinite(rating) or not 0<=rating<=5):raise ValueError('Quality rating must be 0–5')
    # Before/after input is operational metadata, never raw captions/transcripts.
    allowed={'type','start','end','duration','intensity','enabled','preset','text_hash','word_count'}
    def safe(value):
        value=value or {}
        if not isinstance(value,dict) or set(value)-allowed:raise ValueError('Unsupported correction fields')
        for k,v in value.items():
            if isinstance(v,str) and len(v)>80:raise ValueError('Oversized correction')
            if isinstance(v,(dict,list)):raise ValueError('Nested correction rejected')
        return value
    before=safe(before);after=safe(after)
    if action in ('approve','approve_none') and before!=after:raise ValueError('Refresh the changed candidate before approving it')
    states={'approve':'human-approved','approve_none':'human-approved','reject':'human-rejected',
        'remove':'human-rejected'}
    state=states.get(action,'human-modified')
    if action=='approve_none' and candidate['effect']['type']!='none':raise ValueError('Select no-effect candidate')
    if action=='approve' and candidate['effect']['type']=='none':raise ValueError('Use explicit no-effect approval')
    record=dict(action=action,before=before,after=after,rating=rating,provenance='explicit-human-action',candidate=candidate_id)
    # The event UUID is a transport receipt; identical undo/redo/autosave or
    # repeated button actions must not amplify training weight.
    event=f.digest(record)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        history=[dict(r) for r in db.execute('SELECT id,data FROM user_feedback WHERE scene_id=? ORDER BY created,id',(scene,))]
        prior=next((r for r in reversed(history) if __import__('json').loads(r['data']).get('candidate')==candidate_id and __import__('json').loads(r['data']).get('action') in ('approve','approve_none','reject','remove')),None)
        if action in ('approve','approve_none','reject','remove') and prior and __import__('json').loads(prior['data'])!=record:
            # A deliberate changed verdict supersedes an older review; repeated
            # identical clicks still collapse to the same receipt.
            event=f.digest([record,prior['id']])
        inserted=store.put('user_feedback',event,record,scene=scene,category=row['category'],status=state,db=db)
        if not inserted:return dict(status='duplicate',event=event)
        if action in ('approve','approve_none','reject','remove'):
            positive=action in ('approve','approve_none')
            store.put('reviewed_examples',event,dict(candidate=candidate_id,label=int(positive),provenance='explicit-human-action',
                features=candidate['features'],effect=candidate['effect'],baseline_score=candidate['baseline_score']),
                scene=scene,category=row['category'],status=state,db=db)
        if action in ('caption_style','caption_text'):
            store.put('caption_preferences',event,record,scene=scene,category=row['category'],status=state,db=db)
        if action=='quality':store.put('quality_reviews',event,record,scene=scene,category=row['category'],status='human-approved',db=db)
    return dict(status=state,event=event)


def retrieve(store,feature,limit=5):
    f.validate(feature)
    if not store.preferences()['retrieval']:return []
    target=f.vector(feature);found=[]
    for row in store.rows('reviewed_examples','category=?',(feature['category'],),limit=2000):
        data=row['data']
        if data.get('task','effects')!='effects':continue
        if data.get('provenance')!='explicit-human-action' or data.get('label')!=1:continue
        # A later explicit rejection supersedes an old approval.
        history=store.rows('user_feedback','scene_id=?',(row['scene_id'],))
        latest=next((r for r in reversed(history) if r['data'].get('candidate')==data['candidate'] and r['data'].get('action') in ('approve','approve_none','reject','remove')),None)
        if latest and latest['status']=='human-rejected':continue
        other=f.validate(data['features'])
        if other['effect_type'] not in ('none',feature['effect_type']):continue
        # Do not borrow a cropped-view example to justify unsafe full-scene zoom.
        if (other['values']['safe_zoom'] or 1)>(feature['values']['safe_zoom'] or 1)+.02:continue
        distance=sum(abs(a-b) for a,b in zip(target,f.vector(other)))/len(target)
        score=1/(1+distance)
        found.append(dict(record_id=row['id'],similarity=score,provenance='explicit-human-action',
            candidate_effect=other['effect_type'],reason='Reviewed example with compatible category, features and framing constraints.'))
    return sorted(found,key=lambda r:(-r['similarity'],r['record_id']))[:max(0,min(20,limit))]


class SemanticSearch:
    """Future optional interface; not a network or embedding implementation."""
    def search(self,feature,limit=5):raise NotImplementedError
