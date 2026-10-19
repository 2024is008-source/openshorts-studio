"""Bounded CPU logistic ranker, honest held-out metrics and safe JSON registry."""
from collections import defaultdict,Counter
import hashlib
import json
import math
import re
from pathlib import Path
import statistics
import time
from learning import features as f
from learning.datasets import validate

DEFAULTS=dict(min_examples=100,min_categories=2,min_groups=10,min_improvement=.02,epochs=100,learning_rate=.05)


def probability(weights,x):
    z=max(-40,min(40,weights[0]+sum(a*b for a,b in zip(weights[1:],x))))
    return 1/(1+math.exp(-z))


def metrics(rows,scores):
    if not rows:return {'available':False}
    chosen=[int(p>=.5) for p in scores];groups=defaultdict(list)
    for row,score in zip(rows,scores):groups[row['scene']].append((row,score))
    top=[];pairs=[]
    for group in groups.values():
        best=max(group,key=lambda pair:(pair[1],pair[0]['id']))[0]
        if any(r['label']==1 for r,_ in group):top.append(best['label'])
        for yes,ys in group:
            for no,ns in group:
                if yes['label']==1 and no['label']==0:pairs.append(float(ys>ns)+.5*(ys==ns))
    negative=[i for i,r in enumerate(rows) if r['label']==0 and r['features']['effect_type']!='none']
    none=[i for i,r in enumerate(rows) if r['features']['effect_type']=='none']
    return dict(available=True,examples=len(rows),top_agreement=statistics.mean(top) if top else None,
        pairwise_accuracy=statistics.mean(pairs) if pairs else None,
        agreement=sum(c==r['label'] for c,r in zip(chosen,rows))/len(rows),
        false_effect_rate=sum(chosen[i] for i in negative)/len(negative) if negative else None,
        no_effect_accuracy=sum(chosen[i]==rows[i]['label'] for i in none)/len(none) if none else None,
        brier=sum((p-r['label'])**2 for p,r in zip(scores,rows))/len(rows),
        calibration=[dict(low=b/5,high=(b+1)/5,count=len(ids),mean_confidence=statistics.mean(scores[i] for i in ids),
            positive_rate=statistics.mean(rows[i]['label'] for i in ids)) for b in range(5)
            if (ids:=[i for i,p in enumerate(scores) if b/5<=p<((b+1)/5) or b==4 and p==1])])


def readiness(dataset,config=None):
    cfg=DEFAULTS|dict(config or {})
    rows=dataset['rows'];reasons=[]
    if len(rows)<cfg['min_examples']:reasons.append('insufficient reviewed examples')
    if len(dataset['categories'])<cfg['min_categories']:reasons.append('insufficient category diversity')
    if dataset['groups']<cfg['min_groups']:reasons.append('insufficient independent sources')
    for split in ('train','validation','test'):
        part=[r for r in rows if r['split']==split]
        if {r['label'] for r in part}!={0,1}:reasons.append(f'{split} needs both reviewed labels')
    return dict(ready=not reasons,status='ready' if not reasons else 'insufficient-data',reasons=reasons,
        synthetic=dataset['synthetic'],thresholds=cfg)


