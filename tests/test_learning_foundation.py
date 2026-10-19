import concurrent.futures
import copy
import json
import sqlite3
import threading
from pathlib import Path
import pytest
from learning.database import Store
from learning import features as f,service,datasets,models
from learning.policies import policy,category


def scene():
    return dict(id='scene-0',start=0.,end=5.,source_start=10.,source_end=15.,shot_type='GENERAL',
        visible_subjects=[],important_regions=[],speech=[dict(text='retained',start=1.,end=2.)],
        confidence=.9,safe_zoom=1.,transition='shot_boundary',motion={'relative_audio_peak':.6},
        observations=[dict(layout_intent='preserve_scene',role='setup')],cues=[])


def setup(store,group='source',kind='challenge'):
    plan=dict(source_identity=group,segments=[dict(start=10,end=15)],kind=kind)
    effect=dict(id='effect-1',type='keyword_highlight',source_scene='scene-0',start=1.,end=2.,duration=1.,intensity=.6,
        origin='ai',enabled=True,confidence=.9,parameters={'quote':'private entire transcript'})
    settings=dict(scenes=[scene()],effects=[effect])
    return service.observe(plan,settings,store)


def test_migrations_integrity_backup_recovery_delete(tmp_path):
    store=Store(tmp_path);ids=setup(store)
    assert store.integrity()
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO user_feedback VALUES('bad','missing','','','{}',0)")
    store.backup();store.path.write_bytes(b'corrupt database')
    restored=Store(tmp_path)
    assert restored.integrity() and restored.rows('effect_candidates')
    assert list(tmp_path.glob('corrupt-*'))
    restored.delete_history()
    assert not restored.rows('effect_candidates') and not (tmp_path/'knowledge-backup.sqlite3').exists()


def test_concurrent_writes_and_dedup(tmp_path):
    store=Store(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(4) as workers:
        list(workers.map(lambda i:store.put('quality_reviews',f'r{i%5}',dict(rating=4)),range(40)))
    assert len(store.rows('quality_reviews'))==5 and store.integrity()


def test_features_missing_values_no_labels_and_identical_transform():
    value=f.extract(scene())
    assert value['values']['visual_complexity'] is None and value['values']['speaker_change'] is None
    assert f.vector(value)==f.vector(json.loads(json.dumps(value)))
    assert len(f.vector(value))==f.VECTOR_SIZE
    value['human_rating']=5
    with pytest.raises(ValueError):f.validate(value)
    assert category('educational')=='podcast' and policy('sports_highlights','cricket')['foundation_only']
    with pytest.raises(ValueError):policy('podcast','invented')


def test_feedback_is_explicit_deduped_private_and_none_is_valid(tmp_path):
    store=Store(tmp_path);ids=setup(store)
    assert not store.rows('reviewed_examples')
    candidate=ids[0]['id'];none=ids[1]['id']
    assert service.feedback(store,'explicit-1',candidate,'approve')['status']=='human-approved'
    assert service.feedback(store,'explicit-1',candidate,'approve')['status']=='duplicate'
    service.feedback(store,'explicit-2',none,'approve_none')
    assert len(store.rows('reviewed_examples'))==2
    assert 'private entire transcript' not in str(store.rows('effect_candidates'))
    feature=store.rows('effect_candidates','id=?',(candidate,))[0]['data']['features']
    assert service.retrieve(store,feature)[0]['provenance']=='explicit-human-action'
    service.feedback(store,'explicit-3',candidate,'reject')
    dataset=datasets.build(store)
    assert any(r['label']==0 for r in dataset['rows']) and any(r['features']['effect_type']=='none' for r in dataset['rows'])


@pytest.mark.parametrize('action',['remove','replace','adjust_intensity','adjust_duration','adjust_timing','caption_style','caption_text','quality'])
def test_corrections_are_recorded_without_implicit_labels(tmp_path,action):
    store=Store(tmp_path);candidate=setup(store)[0]['id']
    service.feedback(store,'correction-1',candidate,action,{'intensity':.5},{'intensity':.7},rating=4)
    assert store.rows('user_feedback')[0]['data']['before']['intensity']==.5
    assert not store.rows('reviewed_examples') if action!='remove' else store.rows('reviewed_examples')[0]['data']['label']==0


def reviewed_dataset(store,groups=15):
    for i in range(groups):
        ids=setup(store,f'source-{i}','challenge' if i%2 else 'podcast')
        service.feedback(store,f'approved-{i}',ids[0]['id'],'approve')
        service.feedback(store,f'rejected-{i}',ids[1]['id'],'reject')
    return datasets.build(store,synthetic=True)


def test_dataset_reproducible_grouped_and_no_leakage(tmp_path):
    store=Store(tmp_path);data=reviewed_dataset(store)
    assert data==datasets.build(store,synthetic=True)
    assert all(len({r['split'] for r in data['rows'] if r['group']==g})==1 for g in {r['group'] for r in data['rows']})
    broken=copy.deepcopy(data);broken['rows'].append({**broken['rows'][0],'split':'another'})
    with pytest.raises(ValueError):datasets.validate(broken)


def test_insufficient_data_does_not_train(tmp_path):
    store=Store(tmp_path);data=datasets.build(store)
    assert models.train(store,data)['status']=='insufficient-data'
    assert not list(tmp_path.glob('model-*.json')) and not store.preferences()['inference']


def test_training_evaluation_safe_artifact_synthetic_not_promoted(tmp_path):
    store=Store(tmp_path);data=reviewed_dataset(store)
    result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=20))
    assert result['status']=='evaluated'
    identity=result['model_id'];model=models.load(store,identity)
    assert model['algorithm']=='logistic-regression'
    assert result['evaluation']['splits']['test']['model']['available']
    assert result['evaluation']['splits']['test']['model']['pairwise_accuracy'] is not None
    with pytest.raises(ValueError,match='Synthetic'):models.transition(store,identity,'approved')
    path=tmp_path/f'model-{identity}.json';path.write_text('{}')
    with pytest.raises(ValueError,match='checksum'):models.load(store,identity)


