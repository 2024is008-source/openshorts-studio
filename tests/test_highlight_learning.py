"""Synthetic-only local ranking regression data; never production ground truth."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from learning.database import Store
from learning import datasets,models,features
from learning import highlight_features as hf,highlight_ranking as hr

def pool(n=4):
    return [dict(start=i*20.,end=i*20.+10,selection_score=80-i*10,predicted_score=75-i*10,
        verification_status='text_grounded',selection_report=dict(components=dict(hook=70-i*10,story=80,ending=60),
            evidence=dict(speech_coverage=.8 if i%2 else .2,sentence_ending=True,provider_ratings=True)),
        view_count=10_000,exported=True) for i in range(n)]

def setup(tmp_path,n=4):
    store=Store(tmp_path);rows=pool(n);snaps=hr.observe(store,rows,hashlib.sha256(b'synthetic source').hexdigest(),'podcast-education',synthetic=True)
    return store,rows,snaps

def training_data(store,groups=15):
    for g in range(groups):
        kind='challenge' if g%2 else 'podcast-education'
        snapshots=hr.observe(store,pool(6),hashlib.sha256(f'synthetic-{g}'.encode()).hexdigest(),kind,synthetic=True)
        for i,row in enumerate(snapshots):hr.feedback(store,row['id'],'accept' if i%2 else 'reject',negative_reason=None if i%2 else 'poor_story')
    return datasets.build(store,synthetic=True,task=hr.TASK)

def test_features_missing_and_no_semantic_visual_invention():
    row=pool()[0];row.update(crowd_noise=1,visual_evidence='Proposed wicket',event_verified=True)
    feature=hf.extract(row,kind='cricket')
    assert feature['values']['event_verified'] is None and feature['values']['visual'] is None
    assert feature['values']['visual_activity'] is None and feature['values']['framing_feasibility'] is None
    assert feature['category']=='sports_highlights' and feature['subcategory']=='cricket'
    assert len(features.vector(feature))==hf.VECTOR_SIZE
    row['verification_status']='model_observed'
    assert hf.extract(row)['values']['event_verified']==1

def test_prediction_features_exclude_outcomes_and_feedback():
    row=pool()[0];before=hf.extract(row)
    row.update(label=1,human_approved=True,quality_rating=5,exported=False,view_count=0,trim_correction=dict(start=5,end=10),rejected=True)
    assert hf.extract(row)==before
    broken=copy.deepcopy(before);broken['label']=1
    with pytest.raises(ValueError):hf.validate(broken)

@pytest.mark.parametrize('category,expected',[('podcast-motivation',('podcast','motivation')),('podcast-education',('podcast','education')),('podcast-comedy',('podcast','comedy')),('challenge',('challenge','auto')),('cricket',('sports_highlights','cricket')),('football',('sports_highlights','football'))])
def test_existing_category_support(category,expected):
    assert hf.category(category)==expected

@pytest.mark.parametrize('kind,role',[('podcast-motivation','takeaway'),('podcast-education','explanation'),('podcast-comedy','punchline'),('challenge','outcome')])
def test_category_features_require_retained_evidence_references(kind,role):
    row=pool()[0];row['story_report']=dict(beats=[dict(role=role,evidence_ids=['e1'])],evidence=[])
    assert hf.extract(row,kind=kind)['values']['payoff_evidence'] is None
    row['story_report']['evidence']=[dict(id='e1',channel='transcript')]
    assert hf.extract(row,kind=kind)['values']['payoff_evidence']==1

def test_observation_is_unreviewed_and_contains_no_content(tmp_path):
    store,rows,snaps=setup(tmp_path)
    assert not store.rows('reviewed_examples') and len(snaps)==4
    raw=json.dumps(store.rows('effect_candidates'))
    assert 'view_count' not in raw and 'exported' not in raw and 'source.mp4' not in raw
    assert datasets.build(store,task=hr.TASK)['rows']==[]

def test_adaptive_comparator_records_actual_hybrid_priority(tmp_path):
    store=Store(tmp_path);rows=pool(2)
    for row in rows:row.update(adaptive_priority=.84,origins=['transcript'])
    snapshots=hr.observe(store,rows,'a'*64,synthetic=True)
    assert snapshots[0]['gemini_baseline']==pytest.approx(.6)
    assert 'hybrid priority' in snapshots[0]['gemini_baseline_kind']

def test_feedback_persists_deduplicates_and_latest_verdict_wins(tmp_path):
    store,_,snaps=setup(tmp_path);cid=snaps[0]['id']
    assert hr.feedback(store,cid,'accept')['status']=='human-approved'
    assert hr.feedback(store,cid,'accept')['status']=='duplicate'
    hr.feedback(store,cid,'reject',negative_reason='irrelevant')
    data=datasets.build(store,synthetic=True,task=hr.TASK)
    assert len(data['rows'])==1 and data['rows'][0]['label']==0
    assert not datasets.build(store,task=hr.TASK)['rows'] # Synthetic labels are excluded from real readiness.
    assert not datasets.build(store)['rows'] # Effect learning remains isolated.
    hr.feedback(store,cid,'accept');assert datasets.build(store,synthetic=True,task=hr.TASK)['rows'][0]['label']==1

@pytest.mark.parametrize('action,kwargs',[('rating',{'rating':4}),('trim',{'start':1,'end':9}),('caption_style',{'preset':'podcast'}),('category',{'category':'football'}),('effect_change',{}),('weak_selected',{})])
def test_corrections_and_weak_signals_never_become_binary_labels(tmp_path,action,kwargs):
    store,_,snaps=setup(tmp_path);hr.feedback(store,snaps[0]['id'],action,**kwargs)
    assert not store.rows('reviewed_examples')
    if action=='trim':
        data=datasets.build(store,synthetic=True,task=hr.TASK)
        assert data['boundary_evaluation']['examples']==1 and data['boundary_evaluation']['mean_absolute_start_correction']==1

def test_selected_alternative_is_explicit_paired_feedback(tmp_path):
    store,_,snaps=setup(tmp_path);hr.feedback(store,snaps[0]['id'],'alternative',alternative=snaps[1]['id'])
    data=datasets.build(store,synthetic=True,task=hr.TASK)
    assert not data['rows']
    preference=store.rows('user_feedback')[0]['data']
    assert preference['alternative']==snaps[1]['id'] and preference['provenance']=='explicit-human-action'
    assert hr.feedback(store,snaps[0]['id'],'alternative',alternative=snaps[1]['id'])['status']=='duplicate'
    others=hr.observe(store,pool(2),'a'*64,'challenge',synthetic=True)
    with pytest.raises(ValueError):hr.feedback(store,snaps[0]['id'],'alternative',alternative=others[0]['id'])

def test_feedback_validation_and_privacy(tmp_path):
    store,_,snaps=setup(tmp_path);cid=snaps[0]['id']
    for action,kw in [('reject',{}),('rating',{'rating':float('nan')}),('trim',{'start':-1,'end':9}),('caption_style',{'preset':'raw /transcript'}),('accept',{'rating':8})]:
        with pytest.raises(ValueError):hr.feedback(store,cid,action,**kw)
    prefs=store.preferences();prefs['collect']=False;store.privacy(prefs)
    assert hr.observe(store,pool(),'a'*64)==[]
    with pytest.raises(ValueError):hr.feedback(store,cid,'accept')
    assert hr.apply(pool(),store=store)[0]['local_ranking']['fallback_reason']=='ML inference disabled'
    store.delete_history();assert not store.rows('effect_candidates') and not store.rows('reviewed_examples')

def test_privacy_delete_removes_owned_partial_model_but_keeps_unrelated_files(tmp_path):
    store=Store(tmp_path);partial=tmp_path/('model-'+'a'*64+'.tmp');partial.write_text('incomplete owned weights')
    unrelated=tmp_path/'my-notes.txt';unrelated.write_text('private unrelated notes')
    prefs=store.preferences();prefs['collect']=False;store.privacy(prefs)
    store.delete_history()
    assert not partial.exists() and unrelated.exists() and not store.preferences()['collect']

def test_source_content_grouping_and_unknown_source_not_trainable(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.write_bytes(b'synthetic identical bytes');b.write_bytes(a.read_bytes())
    assert hr.source_identity(a)['sha256']==hr.source_identity(b)['sha256']
    store=Store(tmp_path/'db');assert hr.observe(store,pool(),None)==[]

def test_grouped_split_provenance_fingerprint_and_no_task_mix(tmp_path):
    store=Store(tmp_path);data=training_data(store)
    assert data['synthetic'] and data['task']==hr.TASK and len(data['rows'])==90
    assert not datasets.build(store,task=hr.TASK)['rows']
    for group in {r['group'] for r in data['rows']}:assert len({r['split'] for r in data['rows'] if r['group']==group})==1
    broken=copy.deepcopy(data);broken['rows'][0]['label']=1-broken['rows'][0]['label']
    with pytest.raises(ValueError,match='fingerprint'):datasets.validate(broken)
    broken=copy.deepcopy(data);broken['rows'].append({**broken['rows'][0],'split':'test' if broken['rows'][0]['split']!='test' else 'train'})
    with pytest.raises(ValueError,match='leakage'):datasets.validate(broken)

def test_ranking_metrics_have_source_query_scope():
    rows=[dict(query='q',candidate=str(i),label=int(i==0)) for i in range(4)]
    best=hr.metrics(rows,[1,.3,.2,.1],k=1);worst=hr.metrics(rows,[0,.3,.2,1],k=1)
    assert best['precision_at_k']==best['recall_at_k']==best['ndcg_at_k']==1
    assert worst['ndcg_at_k']==0 and not best['calibrated_probability']
    assert hr.metrics(rows[:1],[.5])['ndcg_at_k'] is None

def test_existing_logistic_trainer_and_json_registry_reused_synthetic_stays_off(tmp_path):
    store=Store(tmp_path);data=training_data(store)
    result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=10))
    assert result['status']=='evaluated';identity=result['model_id'];artifact=models.load(store,identity)
    assert artifact['task']==hr.TASK and len(artifact['weights'])==hf.VECTOR_SIZE+1
    assert set(result['evaluation']['splits']['test'])=={'model','baseline','gemini','categories'}
    assert 'boundary' in result['evaluation'] and 'negative_examples' in result['evaluation']
    with pytest.raises(ValueError,match='Synthetic'):models.transition(store,identity,'approved')
    with pytest.raises(ValueError):models.transition(store,identity,'active')
    assert not store.preferences()['inference'] and not store.rows('model_registry','status=?',('active',))
    assert models.transition(store,identity,'rolled_back')['status']=='rolled_back'
    assert models.rank(store,[dict(features=data['rows'][0]['features'])],task=hr.TASK) is None
    (tmp_path/f'model-{identity}.json').write_text('{}')
    with pytest.raises(ValueError,match='checksum'):models.load(store,identity)

def test_inference_rejects_forced_synthetic_active_and_task_confusion(tmp_path):
    store=Store(tmp_path);data=training_data(store);result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=1));identity=result['model_id']
    with store.connect() as db:db.execute("UPDATE model_registry SET status='active' WHERE id=?",(identity,))
    prefs=store.preferences();prefs['inference']=True;store.privacy(prefs)
    assert models.rank(store,[dict(features=data['rows'][0]['features'])],task=hr.TASK) is None
    assert store.rows('model_registry','id=?',(identity,))[0]['status']=='rolled_back'
    assert models.rank(store,[dict(features=data['rows'][0]['features'])]) is None

def test_model_missing_or_db_unavailable_falls_back_and_preserves_manuals(tmp_path,monkeypatch):
    store=Store(tmp_path);rows=pool();rows[1]['manual_selected']=True;rows[2]['human_approved']=True
    before=copy.deepcopy(rows)
    monkeypatch.setattr(models,'rank',lambda *a,**k:[.1,.8,.4,.9])
    ranked=hr.apply(rows,'a'*64,store=store,synthetic=True)
    assert ranked[1]['start']==before[1]['start'] and ranked[2]['start']==before[2]['start']
    assert ranked[0]['start']==before[3]['start'] and ranked[-1]['start']==before[0]['start']
    assert rows==before
    monkeypatch.setattr(hr,'Store',lambda:(_ for _ in ()).throw(OSError('unavailable')))
    fallback=hr.apply(rows);assert [r['start'] for r in fallback]==[r['start'] for r in rows]
    assert 'unavailable' in fallback[0]['local_ranking']['fallback_reason']
    assert fallback[1]['learning_protected'] and fallback[2]['learning_protected']

def test_category_data_and_baseline_gates_cannot_be_waived(tmp_path):
    store=Store(tmp_path);data=training_data(store)
    # Oracle scores are evaluation-only test baselines, never prediction inputs.
    for row in data['rows']:row['baseline']=row['gemini_baseline']=float(row['label'])
    data['id']=features.digest({k:v for k,v in data.items() if k!='id'})
    artifact=dict(dataset=data['id'],weights=[0.]*(hf.VECTOR_SIZE+1));report=hr.evaluate(artifact,data)
    reasons=hr.promotion_reasons(artifact,data,report)
    assert 'Real reviewed highlight dataset required' in reasons
    assert 'insufficient reviewed examples' in reasons
    assert any('did not beat' in r for r in reasons)

def test_empty_learning_status_and_no_automatic_training(tmp_path):
    store=Store(tmp_path);state=hr.status(store)
    assert state['reviewed_examples']==0 and state['active_model'] is None and not state['enabled']
    assert 'insufficient' in state['activation_reason']
    assert not store.rows('training_datasets') and not store.rows('model_registry')

def test_corrupt_db_falls_back_and_preserves_corrupt_bytes(tmp_path):
    store=Store(tmp_path);store.path.write_bytes(b'corrupted synthetic database')
    result=hr.apply(pool(),store=store)
    assert result[0]['local_ranking']['score_kind']=='existing_deterministic'
    repaired=Store(tmp_path);assert repaired.integrity() and list(tmp_path.glob('corrupt-*.sqlite3'))

def test_retention_excludes_expired_labels_without_deleting_customer_data(tmp_path):
    store,_,snaps=setup(tmp_path);hr.feedback(store,snaps[0]['id'],'accept')
    with store.connect() as db:db.execute('UPDATE scene_features SET created=0')
    assert datasets.build(store,synthetic=True,task=hr.TASK)['rows']==[]
    assert len(store.rows('reviewed_examples'))==1

def test_missing_gemini_baseline_or_unreviewed_negatives_block_promotion(tmp_path):
    store=Store(tmp_path);data=training_data(store)
    for row in data['rows']:row['gemini_baseline']=None;row['negative_reason']=None
    data['id']=features.digest({k:v for k,v in data.items() if k!='id'})
    artifact=dict(dataset=data['id'],weights=[0.]*(hf.VECTOR_SIZE+1));report=hr.evaluate(artifact,data)
    reasons=hr.promotion_reasons(artifact,data,report)
    assert any('gemini' in reason for reason in reasons)
    assert 'Negative examples need explicit quality reasons' in reasons

def test_boundary_corrections_stay_out_of_vectors(tmp_path):
    store,rows,snaps=setup(tmp_path);cid=snaps[0]['id'];hr.feedback(store,cid,'accept')
    before=datasets.build(store,synthetic=True,task=hr.TASK)['rows'][0]['features']
    hr.feedback(store,cid,'trim',start=1,end=8)
    after=datasets.build(store,synthetic=True,task=hr.TASK)['rows'][0]
    assert after['features']==before and after['boundary']['end_delta']==-2
    assert hf.vector(before)==hf.vector(after['features'])

def test_approval_protection_survives_a_changed_candidate_pool(tmp_path):
    store,rows,snaps=setup(tmp_path);hr.feedback(store,snaps[0]['id'],'accept')
    changed=rows[:2]
    result=hr.apply(changed,hashlib.sha256(b'synthetic source').hexdigest(),'podcast-education',store=store,synthetic=True)
    assert result[0]['learning_candidate_id']!=snaps[0]['id']
    assert result[0]['learning_protected']

def test_task_rollback_preserves_other_active_task(tmp_path):
    store=Store(tmp_path)
    store.put('model_registry','effect',{'task':'effects'},status='active')
    store.put('model_registry','highlight',{'task':hr.TASK},status='approved')
    # Exercise transaction partitioning only; no production inference/artifact is activated.
    models._transition_task(store,'highlight','active',hr.TASK)
    assert store.rows('model_registry','id=?',('effect',))[0]['status']=='active'
    models._transition_task(store,'highlight','rolled_back',hr.TASK)
    assert store.rows('model_registry','id=?',('effect',))[0]['status']=='active'

def test_artifact_task_and_weight_validation(tmp_path):
    store=Store(tmp_path);data=training_data(store);result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=1));identity=result['model_id'];path=tmp_path/f'model-{identity}.json'
    value=json.loads(path.read_text());value['weights'][0]=1e100;raw=json.dumps(value).encode();path.write_bytes(raw)
    with store.connect() as db:
        entry=store.rows('model_registry','id=?',(identity,))[0]['data'];entry['checksum']=hashlib.sha256(raw).hexdigest()
        db.execute('UPDATE model_registry SET data=? WHERE id=?',(json.dumps(entry),identity))
    with pytest.raises(ValueError,match='weights'):models.load(store,identity)
