"""Deterministic TASK-005 fixtures; no cloud requests or emotion classifiers."""
import copy
import json
from pathlib import Path
import subprocess

import pytest
import clip_selection as cs
import story_director as sd
from test_story_selection import pipeline  # noqa: F401

FIXTURES=json.loads((Path(__file__).parent/'fixtures/story_modes.json').read_text(encoding='utf-8'))


def source(mode='challenge'):
    segments=[dict(start=a,end=b,text=text) for (a,b),text in zip([(1,8),(9,17),(18,27)],FIXTURES[mode])]
    return dict(language='en',segments=segments)


def candidate(mode='challenge',score=90):
    transcript=source(mode)
    evidence=[dict(id=str(i),start=s['start'],end=s['end'],channel='transcript',quote=s['text']) for i,s in enumerate(transcript['segments'])]
    ratings=[dict(criterion=key,score=score,reason='Supported by the retained source utterances.',evidence_ids=ids)
        for key,ids in [('opening_quality',['0']),('context_completeness',['0']),('value',['1']),
            ('narrative_progression',['0','2']),('ending_completeness',['2'])]]
    return dict(start=0,end=28,predicted_score=40,story=dict(mode=mode,idea=FIXTURES[mode][0],evidence=evidence,
        beats=[dict(role='setup',evidence_ids=['0']),dict(role='development',evidence_ids=['1']),dict(role='outcome',evidence_ids=['2'])],
        ratings=ratings,hook_quote=FIXTURES[mode][0],ending_note='The final retained utterance completes this account.'))


@pytest.mark.parametrize('mode',list(FIXTURES))
def test_five_modes_produce_grounded_ranked_explanations(mode,monkeypatch):
    monkeypatch.setenv('STORY_MODE',mode)
    row=cs.select_story_candidates([candidate(mode)],source(mode),30)[0]
    report=row['story_report']
    assert report['mode']==mode and report['rank']==1 and 0<=report['score']<=100
    assert report['scores']['value']['score']==90
    assert report['scores']['visual_relevance'] is None
    assert cs.valid_range(report['start'],report['end'],30)
    assert all(report['start']<=e['start']<e['end']<=report['end'] for e in report['evidence'])
    assert 'Evidence: 1' in row['ranking_report']['reasons']['engagement']


def test_speech_evidence_cannot_remove_negation_or_retime_a_sentence():
    row=candidate();row['story']['evidence'][0]['quote']='We finished ten laps.'
    row['story']['evidence'][1].update(start=9,end=10)  # not the full measured utterance
    story=sd.grounded_story(row,cs.speech_units(source(),30))
    assert {e['id'] for e in story['evidence']}=={'2'}
    assert {r['criterion'] for r in story['ratings']}=={'ending_completeness'}


def test_missing_or_unknown_evidence_never_receives_provider_scores():
    row=candidate();row['story']['ratings'][0]['evidence_ids']=['unknown']
    story=sd.grounded_story(row,cs.speech_units(source(),30))
    assert not any(r['criterion']=='opening_quality' for r in story['ratings'])


@pytest.mark.parametrize('description',['She feels sad.','He is angry.','She secretly intends to quit.','She appears devastated.'])
def test_facial_appearance_cannot_establish_internal_states(description,monkeypatch):
    monkeypatch.setenv('STORY_MODE','emotional')
    row=candidate('emotional');row['story']['evidence']=[dict(id='face',start=2,end=5,channel='visual',description=description)]
    row['story']['ratings']=[dict(criterion='value',score=100,reason='Face shows an emotion.',evidence_ids=['face'])]
    story=sd.grounded_story(row,cs.speech_units(source('emotional'),30),watched=True)
    assert not story['ratings'] and all(e['channel']=='transcript' for e in story['evidence'])


def test_observed_smile_is_not_an_emotional_state_rating(monkeypatch):
    monkeypatch.setenv('STORY_MODE','emotional')
    row=candidate();row['story']['evidence']=[dict(id='face',start=2,end=5,channel='visual',description='A person smiles.')]
    row['story']['ratings']=[dict(criterion='value',score=100,reason='Visible smile.',evidence_ids=['face'])]
    story=sd.grounded_story(row,[],watched=True)
    assert story['evidence'][0]['description']=='A person smiles.' and not story['ratings']