def train(store,dataset,config=None,cancel=None):
    validate(dataset);cfg=DEFAULTS|dict(config or {});state=readiness(dataset,cfg)
    if not state['ready']:return state
    if not 1<=cfg['epochs']<=500 or not 0<cfg['learning_rate']<=.2:raise ValueError('Unbounded training configuration')
    if len(dataset['rows'])>10000:raise ValueError('Training row limit exceeded')
    task=dataset.get('task','effects')
    if task not in ('effects','highlight-ranking'):raise ValueError('Unknown learning task')
    from learning import highlight_features as hf
    weights=[0.]*((hf.VECTOR_SIZE if task==hf.TASK else f.VECTOR_SIZE)+1);rows=[r for r in dataset['rows'] if r['split']=='train']
    prepared=[(f.vector(r['features']),r['label']) for r in rows];deadline=time.monotonic()+120
    for epoch in range(cfg['epochs']):
        if (cancel and cancel.is_set()) or time.monotonic()>deadline:return dict(status='cancelled',epochs=epoch)
        gradient=[0.]*len(weights)
        for x,label in prepared:
            error=probability(weights,x)-label;gradient[0]+=error
            for i,v in enumerate(x):gradient[i+1]+=error*v
        weights=[w-cfg['learning_rate']*(g/len(rows)+(.01*w if i else 0)) for i,(w,g) in enumerate(zip(weights,gradient))]
    artifact=dict(runtime=1,feature_version=f.VERSION,algorithm='logistic-regression',weights=weights,
        dataset=dataset['id'],synthetic=dataset['synthetic'],hyperparameters=cfg)
    if task!='effects':artifact['task']=task
    identity=f.digest(artifact);raw=json.dumps(artifact,sort_keys=True,allow_nan=False).encode()
    destination=store.root/f'model-{identity}.json';temporary=destination.with_suffix('.tmp')
    temporary.write_bytes(raw);temporary.replace(destination)
    entry=dict(artifact=destination.name,checksum=hashlib.sha256(raw).hexdigest(),dataset=dataset['id'],
        feature_version=f.VERSION,runtime=1,algorithm='logistic-regression',synthetic=dataset['synthetic'],hyperparameters=cfg)
    if task!='effects':entry['task']=task
    store.put('model_registry',identity,entry,status='candidate')
    report=evaluate(artifact,dataset)
    # Evaluation and state transition share a transaction.
    with store.connect() as db:
        store.put('model_evaluations',identity,report,status='held-out',db=db)
        db.execute('UPDATE model_registry SET status=? WHERE id=?',('evaluated',identity))
    return dict(status='evaluated',model_id=identity,evaluation=report,
        lightgbm=dict(status='optional-not-run',reason='Use an explicit optional trainer adapter; no dependency installed automatically.'))


def evaluate(artifact,dataset):
    if dataset.get('task')=='highlight-ranking':
        from learning.highlight_ranking import evaluate as clip_evaluate
        return clip_evaluate(artifact,dataset)
    report=dict(dataset=dataset['id'],synthetic=dataset['synthetic'],splits={})
    for split in ('validation','test'):
        rows=[r for r in dataset['rows'] if r['split']==split];started=time.perf_counter()
        scores=[probability(artifact['weights'],f.vector(r['features'])) for r in rows]
        elapsed=(time.perf_counter()-started)*1000
        result=metrics(rows,scores);baseline=metrics(rows,[r['baseline'] for r in rows])
        report['splits'][split]=dict(model=result,baseline=baseline,latency_ms_per_candidate=elapsed/max(1,len(rows)),
            categories={cat:metrics([r for r in rows if r['features']['category']==cat],
                [p for r,p in zip(rows,scores) if r['features']['category']==cat]) for cat in sorted({r['features']['category'] for r in rows})})
    return report


def load(store,identity):
    if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Invalid model identity')
    rows=store.rows('model_registry','id=?',(identity,))
    if not rows:raise ValueError('Unknown model')
    row=rows[0];entry=row['data']
    if entry['runtime']!=1 or entry['feature_version']!=f.VERSION:raise ValueError('Incompatible model schema')
    name=entry['artifact'];path=store.root/name
    if name!=f'model-{identity}.json' or path.is_symlink() or not path.is_file() or path.stat().st_size>1000000:raise ValueError('Untrusted model artifact')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['checksum']:raise ValueError('Artifact checksum mismatch')
    value=json.loads(raw)
    if value['algorithm']!='logistic-regression' or value['feature_version']!=f.VERSION or value['runtime']!=1:raise ValueError('Invalid model contract')
    from learning import highlight_features as hf
    task=value.get('task','effects')
    if task not in ('effects',hf.TASK) or task!=entry.get('task','effects'):raise ValueError('Model task mismatch')
    size=hf.VECTOR_SIZE if task==hf.TASK else f.VECTOR_SIZE
    if len(value['weights'])!=size+1 or any(type(w) not in (int,float) or not math.isfinite(w) or abs(w)>1e6 for w in value['weights']):raise ValueError('Invalid model weights')
    return value


