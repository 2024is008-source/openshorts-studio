"""Clip feedback/ranking on the existing store and logistic trainer. Local only."""
import copy
from collections import defaultdict,Counter
from functools import lru_cache
import hashlib
import math
import re
import time
from pathlib import Path
from learning import features as f
from learning import highlight_features as hf
from learning.database import Store

TASK=hf.TASK
ACTIONS={'accept','reject','rating','trim','alternative','category','caption_style','effect_change','weak_selected'}
NEGATIVE_REASONS={'poor_story','wrong_event','duplicate','bad_boundary','irrelevant','poor_framing','other'}

@lru_cache(maxsize=32)
def _content_hash(path,size,mtime):
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def source_identity(path):
    stat=Path(path).stat()
    return dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256=_content_hash(str(Path(path).resolve()),stat.st_size,stat.st_mtime_ns))

def signature():
    try:
        store=Store();enabled=store.preferences()['inference']
        active=[r['id'] for r in store.rows('model_registry','status=?',('active',)) if r['data'].get('task')==TASK] if enabled else []
        return dict(task=TASK,version=hf.VERSION,inference=enabled,active=active,collect=store.preferences()['collect'])
    except Exception:return dict(task=TASK,version=hf.VERSION,unavailable=True)

def _score(value):
    value=f.finite(value)
    return max(0,min(1,value/100)) if value is not None else None

def observe(store,pool,source_group,kind='general',synthetic=False):
    if not store.preferences()['collect'] or not isinstance(source_group,str) or not re.fullmatch('[0-9a-f]{64}',source_group):return []
    snapshots=[]
    for row in pool:
        feature=hf.extract(row,pool,kind);baseline=_score(row.get('selection_score'))
        provider=(row.get('selection_report') or {}).get('evidence',{}).get('provider_ratings') or row.get('verification_status')=='model_observed'
        assisted=_score(row.get('predicted_score',row.get('score'))) if provider else None
        assisted_kind='saved provider score' if assisted is not None else None
        priority=f.finite(row.get('adaptive_priority'))
        if priority is not None and (row.get('verification_status')=='model_observed' or 'transcript' in row.get('origins',[])):
            assisted=max(0,min(1,priority/1.4));assisted_kind='existing adaptive Gemini-assisted hybrid priority'
        from category_intelligence import candidate_features
        snapshots.append(dict(category_evidence=candidate_features(row,kind),task=TASK,features=feature,start=float(row['start']),end=float(row['end']),baseline_score=baseline,
            gemini_baseline=assisted,gemini_baseline_kind=assisted_kind,synthetic=bool(synthetic)))
    query=f.digest([source_group,hf.category(kind),'adaptive' if any('adaptive_priority' in row for row in pool) else 'classic',[(s['start'],s['end']) for s in snapshots]])
    with store.connect() as db:
        for snapshot in snapshots:
            cid=f.digest([query,snapshot]);scene=f.digest([TASK,source_group,snapshot['start'],snapshot['end']])
            snapshot.update(query=query,source_verified=True)
            feature=snapshot['features'];cat=feature['category']
            db.execute('INSERT OR IGNORE INTO scene_features VALUES(?,?,?,?,?,?,?,?)',
                (scene,source_group,query,cid,cat,hf.VERSION,__import__('json').dumps(feature,allow_nan=False),time.time()))
            store.put('effect_candidates',cid,snapshot,scene=scene,category=cat,db=db)
            snapshot['id']=cid
    return snapshots

