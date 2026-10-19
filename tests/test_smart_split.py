import copy,json
import pytest
import smart_split as s
import recut


def transcript():
    return {'segments':[dict(start=a,end=b,text=text,speaker='A',words=[dict(word=text,start=a,end=b,aligned=True)]) for a,b,text in [(0.,2.,'Here is the goal.'),(6.,8.,'Here is the result.')]]}


def analysis(cat='challenge',sub='general'):
    return dict(category_selection=dict(primary_category=cat,subcategory=sub),scene_cuts=[],moments=[],
        scene_observations=[dict(start=2.,end=6.,editorial_role='irrelevant_pause',confidence=.92)])


def measured(a,b):return dict(available=True,intervals=[[2.,6.]])


def test_automatic_split_is_real_recipe_with_exact_mapping():
    result=s.plan(dict(start=0.,end=8.),transcript(),8.,analysis(),measured)
    assert result['segments']==[dict(start=0.,end=2.4),dict(start=5.6,end=8.)]
    assert result['output_duration']==4.8
    mapped=recut.virtual_transcript(transcript(),result['segments'])
    assert mapped['segments'][1]['words'][0]['start']==2.8
    assert result['mapping'][1]['start']==2.4
    assert any(o['type']=='split_join' for o in result['operations'])


@pytest.mark.parametrize('cat,sub',[('sports_highlights','cricket'),('sports_highlights','football'),('podcast','comedy')])
def test_decisive_action_and_comedic_timing_preserved(cat,sub):
    assert s.plan(dict(start=0.,end=8.),transcript(),8.,analysis(cat,sub),measured)['segments']==[dict(start=0.,end=8.)]


def test_emotional_pause_unknown_speaker_and_unmeasured_silence_preserved():
    t=transcript();t['segments'][0]['text']='I am proud.';t['segments'][0]['words'][0]['word']='I am proud.'
    assert len(s.plan(dict(start=0.,end=8.),t,8.,analysis(),measured)['segments'])==1
    t=transcript()
    for row in t['segments']:row['speaker']=None
    a=analysis();a['scene_observations']=[]
    assert len(s.plan(dict(start=0.,end=8.),t,8.,a,measured)['segments'])==1
    assert len(s.plan(dict(start=0.,end=8.),transcript(),8.,a,measured)['segments'])==1
    assert len(s.plan(dict(start=0.,end=8.),transcript(),8.,analysis())['segments'])==1


def test_manual_override_and_changed_category():
    c=dict(start=0.,end=8.,manual_override=True)
    assert s.plan(c,transcript(),8.,analysis(),measured)['locked']
    c.pop('manual_override')
    assert len(s.plan(c,transcript(),8.,analysis(),measured)['segments'])==2
    assert len(s.plan(c,transcript(),8.,analysis('sports_highlights','cricket'),measured)['segments'])==1


def test_high_confidence_optional_footage_removal_and_context_veto():
    a=analysis();a['scene_observations']=[dict(start=2.,end=6.,editorial_role='redundant_visual',confidence=.98,event='Repeated empty set',layout_evidence='No action or result in interval')]
    r=s.plan(dict(start=0.,end=8.),transcript(),8.,a)
    assert r['segments']==[dict(start=0.,end=2.),dict(start=6.,end=8.)]
    a['moments']=[dict(start=1.,end=7.,role='action')]
    assert len(s.plan(dict(start=0.,end=8.),transcript(),8.,a)['segments'])==1


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,9])
def test_invalid_source_bounds(value):
    with pytest.raises(ValueError):s.plan(dict(start=value,end=8.),transcript(),8.)
    if value in (float('inf'),float('nan')):
        with pytest.raises(ValueError):recut.normalize_segments([dict(start=0,end=value)])


def test_no_word_splits_and_safe_roundtrip():
    a=analysis();a['scene_observations']=[dict(start=1.,end=7.,editorial_role='off_topic',confidence=.99,event='Optional tangent',layout_evidence='Separate topic')]
    r=s.plan(dict(start=0.,end=8.),transcript(),8.,a)
    assert r['segments']==[dict(start=0.,end=8.)]
    assert json.loads(json.dumps(r))==r


@pytest.mark.parametrize('kind,expected',[('j_cut',3.2),('l_cut',2.8)])
def test_j_l_tracks_keep_speech_clock(kind,expected):
    base=[dict(start=0.,end=3.),dict(start=8.,end=11.)]
    plan=recut.track_edit(base,12.,[dict(index=1,type=kind,duration=.2,visual_handles_verified=True)])
    assert plan['audio_segments']==base and plan['video_segments'][0]['end']==expected
    assert recut.total_duration(plan['video_segments'])==6.
    assert plan==json.loads(json.dumps(plan))


