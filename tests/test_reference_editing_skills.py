import copy
import json
from pathlib import Path

import auto_edit
import editing_skills as skills
from test_auto_edit import plan, observation


def challenge():
    p=plan('challenge');p['source_ref']='synthetic.mp4'
    p['evidence']={'category_selection':{'primary_category':'challenge','subcategory':'general'}}
    return p


def test_local_number_is_exact_and_has_source_mapping(monkeypatch):
    monkeypatch.setenv('OPENSHORTS_LEARNING_DISABLED','1')
    p=challenge();p['captions'][0]['text']='$250,000'
    result=auto_edit.generate(p)
    numbers=[o for o in result['skill_plan']['opportunities'] if o['type']=='IMPORTANT_NUMBER']
    assert numbers[0]['evidence']=='$250,000'
    assert numbers[0]['source_start']==10.5 and numbers[0]['start']==.5
    assert any(e['type']=='number_highlight' for e in auto_edit.active(result))
    assert any(d['status']=='applied' for d in result['skill_plan']['decisions'])
    assert auto_edit.normalize(json.loads(json.dumps(result)),3)==result


def test_transcript_does_not_invent_visual_reaction_or_comparison():
    p=challenge();p['captions'][0]['text']='I cried before and after I won.'
    value=auto_edit.generate(p)
    types={o['type'] for o in value['skill_plan']['opportunities']}
    assert not types & {'UNEXPECTED_REACTION','BEFORE_AFTER_COMPARISON','TRANSFORMATION_REVEAL'}


def test_category_and_low_confidence_gates():
    p=plan();assert auto_edit.generate(p)['effects']==[]
    p=challenge();p['captions'][0]['aligned']=False
    assert not any(o['type']=='IMPORTANT_NUMBER' for o in auto_edit.generate(p)['skill_plan']['opportunities'])
    p=challenge();p['evidence']['category_selection']['primary_category']='sports_highlights';p['evidence']['category_selection']['subcategory']='cricket'
    assert auto_edit.generate(p)['skill_plan']['decisions']==[]


def test_emotional_dialogue_suppresses_camera_and_preserves_pauses():
    p=challenge();p['captions'][0]['text']='I am proud and in love.'
    value=auto_edit.generate(p,observation('reaction'))
    assert not any(e['category']=='camera' for e in auto_edit.active(value))
    units=[dict(start=0,end=1,text='I am proud.'),dict(start=4,end=5,text='We did it.')]
    assert skills.protect_dialogue(units)==[(0,5)]


def test_comparison_requires_two_verified_chronological_views():
    p=challenge();scenes=auto_edit.scene_records(p)
    s=scenes[0];s['observations']=[dict(comparison_id='clothes',comparison_phase='before',source_start=10.,source_end=11.,event='Earlier garment',confidence=.9)]
    assert not any(o['type']=='BEFORE_AFTER_COMPARISON' for o in skills.detect(p,scenes))
    s['observations'].append(dict(comparison_id='clothes',comparison_phase='after',source_start=12.,source_end=13.,event='Later garment',confidence=.9))
    result=skills.detect(p,scenes)
    assert {'BEFORE_AFTER_COMPARISON','TRANSFORMATION_REVEAL'} <= {o['type'] for o in result}
    s['observations'][1]['confidence']=.4
    assert not any(o['type']=='BEFORE_AFTER_COMPARISON' for o in skills.detect(p,scenes))


def test_reaction_visual_gate_and_no_fake_adapters():
    p=challenge();value=auto_edit.generate(p,observation('reaction',quote=''))
    assert any(o['type']=='UNEXPECTED_REACTION' for o in value['skill_plan']['opportunities'])
    assert any(e['type']=='snap_zoom' for e in auto_edit.active(value))
    assert all(s['adapter'] in auto_edit.SUPPORTED for s in skills.registry()['skills'])
    assert skills.registry()['training_enabled'] is False


def test_manual_override_and_trim_invalidate_old_skill_annotations():
    p=challenge();value=auto_edit.generate(p)
    value['effects'][0]['origin']='manual'
    result=auto_edit.generate(p,settings=value)
    assert any(e['origin']=='manual' for e in result['effects'])
    trimmed=auto_edit.retime(result,[dict(start=10.,end=11.5)])
    assert trimmed['skill_plan'] is None


def test_ml_stores_provenance_without_dialogue_or_approval(tmp_path):
    from learning.database import Store
    from learning.service import observe
    p=challenge();p['captions'][0]['text']='We risk $250,000 private dialogue.'
    value=auto_edit.generate(p);store=Store(tmp_path)
    observe(p,value,store)
    rows=store.rows('editing_decisions');serialized=json.dumps(rows)
    assert 'private dialogue' not in serialized and 'human-approved' not in serialized
    assert any(r['data'].get('task')=='reference-editing-skills' for r in rows)
    assert not store.preferences()['inference']
    assert store.integrity()


def test_late_emotion_does_not_suppress_earlier_number():
    p=challenge();p['captions'].append(dict(text='I am proud.',start=2.,end=2.8,source_start=12.,source_end=12.8,aligned=True))
    result=auto_edit.generate(p)
    assert any(e['type']=='number_highlight' for e in auto_edit.active(result))


def test_ten_skill_definitions_have_evidence_and_deterministic_fallback():
    definitions=skills.registry()['skills']
    assert len(definitions)==10
    for definition in definitions:
        assert definition['evidence_examples'] and definition['fallback'] and definition['quality_validation']
        assert definition['ground_truth_virality'] is False
    p=challenge();p['captions']=[]
    first=auto_edit.generate(p);second=auto_edit.generate(p)
    assert first==second and first['effects']==[]


def test_invalid_skill_mapping_rejected():
    import pytest
    value=auto_edit.generate(challenge());value['skill_plan']['opportunities'][0]['end']=999
    with pytest.raises(ValueError):auto_edit.normalize(value,3)