def feedback(store,candidate_id,action,*,rating=None,start=None,end=None,alternative=None,category=None,subcategory='auto',preset=None,negative_reason=None):
    if not store.preferences()['collect']:raise ValueError('Learning collection is disabled')
    if action not in ACTIONS:raise ValueError('Unknown clip feedback action')
    rows=store.rows('effect_candidates','id=?',(candidate_id,))
    if not rows or rows[0]['data'].get('task')!=TASK:raise ValueError('Unknown highlight candidate')
    row=rows[0];snapshot=row['data'];hf.validate(snapshot['features'])
    if rating is not None and (f.finite(rating) is None or not 0<=rating<=5):raise ValueError('Quality rating must be 0–5')
    if action=='rating' and rating is None:raise ValueError('Rating is required')
    if action=='reject' and negative_reason not in NEGATIVE_REASONS:raise ValueError('Choose a rejection reason')
    boundary=None
    if action=='trim':
        if f.finite(start) is None or f.finite(end) is None or not snapshot['start']<=start<end<=snapshot['end']:raise ValueError('Trim must stay within the immutable candidate range')
        boundary=dict(start=float(start),end=float(end),start_delta=float(start)-snapshot['start'],end_delta=float(end)-snapshot['end'])
    other=None
    if action=='alternative':
        values=store.rows('effect_candidates','id=?',(alternative,))
        if not values or alternative==candidate_id or values[0]['data'].get('task')!=TASK or values[0]['data'].get('query')!=snapshot['query']:raise ValueError('Alternative must belong to this same source candidate pool')
        other=values[0]
    if action=='category':
        cat,sub=hf.category(category,subcategory)
        if cat=='default_clipping' and category!='general':raise ValueError('Unsupported feedback category')
    else:cat,sub=snapshot['features']['category'],snapshot['features']['subcategory']
    if action=='caption_style' and (not isinstance(preset,str) or not re.fullmatch('[A-Za-z0-9 _.-]{1,64}',preset)):raise ValueError('Invalid caption preset')
    event=dict(task=TASK,candidate=candidate_id,action=action,rating=rating,boundary=boundary,alternative=alternative,
        category=cat,subcategory=sub,preset=preset,negative_reason=negative_reason,
        synthetic=bool(snapshot.get('synthetic')),
        provenance='weak-behavior' if action=='weak_selected' else 'explicit-human-action')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT id,data FROM user_feedback WHERE scene_id=? ORDER BY created DESC,id DESC LIMIT 1',(row['scene_id'],)).fetchone()
        if prior and __import__('json').loads(prior['data'])==event:return dict(status='duplicate',event=prior['id'])
        identity=f.digest([event,prior['id'] if prior else None]);store.put('user_feedback',identity,event,scene=row['scene_id'],category=cat,status='weak' if action=='weak_selected' else 'human-modified',db=db)
        # A preferred alternative does not prove that the original is irrelevant.
        # Keep pairwise preferences, ratings and corrections separate from labels.
        labels=[(row,int(action=='accept'))] if action in ('accept','reject') else []
        for target,label in labels:
            data=target['data'];review=dict(data,candidate=target['id'],label=label,provenance='explicit-human-action',rating=rating,negative_reason='selected_alternative' if action=='alternative' and not label else negative_reason)
            store.put('reviewed_examples',f.digest([identity,target['id']]),review,scene=target['scene_id'],category=target['category'],status='human-approved' if label else 'human-rejected',db=db)
        if action=='caption_style':store.put('caption_preferences',identity,event,scene=row['scene_id'],category=cat,status='human-modified',db=db)
        if action=='rating':store.put('quality_reviews',identity,event,scene=row['scene_id'],category=cat,status='human-approved',db=db)
    return dict(status='weak' if action=='weak_selected' else 'human-approved' if action=='accept' else 'human-rejected' if action=='reject' else 'human-modified',event=identity)

def metrics(rows,scores,k=3):
    if not rows:return dict(available=False)
    if len(rows)!=len(scores) or any(f.finite(s) is None or not 0<=s<=1 for s in scores):raise ValueError('Invalid ranking scores')
    queries=defaultdict(list)
    for row,score in zip(rows,scores):queries[row['query']].append((row,score))
    precision=[];recall=[];ndcg=[];paired=0;boundary_errors=[]
    for values in queries.values():
        if len(values)<2 or {r['label'] for r,_ in values}!={0,1}:continue
        paired+=1;ordered=sorted(values,key=lambda p:(-p[1],p[0]['candidate']));n=min(k,len(ordered));yes=sum(r['label'] for r,_ in ordered[:n]);total=sum(r['label'] for r,_ in ordered)
        precision.append(yes/n);recall.append(yes/total)
        boundary_errors.extend((abs(r['boundary']['start_delta']),abs(r['boundary']['end_delta'])) for r,_ in ordered[:n] if r.get('boundary'))
        dcg=sum(r['label']/math.log2(i+2) for i,(r,_) in enumerate(ordered[:n]));ideal=sum(1/math.log2(i+2) for i in range(min(total,n)));ndcg.append(dcg/ideal if ideal else 0)
    mean=lambda values:sum(values)/len(values) if values else None
    return dict(available=True,examples=len(rows),paired_queries=paired,k=k,precision_at_k=mean(precision),recall_at_k=mean(recall),ndcg_at_k=mean(ndcg),brier=sum((s-r['label'])**2 for r,s in zip(rows,scores))/len(rows),calibrated_probability=False,
        boundary=dict(reviewed_selected=len(boundary_errors),start_mae=mean([v[0] for v in boundary_errors]),end_mae=mean([v[1] for v in boundary_errors]),missing_means_unavailable=True))

