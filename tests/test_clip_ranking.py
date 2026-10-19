import copy
import json
import math

import pytest

import clip_ranking as r
import clip_selection as cs


@pytest.mark.parametrize('value',[0,100,50.5])
def test_weighted_score_boundaries(value):
    report=r.weighted_score({key:value for key in r.DEFAULT_WEIGHTS})
    assert report['overall']==value and report['coverage_percent']==100


def test_requested_initial_weights_and_exact_weighted_sum():
    assert r.DEFAULT_WEIGHTS==dict(hook=25,story=25,engagement=20,visual=15,pacing=10,ending=5)
    metrics=dict(hook=100,story=80,engagement=60,visual=40,pacing=20,ending=0)
    assert r.weighted_score(metrics)['overall']==65


def test_missing_values_are_renormalized_and_coverage_is_explicit():
    result=r.weighted_score({'hook':80,'story':40})
    assert result['overall']==60 and result['coverage_percent']==50
    assert result['metrics']['visual'] is None
    assert result['effective_weights']['hook']==50
    assert r.weighted_score({})['overall'] is None
    assert r.weighted_score({'hook':100},{**r.DEFAULT_WEIGHTS,'hook':0})['overall'] is None


@pytest.mark.parametrize('value',[None,True,-1,101,float('nan'),float('inf'),'bad'])
def test_invalid_metric_values_are_missing_not_guessed(value):
    assert r.weighted_score({'hook':value})['overall'] is None


@pytest.mark.parametrize('weights',[{}, {'other':100}, {key:0 for key in r.DEFAULT_WEIGHTS},
    {**r.DEFAULT_WEIGHTS,'hook':-1}, {**r.DEFAULT_WEIGHTS,'hook':True},
    {**r.DEFAULT_WEIGHTS,'story':float('nan')}, {**r.DEFAULT_WEIGHTS,'ending':'bad'}])
def test_invalid_weights_are_rejected(weights):
    with pytest.raises(ValueError):r.normalize_weights(weights)


def test_custom_weights_are_idempotent_and_configurable(monkeypatch):
    weights=r.normalize_weights({key:1 for key in r.DEFAULT_WEIGHTS})
    assert sum(weights.values())==pytest.approx(100)
    assert r.normalize_weights(weights)==weights
    monkeypatch.setenv('CLIP_SCORE_WEIGHTS',json.dumps(weights))
    assert r.configured_weights()==weights
    monkeypatch.setenv('CLIP_SCORE_WEIGHTS','bad json')
    assert r.configured_weights()==r.DEFAULT_WEIGHTS


def test_visual_presence_alone_does_not_create_a_visual_score():
    report=cs.score_story(dict(start=0,end=20),[],[dict(start=0,end=20,visual_evidence='A visible scene')])
    assert report['components']['visual_interest'] is None
    assert report['ranking']['metrics']['visual'] is None
    assert report['ranking']['overall'] is None


def test_low_score_reasons_are_limited_to_available_evidence():
    units=cs.speech_units({'segments':[dict(start=0,end=2,text='And it goes'),dict(start=8,end=10,text='until the next part')]},20)
    report=cs.score_story(dict(start=0,end=10),units)['ranking']
    reasons=' '.join(report['improvements'])
    assert 'pronoun/conjunction' in reasons and 'punctuation' in reasons and '6.00s' in reasons
    assert 'outside the frame' not in reasons and 'resolution' not in reasons
    assert report['metrics']['visual'] is None and report['metrics']['engagement'] is None


def test_overlapping_speakers_do_not_double_count_pacing():
    t={'segments':[dict(start=0,end=5,text='One.'),dict(start=1,end=4,text='Two.') ]}
    report=cs.score_story(dict(start=0,end=10),cs.speech_units(t,10))
    assert report['components']['pacing']==50