def test_training_cancel_and_failed_database_never_break_director(tmp_path,monkeypatch):
    store=Store(tmp_path);data=reviewed_dataset(store);cancel=threading.Event();cancel.set()
    assert models.train(store,data,dict(min_examples=10,min_groups=5),cancel)['status']=='cancelled'
    import learning.integration as bridge
    monkeypatch.setattr(bridge,'Store',lambda:(_ for _ in ()).throw(OSError('unavailable')))
    settings={'effects':[]}
    assert bridge.apply({},settings) is settings


def test_privacy_retention_and_credential_rejection(tmp_path):
    store=Store(tmp_path);ids=setup(store)
    prefs=store.preferences();prefs['collect']=False;store.privacy(prefs)
    assert service.observe({}, {},store)==[]
    with pytest.raises(ValueError):service.feedback(store,'blocked-review',ids[0]['id'],'approve')
    prefs['upload']=True
    with pytest.raises(ValueError):store.privacy(prefs)
    with pytest.raises(ValueError):store.put('quality_reviews','unsafe',{'api_key':'secret'})
    with store.connect() as db:db.execute('UPDATE scene_features SET created=0')
    store.purge();assert not store.rows('scene_features') and not store.rows('effect_candidates')


def test_corrupt_database_and_corrupt_backup_recover_together(tmp_path):
    store=Store(tmp_path);store.path.write_bytes(b'corrupted')
    (tmp_path/'knowledge-backup.sqlite3').write_bytes(b'also corrupted')
    assert Store(tmp_path).integrity()
    assert list(tmp_path.glob('corrupt-backup-*'))


def test_busy_database_is_never_quarantined(tmp_path,monkeypatch):
    store=Store(tmp_path);before=store.path.read_bytes()
    from contextlib import contextmanager
    @contextmanager
    def locked(*args):
        error=sqlite3.OperationalError('database is locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        raise error
        yield
    monkeypatch.setattr(Store,'connect',locked)
    with pytest.raises(sqlite3.OperationalError):Store(tmp_path)
    assert store.path.read_bytes()==before and not list(tmp_path.glob('corrupt-*'))


def test_untrusted_stored_privacy_is_validated_and_can_be_repaired(tmp_path):
    store=Store(tmp_path);store.put('privacy_preferences','local',{'inference':'yes'})
    with pytest.raises(ValueError):store.preferences()
    store.privacy(dict(collect=True,retrieval=True,inference=False,retention_days=30,upload=False))
    assert not store.preferences()['inference']


@pytest.mark.parametrize('state',['empty','unreviewed','disabled','missing_model','corrupt_database','unavailable_database'])
def test_existing_director_survives_optional_learning_failures(tmp_path,monkeypatch,state):
    import auto_edit
    import learning.integration as bridge
    from test_auto_edit import plan,observation,manual
    monkeypatch.setenv('OPENSHORTS_LEARNING_DIR',str(tmp_path))
    monkeypatch.setenv('OPENSHORTS_LEARNING_DISABLED','1')
    original=manual();expected=auto_edit.generate(plan(),observation(),original)
    store=Store(tmp_path)
    if state=='unreviewed':setup(store)
    if state in ('missing_model','corrupt_database'):
        prefs=store.preferences();prefs['inference']=True;store.privacy(prefs)
    if state=='missing_model':
        store.put('model_registry','missing',dict(runtime=1,feature_version=1,artifact='model-missing.json'),status='active')
    if state=='corrupt_database':store.path.write_bytes(b'broken')
    if state=='unavailable_database':monkeypatch.setattr(bridge,'Store',lambda:(_ for _ in ()).throw(OSError('unavailable')))
    monkeypatch.delenv('OPENSHORTS_LEARNING_DISABLED')
    assert auto_edit.generate(plan(),observation(),original)==expected
    assert next(e for e in expected['effects'] if e['origin']=='manual')['intensity']==original['effects'][0]['intensity']


def test_synthetic_model_cannot_bypass_activation_gate(tmp_path):
    store=Store(tmp_path);data=reviewed_dataset(store)
    result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=2));identity=result['model_id']
    with store.connect() as db:db.execute("UPDATE model_registry SET status='active' WHERE id=?",(identity,))
    prefs=store.preferences();prefs['inference']=True;store.privacy(prefs)
    assert models.rank(store,[data['rows'][0]]) is None
    assert store.rows('model_registry','id=?',(identity,))[0]['status']=='rolled_back'