def evaluate(artifact,dataset):
    from learning.models import probability
    report=dict(task=TASK,dataset=dataset['id'],synthetic=dataset['synthetic'],splits={},comparator_kinds=dict(Counter(r.get('gemini_baseline_kind') or 'unavailable' for r in dataset['rows'])),coverage='Ranking metrics use explicitly reviewed candidates only; unreviewed candidates are not negatives')
    for split in ('validation','test'):
        rows=[r for r in dataset['rows'] if r['split']==split]
        def evaluate_rows(part):
            scores=[probability(artifact['weights'],hf.vector(r['features'])) for r in part]
            baseline=lambda field:metrics(part,[r[field] for r in part]) if part and all(f.finite(r.get(field)) is not None and 0<=r[field]<=1 for r in part) else {'available':False}
            return dict(model=metrics(part,scores),baseline=baseline('baseline'),gemini=baseline('gemini_baseline'))
        result=evaluate_rows(rows)
        result['categories']={cat:evaluate_rows([r for r in rows if r['features']['category']+':'+r['features']['subcategory']==cat]) for cat in sorted({r['features']['category']+':'+r['features']['subcategory'] for r in rows})}
        report['splits'][split]=result
    report['boundary']=dataset.get('boundary_evaluation',dict(available=False,reason='No paired reviewed boundary corrections'))
    report['negative_examples']=dict(total=sum(r['label']==0 for r in dataset['rows']),with_explicit_reason=sum(r['label']==0 and bool(r.get('negative_reason')) for r in dataset['rows']))
    return report

def promotion_reasons(model,dataset,report):
    from learning.models import readiness,DEFAULTS
    reasons=list(readiness(dataset)['reasons'])
    if dataset.get('task')!=TASK or dataset.get('synthetic') is not False:reasons.append('Real reviewed highlight dataset required')
    if dataset.get('id')!=model.get('dataset') or report.get('dataset')!=dataset.get('id') or report.get('synthetic') is not False:reasons.append('Evaluation provenance mismatch')
    for name in ('validation','test'):
        result=report.get('splits',{}).get(name,{})
        m=result.get('model',{})
        for key in ('baseline','gemini'):
            b=result.get(key,{})
            if not m.get('available') or not b.get('available') or (m.get('paired_queries') or 0)<2:reasons.append(f'{name}: insufficient paired model/{key} results');continue
            for metric in ('precision_at_k','recall_at_k','ndcg_at_k','brier'):
                if any(f.finite(r.get(metric)) is None or not 0<=r[metric]<=1 for r in (m,b)):reasons.append(f'{name}: invalid ranking metric');break
            else:
                if m['ndcg_at_k']<b['ndcg_at_k']+DEFAULTS['min_improvement'] or m['precision_at_k']<b['precision_at_k'] or m['recall_at_k']<b['recall_at_k'] or m['brier']>b['brier']:reasons.append(f'{name}: did not beat {key}')
    if any(r['label']==0 and not r.get('negative_reason') for r in dataset['rows']):reasons.append('Negative examples need explicit quality reasons')
    for category in {r['features']['category']+':'+r['features']['subcategory'] for r in dataset['rows']}:
        part=[r for r in dataset['rows'] if r['features']['category']+':'+r['features']['subcategory']==category]
        if len(part)<20 or len({r['group'] for r in part})<4:reasons.append(category+': insufficient reviewed category data')
        for name in ('validation','test'):
            result=report.get('splits',{}).get(name,{}).get('categories',{}).get(category,{})
            if (result.get('model',{}).get('paired_queries') or 0)<2:reasons.append(category+': insufficient category holdout queries')
            for baseline in ('baseline','gemini'):
                m,b=result.get('model',{}),result.get(baseline,{})
                if not b.get('available') or any(f.finite(r.get('ndcg_at_k')) is None for r in (m,b)):reasons.append(category+': category baseline unavailable');continue
                if m['ndcg_at_k']<b['ndcg_at_k']:reasons.append(category+': category ranking regressed')
                mb,bb=m.get('boundary',{}),b.get('boundary',{})
                if mb.get('reviewed_selected') and mb.get('reviewed_selected')==bb.get('reviewed_selected') and (mb['start_mae']>bb['start_mae'] or mb['end_mae']>bb['end_mae']):reasons.append(category+': reviewed boundary quality regressed')
    return sorted(set(reasons))