def test_adjustments_are_bounded_and_idempotent():
    report=r.explain({'components':{'hook_strength':100}})
    r.adjust(report,'redundancy',8,'A measured duplicate.')
    r.adjust(report,'redundancy',8,'A measured duplicate.')
    assert report['base_score']==100 and report['overall']==92
    assert report['improvements'].count('A measured duplicate.')==1
    r.adjust(report,'other',1000)
    assert report['overall']==0


def test_rescore_preserves_all_old_records_and_media_fields():
    clips=[dict(start=0,end=20,predicted_score=99,video_url='/videos/a.mp4',clip_index=4),
           dict(start=1,end=21,predicted_score=98,video_url='/videos/b.mp4',clip_index=7)]
    original=copy.deepcopy(clips)
    result=r.rescore_clips(clips)
    assert clips==original and len(result)==2
    assert [c['clip_index'] for c in result]==[4,7]
    assert result[0]['ranking_report']['overall'] is None
    assert result[1]['ranking_report']['adjustments']['redundancy']==10
    assert 'clip 5' in ' '.join(result[1]['ranking_report']['improvements'])
    for old,new in zip(original,result):
        assert all(new[key]==value for key,value in old.items())


def test_rescore_is_reproducible_from_same_inputs_and_weights():
    clips=[dict(start=0,end=20),dict(start=30,end=50)]
    t={'segments':[dict(start=0,end=20,text='A whole idea.'),dict(start=30,end=50,text='Another whole idea.')]}
    first=r.rescore_clips(clips,t)
    second=r.rescore_clips(first,t,weights=first[0]['ranking_report']['weights'])
    assert [c['ranking_report'] for c in first]==[c['ranking_report'] for c in second]


def test_strongest_inspected_moment_maps_edl_source_to_clip_time():
    clip=dict(start=0,end=20,recipe={'segments':[dict(start=10,end=20),dict(start=40,end=50)]})
    moments=[dict(start=44,end=48,score=90,event='Measured source resolution'),dict(start=80,end=90,score=100,event='Outside selected source')]
    moment=r.strongest_moment(clip,moments)
    assert moment['source_time']==44 and moment['clip_time']==14
    assert 'Outside' not in moment['text']
    assert r.strongest_moment(clip,[dict(start=float('nan'),end=10,score=100)]) is None


def test_legacy_visual_default_without_provenance_is_not_reused():
    report=r.explain({'components':{'visual_interest':60},'evidence':{'visual_context_available':True}})
    assert report['metrics']['visual'] is None and report['overall'] is None


def test_legacy_components_do_not_invent_rating_provenance():
    report=r.explain({'components':{'hook_strength':80,'emotional_engagement':30}})
    assert report['metrics']['hook']==80
    assert 'provenance is unavailable' in report['reasons']['hook']
    assert 'Provider' not in report['reasons']['engagement']


def test_gemini_rejects_invalid_component_ratings():
    import gemini_worker as gw
    from pydantic import ValidationError
    scores=dict(hook_strength=80,standalone_context=80,narrative_completeness=80,pacing=80,ending_quality=80)
    for value in [-1,101,float('nan'),'bad',True]:
        with pytest.raises(ValidationError):gw.StoryScores.model_validate({**scores,'hook_strength':value})


def test_malformed_retained_evidence_stays_serializable_and_unassessed():
    report=r.explain({'components':None,'evidence':{'speech_coverage':float('nan'),
        'rating_fields':True},'notes':[None,4]})
    assert report['overall'] is None
    assert report['evidence']['speech_coverage'] is None
    json.dumps(report,allow_nan=False)
    assert r.explain({'components':5,'evidence':7})['overall'] is None
    clip=r.rescore_clips([{'clip_index':None,'selection_report':'invalid'}])[0]
    assert clip['ranking_report']['clip_index']==0 and clip['ranking_report']['overall'] is None
    assert r.strongest_moment({'start':0,'end':10},[None,'invalid']) is None