def test_track_handles_and_overlaps_rejected():
    base=[dict(start=0.,end=3.),dict(start=8.,end=11.)]
    join=dict(index=1,type='j_cut',duration=.2,visual_handles_verified=True)
    with pytest.raises(ValueError):recut.track_edit(base,12,[dict(join,visual_handles_verified=False)])
    with pytest.raises(ValueError):recut.track_edit(base,12,[join,join])
    with pytest.raises(ValueError):recut.track_edit([dict(start=0,end=.5),dict(start=1,end=1.5)],2,[dict(join,type='l_cut')])


def test_learning_unreviewed_and_private(tmp_path,monkeypatch):
    from learning.database import Store
    monkeypatch.delenv('OPENSHORTS_LEARNING_DISABLED',raising=False)
    store=Store(tmp_path);r=s.plan(dict(start=0.,end=8.),transcript(),8.,analysis(),measured)
    s.observe(r,'private/source.mp4',store)
    rows=store.rows('editing_decisions');raw=json.dumps(rows)
    assert rows and 'private/source' not in raw and 'human-approved' not in raw
    assert not store.preferences()['inference']


def test_pipeline_updates_real_recipe_but_preserves_manual_recipe(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENSHORTS_LEARNING_DISABLED','1')
    monkeypatch.setattr('pacing.detect_silence',lambda *args:measured(0,8))
    original=dict(start=0.,end=8.)
    result=s.apply([original],transcript(),8.,'source.mp4',tmp_path,analysis())[0]
    assert result['recipe']['segments']==result['assembly_report']['segments']
    assert result['end']==4.8 and result['recipe']['pacing_audio_continuity']
    assert original==dict(start=0.,end=8.)
    result['recipe']['origin']='manual'
    saved=copy.deepcopy(result['recipe'])
    reopened=s.apply([json.loads(json.dumps(result))],transcript(),8.,'source.mp4',tmp_path,analysis())[0]
    assert reopened['recipe']==saved and reopened['assembly_report']['locked']


@pytest.mark.parametrize('confidence',[float('nan'),float('inf'),1.1,-1,True])
def test_invalid_visual_confidence_never_removes(confidence):
    a=analysis();a['scene_observations']=[dict(start=2.,end=6.,editorial_role='empty',confidence=confidence,event='Empty',layout_evidence='Empty')]
    assert s.plan(dict(start=0.,end=8.),transcript(),8.,a)['segments']==[dict(start=0.,end=8.)]


def test_transformation_milestones_and_result_are_kept_in_source_order():
    a=analysis();a['scene_observations']=[dict(start=x,end=x+1.,editorial_role=role) for x,role in [(0.,'before'),(3.,'milestone'),(6.,'after')]]
    a['scene_observations'].append(dict(start=2.,end=6.,editorial_role='redundant_visual',confidence=.99,event='Repeated view',layout_evidence='Same view'))
    result=s.plan(dict(start=0.,end=8.),transcript(),8.,a,measured)
    assert result['segments']==[dict(start=0.,end=8.)]
    assert [r['role'] for r in result['story_order']]==['before','milestone','after']


def test_assembled_edl_effect_and_caption_use_final_clock(tmp_path,monkeypatch):
    import editing_director as director
    monkeypatch.setenv('OPENSHORTS_LEARNING_DISABLED','1')
    t=transcript();t['segments'][1]['text']='The reading is 43 pounds.';t['segments'][1]['words'][0]['word']='The reading is 43 pounds.'
    report=s.plan(dict(start=0.,end=8.),t,8.,analysis(),measured)
    source=tmp_path/'source.mp4';source.write_bytes(b'identity fixture')
    context=dict(source_path=str(source),source_duration=8.,segments=report['segments'],transcript=t,analysis=analysis())
    edl=director.compile_plan(media=str(source),width=320,height=180,fps=10.,out_size=(360,640),
        ranges=[(0,48,'GENERAL')],xs=[None]*48,ys=[None]*48,crop_size=(100,180),context=context)
    assert edl['captions'][1]['start']==2.8 and edl['captions'][1]['source_start']==6.
    numbers=[o for o in edl['auto_edit']['skill_plan']['opportunities'] if o['type']=='IMPORTANT_NUMBER']
    assert numbers and numbers[0]['start']==2.8 and numbers[0]['source_start']==6.
    assert director.EditPlan.model_validate(json.loads(json.dumps(edl))).duration==4.8


def test_learning_retention_does_not_keep_orphan_assembly_records(tmp_path,monkeypatch):
    from learning.database import Store
    monkeypatch.delenv('OPENSHORTS_LEARNING_DISABLED',raising=False)
    store=Store(tmp_path);s.observe(s.plan(dict(start=0.,end=8.),transcript(),8.),'source.mp4',store)
    with store.connect() as db:db.execute('UPDATE editing_decisions SET created=0')
    store.purge()
    assert store.rows('editing_decisions')==[]