def status(store):
    from learning import datasets,models
    data=datasets.build(store,task=TASK,persist=False);state=models.readiness(data)
    registry=[r for r in store.rows('model_registry') if r['data'].get('task')==TASK]
    active=next((r['id'] for r in reversed(registry) if r['status']=='active'),None)
    evaluation=next((r['data'] for r in reversed(store.rows('model_evaluations')) if r['data'].get('task')==TASK),None)
    reasons=list(state['reasons']);candidate=registry[-1]['id'] if registry else None
    if candidate and not reasons:
        try:
            model=models.load(store,candidate);snapshots=store.rows('training_datasets','id=?',(model['dataset'],))
            reasons=promotion_reasons(model,snapshots[0]['data'],models.evaluate(model,snapshots[0]['data'])) if snapshots else ['Training dataset unavailable']
        except (ValueError,OSError,KeyError,TypeError):reasons=['Candidate model unavailable or incompatible']
    if not reasons:reasons=['Explicit model approval/activation and privacy inference opt-in required']
    return dict(task=TASK,reviewed_examples=len(data['rows']),independent_sources=data['groups'],categories=data['categories'],training=state,active_model=active,candidate_model=candidate,enabled=store.preferences()['inference'],evaluation=evaluation,activation_reason='; '.join(reasons),confidence='Raw logistic scores; calibrated probabilities are not claimed',local_only=True)

def apply(pool,source_group=None,kind='general',store=None,synthetic=False,baseline_key='selection_score'):
    """Annotate safe existing candidates; stable protected positions, fail-open ordering."""
    if not pool:return pool
    original=copy.deepcopy(pool)
    for row in original:row['learning_protected']=bool(row.get('learning_protected') or row.get('manual_selected') or row.get('human_approved') or row.get('selection_origin')=='manual')
    try:
        from learning import models
        store=store or Store();snapshots=observe(store,original,source_group,kind,synthetic)
        reviews=[r for r in store.rows('reviewed_examples') if r['data'].get('task')==TASK]
        reviewed={r['data']['candidate']:r['data']['label'] for r in reviews}
        reviewed_scenes={r['scene_id']:r['data']['label'] for r in reviews}
        candidates=[dict(features=hf.extract(row,original,kind)) for row in original]
        scores=models.rank(store,candidates,task=TASK)
        reason='ML inference disabled' if not store.preferences()['inference'] else 'No compatible active highlight model or category evaluation'
        for i,row in enumerate(original):
            snapshot=snapshots[i] if snapshots else None
            scene=f.digest([TASK,source_group,float(row['start']),float(row['end'])]) if source_group else None
            locked=bool(row.get('learning_protected') or snapshot and reviewed.get(snapshot['id'])==1 or scene and reviewed_scenes.get(scene)==1)
            row['learning_protected']=locked
            if snapshot:row['learning_candidate_id']=snapshot['id']
            row['local_ranking']=dict(task=TASK,relevance_score=scores[i] if scores is not None else _score(row.get('selection_score')),score_kind='model_raw_score' if scores is not None else 'existing_deterministic',confidence=None,calibration='not claimed',fallback_reason=reason if scores is None else None,
                evidence_summary=dict(available=[k for k,v in candidates[i]['features']['values'].items() if v is not None],missing=[k for k,v in candidates[i]['features']['values'].items() if v is None]),explanation='Existing evidence and source eligibility remain authoritative; reviewed/manual candidates are protected.')
        if scores is None:return original
        # Only unprotected slots may change. No clip range, effect or caption is edited.
        unlocked=sorted((i for i,r in enumerate(original) if not r['learning_protected']),key=lambda i:(-scores[i],i));iterator=iter(unlocked)
        return [r if r['learning_protected'] else original[next(iterator)] for r in original]
    except Exception:
        for row in original:row['local_ranking']=dict(task=TASK,relevance_score=_score(row.get('selection_score')),score_kind='existing_deterministic',confidence=None,fallback_reason='Local learning unavailable; existing selection preserved')
        return original