def test_detail_cannot_invent_or_change_video_and_audio_observations():
    row=candidate();observation=dict(id='v',start=10,end=12,channel='visual',description='A runner crosses a marked line.')
    row['story']['evidence'].append(observation)
    row['story']['ratings'].append(dict(criterion='visual_relevance',score=85,reason='The shown action matches the challenge.',evidence_ids=['v']))
    units=cs.speech_units(source(),30)
    assert not any(e['channel']=='visual' for e in sd.grounded_story(row,units)['evidence'])
    context=[dict(story=dict(evidence=[copy.deepcopy(observation)]))]
    assert any(r['criterion']=='visual_relevance' for r in sd.grounded_story(row,units,context)['ratings'])
    row['story']['evidence'][-1]['description']='A runner receives a trophy.'
    assert not any(e['channel']=='visual' for e in sd.grounded_story(row,units,context)['evidence'])


def test_unheard_laughter_is_not_inferred_from_energy():
    row=candidate();row['story']['evidence']=[dict(id='laugh',start=9,end=12,channel='audio',description='Laughter is audible.')]
    story=sd.grounded_story(row,cs.speech_units(source(),30),[dict(audio_context=[dict(start=9,end=12,relative_rms=1)])])
    assert not any(e['channel']=='audio' for e in story['evidence'])


def test_outcome_must_be_retained_near_ending():
    row=candidate();row['story']['beats'][-1]['evidence_ids']=['0']
    story=sd.grounded_story(row,cs.speech_units(source(),30))
    assert not any(r['criterion']=='ending_completeness' for r in story['ratings'])
    assert 'not established' in story['ending_note']


@pytest.mark.parametrize('change',[{'score':101},{'score':True},{'score':float('nan')},{'criterion':'viral_success'}])
def test_invalid_ai_metrics_fall_back_without_promoting_legacy_scores(change):
    row=candidate();row['story']['ratings'][0].update(change);row['story_scores']={'emotional_engagement':100}
    selected=cs.select_story_candidates([row],source(),30)[0]
    assert selected['story_report']['scores']['value'] is None
    assert selected['ranking_report']['metrics']['engagement'] is None


def test_complete_story_outranks_exciting_but_incomplete_candidate():
    complete=candidate(score=90);complete['label']='complete'
    weak=candidate(score=20);weak.update(label='exciting',predicted_score=100)
    result=cs.select_story_candidates([weak,complete],source(),30)
    assert len(result)==1 and result[0]['label']=='complete'


def test_missing_timestamps_do_not_create_a_story():
    with pytest.raises(ValueError,match='No complete timed source story'):
        sd.fallback_highlights({'text':'A story with no timing.'},60,30)


def test_cloud_outage_returns_traceable_contiguous_highlight(monkeypatch):
    monkeypatch.setenv('STORY_MODE','educational')
    result=sd.fallback_highlights(source('educational'),30,30)
    assert result['selection_fallback'] and result['cost_analysis'] is None
    clip=result['shorts'][0];segment=clip['recipe']['segments'][0]
    assert clip['end']==pytest.approx(segment['end']-segment['start'])
    assert clip['story_report']['mode']=='educational'
    assert 'not established' in clip['story_report']['ending_rationale']


def test_fallback_is_deterministic_and_does_not_mutate_source(monkeypatch):
    monkeypatch.setenv('STORY_MODE','podcast');transcript=source('podcast');before=copy.deepcopy(transcript)
    assert sd.fallback_highlights(transcript,30,30)==sd.fallback_highlights(transcript,30,30)
    assert transcript==before


def test_mode_changes_invalidate_selection_cache(pipeline,monkeypatch,tmp_path):
    calls=[]
    def stage(client,model,items,prompt,schema,key,costs,label):
        calls.append(prompt(items))
        return [dict(id=items[0]['id'],score=90)] if label=='score' else [dict(candidate(),start=1,end=27,source_window_id=items[0]['id'])]
    monkeypatch.setattr(pipeline,'_run_stage_split',stage)
    pipeline.get_viral_clips(source(),30,output_dir=tmp_path)
    assert pipeline.get_viral_clips(source(),30,output_dir=tmp_path)['selection_cache_hit']
    monkeypatch.setenv('STORY_MODE','challenge');pipeline.get_viral_clips(source(),30,output_dir=tmp_path)
    assert len(calls)==4 and 'STORY MODE: challenge' in calls[-1]