def test_latest_rejection_supersedes_retrieval_and_new_uuid_is_not_new_label(tmp_path):
    store=Store(tmp_path);candidate=setup(store)[0]['id']
    service.feedback(store,'approve-uuid',candidate,'approve')
    assert service.feedback(store,'another-uuid',candidate,'approve')['status']=='duplicate'
    service.feedback(store,'reject-uuid',candidate,'reject')
    feature=store.rows('effect_candidates','id=?',(candidate,))[0]['data']['features']
    assert not service.retrieve(store,feature)
    assert datasets.build(store)['rows'][0]['label']==0
    service.feedback(store,'reapprove-uuid',candidate,'approve')
    assert datasets.build(store)['rows'][0]['label']==1
    assert service.feedback(store,'repeat-approve',candidate,'approve')['status']=='duplicate'


def test_changed_candidate_needs_snapshot_before_positive_label(tmp_path):
    store=Store(tmp_path);candidate=setup(store)[0]['id']
    with pytest.raises(ValueError,match='Refresh'):
        service.feedback(store,'changed-approve',candidate,'approve',{'intensity':.5},{'intensity':.8})
    assert not store.rows('reviewed_examples')


def test_optional_ranker_preserves_manual_edits_and_training_features(tmp_path,monkeypatch):
    import auto_edit
    import learning.integration as bridge
    from test_auto_edit import plan,observation,manual
    settings=auto_edit.generate(plan(),observation(),manual())
    store=Store(tmp_path);prefs=store.preferences();prefs['inference']=True;store.privacy(prefs)
    monkeypatch.setattr(bridge,'Store',lambda:store)
    def prefer_none(db,candidates):
        recorded=[r['data']['features'] for r in db.rows('effect_candidates')]
        assert candidates and all(c['features'] in recorded for c in candidates)
        return [float(i%2) for i in range(len(candidates))]
    monkeypatch.setattr(bridge,'rank',prefer_none)
    value=bridge.apply(plan(),settings)
    assert value['effects']==[e for e in settings['effects'] if e['origin']=='manual']
    assert auto_edit.normalize(value,plan()['duration'])==value


def test_source_spacing_context_is_shared_without_invented_measurements():
    first=scene();second={**scene(),'id':'scene-1','start':5.,'end':10.}
    settings={'scenes':[first,second],'effects':[{'source_scene':first['id'],'end':2.}]}
    contexts=list(f.scene_contexts(settings))
    assert contexts[1][2]==2.
    feature=f.extract(second,previous_end=contexts[1][2])
    assert feature['values']['effect_spacing']==3.
    assert feature['values']['framing_confidence'] is None and feature['values']['quiet_fraction'] is None


def test_registry_requires_held_out_improvement_and_valid_lifecycle(tmp_path):
    # Promotion decisions are tested without activating a synthetic artifact.
    store=Store(tmp_path);data=reviewed_dataset(store)
    result=models.train(store,data,dict(min_examples=10,min_groups=5,epochs=2))
    identity=result['model_id']
    with pytest.raises(ValueError):models.transition(store,identity,'active')
    assert store.rows('model_registry','id=?',(identity,))[0]['status']=='evaluated'
    assert models.transition(store,identity,'rolled_back')['status']=='rolled_back'
    assert not store.rows('model_registry','status=?',('active',))


@pytest.mark.parametrize('splits',[{}, {'test':{}}, {'validation':{'model':{'top_agreement':float('nan')}},'test':{}}])
def test_invalid_evaluation_never_passes_promotion_gate(tmp_path,monkeypatch,splits):
    store=Store(tmp_path);store.put('model_registry','gate',{},status='evaluated')
    monkeypatch.setattr(models,'load',lambda *args:dict(synthetic=False,dataset='reviewed-dataset',hyperparameters={'min_improvement':.02}))
    # SQLite JSON rejects NaN on write, as do the model's metric gates.
    if 'validation' in splits:
        with pytest.raises(ValueError):store.put('model_evaluations','gate',dict(synthetic=False,dataset='reviewed-dataset',splits=splits))
    else:
        store.put('model_evaluations','gate',dict(synthetic=False,dataset='reviewed-dataset',splits=splits))
        with pytest.raises(ValueError):models.transition(store,'gate','approved')
    assert store.rows('model_registry','id=?',('gate',))[0]['status']=='evaluated'
