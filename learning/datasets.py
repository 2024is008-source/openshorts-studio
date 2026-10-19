"""Reproducible explicitly reviewed datasets; source groups never cross splits."""
from collections import Counter,defaultdict
import time
from learning import features as f


def build(store,seed='openshorts-v1',synthetic=False,task='effects',persist=True):
    scenes={r['id']:r for r in store.rows('scene_features')};latest={}
    cutoff=time.time()-store.preferences()['retention_days']*86400
    for row in store.rows('reviewed_examples'):
        data=row['data']
        if data.get('task','effects')!=task:continue
        if task=='highlight-ranking' and (data.get('source_verified') is not True or data.get('synthetic') is True and not synthetic):continue
        if data.get('provenance')!='explicit-human-action' or type(data.get('label')) is not int or data.get('label') not in (0,1):continue
        if row['scene_id'] not in scenes:continue
        if scenes[row['scene_id']]['created']<cutoff:continue
        f.validate(data['features'])
        key=(scenes[row['scene_id']]['source_group'],data['candidate'])
        latest[key]=row
    groups=sorted({k[0] for k in latest},key=lambda g:f.digest([seed,g]))
    # Group allocation is deterministic and guarantees independent partitions
    # when enough distinct source videos exist.
    assignments={g:'test' if i%5==0 else 'validation' if i%5==1 else 'train' for i,g in enumerate(groups)}
    boundaries={r['data']['candidate']:r['data']['boundary'] for r in store.rows('user_feedback') if r['data'].get('task')=='highlight-ranking' and r['data'].get('action')=='trim'} if task=='highlight-ranking' else {}
    rows=[];seen=set()
    for row in latest.values():
        data=row['data'];scene=scenes[row['scene_id']];group=scene['source_group']
        unique=f.digest([group,data['features'],data['label'],data['candidate'] if task=='highlight-ranking' else None])
        if unique in seen:continue
        seen.add(unique)
        item=dict(id=row['id'],scene=row['scene_id'],group=group,split=assignments[group],
            features=data['features'],label=data['label'],baseline=data.get('baseline_score',.5),provenance='explicit-human-action')
        if task=='highlight-ranking':item.update(query=data['query'],candidate=data['candidate'],gemini_baseline=data.get('gemini_baseline'),gemini_baseline_kind=data.get('gemini_baseline_kind'),rating=data.get('rating'),boundary=boundaries.get(data['candidate']),negative_reason=data.get('negative_reason'),synthetic=data.get('synthetic',False))
        rows.append(item)
    rows.sort(key=lambda r:r['id'])
    counts=dict(Counter(r['features']['category'] for r in rows))
    dataset=dict(version=1,feature_version=f.VERSION,seed=seed,synthetic=bool(synthetic),rows=rows,
        categories=counts,groups=len(groups),split_counts=dict(Counter(r['split'] for r in rows)))
    if task!='effects':
        dataset['task']=task
        corrections=[r['data']['boundary'] for r in store.rows('user_feedback') if r['data'].get('task')==task and r['data'].get('action')=='trim' and (synthetic or not r['data'].get('synthetic'))]
        dataset['boundary_evaluation']=dict(available=bool(corrections),examples=len(corrections),mean_absolute_start_correction=sum(abs(c['start_delta']) for c in corrections)/len(corrections) if corrections else None,mean_absolute_end_correction=sum(abs(c['end_delta']) for c in corrections)/len(corrections) if corrections else None,interpretation='Observed corrections, not measured boundary improvement')
    dataset['id']=f.digest(dataset)
    validate(dataset)
    if persist:store.put('training_datasets',dataset['id'],dataset,status='synthetic' if synthetic else 'reviewed')
    return dataset


def validate(dataset):
    groups=defaultdict(set)
    for row in dataset['rows']:
        f.validate(row['features']);groups[row['group']].add(row['split'])
        if (row['features'].get('task','effects')!=dataset.get('task','effects') or row['split'] not in ('train','validation','test')):raise ValueError('Dataset task or split mismatch')
        if dataset.get('task')=='highlight-ranking' and row.get('synthetic') and not dataset['synthetic']:raise ValueError('Synthetic example in real dataset')
        if row['provenance']!='explicit-human-action' or type(row['label']) is not int or row['label'] not in (0,1):raise ValueError('Invalid label provenance')
    if any(len(s)>1 for s in groups.values()):raise ValueError('Source-group leakage')
    if dataset.get('task')=='highlight-ranking':
        if dataset.get('id')!=f.digest({k:v for k,v in dataset.items() if k!='id'}):raise ValueError('Dataset fingerprint mismatch')
        if dataset['groups']!=len(groups) or dataset['categories']!=dict(Counter(r['features']['category'] for r in dataset['rows'])):raise ValueError('Dataset counts mismatch')
    return dataset