def test_chapter_offsets_apply_to_evidence_and_scene_cuts(tmp_path,monkeypatch):
    media=tmp_path/'source.mp4';media.write_bytes(b'fixture')
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    calls=[]
    def inspect(*a):
        calls.append(a[1]);row=candidate();row['story']['evidence']=[dict(id='v',start=1,end=8,channel='visual',description='A marked line is visible.')]
        return dict(chapter_summary='Source chapter',moments=[row],scene_cuts=[10,999,-1]),None
    monkeypatch.setattr(sd,'_inspect',inspect)
    first=sd.analyze_source(media,None,210,tmp_path)
    assert first['scene_cuts']==[10,187]
    assert first['moments'][1]['story']['evidence'][0]['start']==178
    assert sd.analyze_source(media,None,210,tmp_path)==first and len(calls)==2
    monkeypatch.setenv('STORY_MODE','comedy');sd.analyze_source(media,None,210,tmp_path)
    assert len(calls)==4


def test_real_audio_envelope_is_measured_without_emotion_labels(tmp_path):
    media=tmp_path/'energy.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1',
        '-f','lavfi','-i','sine=frequency=440:duration=1','-filter_complex',
        '[0:a]volume=0.1[a];[a][1:a]concat=n=2:v=0:a=1[out]','-map','[out]',str(media)],check=True,capture_output=True,timeout=15)
    rows=sd.chapter_audio_context(media,2)
    assert len(rows)==2 and rows[0]['relative_rms']<.2 and rows[1]['relative_rms']>.9
    assert set(rows[0])=={'start','end','relative_rms'}
    assert sd.chapter_audio_context(media,181)==[]


def test_energy_is_optional_and_unknown_mode_falls_back(monkeypatch,tmp_path):
    media=tmp_path/'source';media.touch();monkeypatch.setenv('STORY_AUDIO_ENERGY','0')
    assert sd.chapter_audio_context(media,30)==[]
    monkeypatch.setenv('STORY_MODE','made-up');assert sd.configured_story_mode()=='auto'


def test_freeform_idea_and_ending_cannot_add_unseen_events():
    row=candidate();row['story'].update(idea='A millionaire pays the winner!',ending_note='The runner receives a million dollars.')
    story=sd.grounded_story(row,cs.speech_units(source(),30))
    assert 'million' not in story['idea'] and 'million' not in story['ending_note']
    assert FIXTURES['challenge'][0] in story['idea'] and FIXTURES['challenge'][2] in story['ending_note']


def test_actual_retained_audio_observation_can_be_reused():
    observation=dict(id='laugh',start=9,end=12,channel='audio',description='Laughter is audible.')
    row=candidate();row['story']['evidence'].append(observation)
    context=[dict(story=dict(evidence=[copy.deepcopy(observation)]))]
    story=sd.grounded_story(row,cs.speech_units(source(),30),context)
    assert any(e['channel']=='audio' and e['description']=='Laughter is audible.' for e in story['evidence'])


def test_rescoring_updates_ranks_and_hides_evidence_after_source_edit():
    import clip_ranking
    clip=cs.select_story_candidates([candidate()],source(),30)[0]
    result=clip_ranking.rescore_clips([clip],source())[0]
    assert result['story_report']['rank']==1 and result['story_report']['score']==result['selection_score']
    clip.update(start=9,end=27)
    assert clip_ranking.rescore_clips([clip],source())[0]['story_report']['stale']


@pytest.mark.parametrize('duration',[0,-1,float('nan'),float('inf'),True])
def test_invalid_source_duration_is_rejected_before_media_work(tmp_path,duration):
    with pytest.raises(ValueError,match='duration'):
        sd.analyze_source(tmp_path/'missing.mp4',None,duration,tmp_path)