def transition(store,identity,status):
    if status not in ('approved','active','rolled_back'):raise ValueError('Invalid model transition')
    model=load(store,identity);row=store.rows('model_registry','id=?',(identity,))[0]
    if status in ('approved','active'):
        if model.get('synthetic') is not False:raise ValueError('Synthetic models cannot be promoted')
        approvable=('evaluated','rolled_back') if model.get('task')=='highlight-ranking' else ('evaluated',)
        if status=='approved' and row['status'] not in approvable or status=='active' and row['status']!='approved':raise ValueError('Invalid lifecycle transition')
        reports=store.rows('model_evaluations','id=?',(identity,))
        if not reports:raise ValueError('Held-out evaluation required')
        report=reports[0]['data']
        if report.get('synthetic') is not False or report.get('dataset')!=model['dataset'] or set(report.get('splits',{}))!={'validation','test'}:raise ValueError('Invalid held-out evaluation')
        if model.get('task')=='highlight-ranking':
            from learning.highlight_ranking import promotion_reasons
            snapshots=store.rows('training_datasets','id=?',(model['dataset'],))
            if not snapshots:raise ValueError('Reviewed dataset snapshot missing')
            data=validate(snapshots[0]['data'])
            if report!=evaluate(model,data):raise ValueError('Held-out ranking evaluation mismatch')
            reasons=promotion_reasons(model,data,report)
            if reasons:raise ValueError('; '.join(reasons))
            return _transition_task(store,identity,status,model.get('task','effects'))
        improvement=max(DEFAULTS['min_improvement'],model['hyperparameters']['min_improvement'])
        if not math.isfinite(improvement) or not 0<improvement<=1:raise ValueError('Invalid improvement threshold')
        for split in report['splits'].values():
            m,b=split['model'],split['baseline']
            numbers=[result.get(key) for result in (m,b) for key in ('top_agreement','brier')]
            if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in numbers):raise ValueError('Invalid held-out metrics')
            if m['top_agreement']<b['top_agreement']+improvement or m['brier']>b['brier']:
                raise ValueError('Model did not improve held-out baseline')
    return _transition_task(store,identity,status,model.get('task','effects'))

def _transition_task(store,identity,status,task):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if status=='active':
            for row in db.execute("SELECT id,data FROM model_registry WHERE status='active'").fetchall():
                if json.loads(row['data']).get('task','effects')==task:db.execute("UPDATE model_registry SET status='rolled_back' WHERE id=?",(row['id'],))
        db.execute('UPDATE model_registry SET status=? WHERE id=?',(status,identity))
    return dict(model=identity,status=status)


def rank(store,candidates,task='effects'):
    if not store.preferences()['inference']:return None
    rows=[r for r in store.rows('model_registry','status=?',('active',)) if r['data'].get('task','effects')==task]
    if not rows:return None
    identity=rows[-1]['id']
    try:
        model=load(store,identity)
        if model.get('synthetic') is not False:raise ValueError('Synthetic model is not eligible for production inference')
        if task=='highlight-ranking':
            reports=store.rows('model_evaluations','id=?',(identity,))
            if not reports:return None
            categories=reports[0]['data'].get('splits',{}).get('test',{}).get('categories',{})
            if any(c['features']['category']+':'+c['features']['subcategory'] not in categories for c in candidates):return None
        if any(c['features'].get('task','effects')!=task for c in candidates):raise ValueError('Prediction task mismatch')
    except (ValueError,OSError,KeyError,TypeError):
        with store.connect() as db:db.execute("UPDATE model_registry SET status='rolled_back' WHERE id=?",(identity,))
        return None
    started=time.perf_counter();scores=[probability(model['weights'],f.vector(c['features'])) for c in candidates]
    if store.preferences()['collect']:store.put('inference_receipts',__import__('uuid').uuid4().hex,dict(model=identity,task=task,feature_version=f.VERSION,
        candidate_count=len(candidates),latency_ms=(time.perf_counter()-started)*1000),status='local')
    return scores
