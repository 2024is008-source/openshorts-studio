"""Story selection contracts: source-grounded timing, ranking and outage behavior."""
import copy
import json

import pytest

import clip_selection as cs
import story_director as sd
from generation_options import clip_target_options, RESUME_OPTIONS


def segment(a,b,text,speaker=None):
    tokens=text.split()
    step=(b-a)/len(tokens)
    return dict(start=a,end=b,text=text,speaker=speaker,words=[
        dict(word=t,start=a+i*step,end=a+(i+1)*step) for i,t in enumerate(tokens)])


@pytest.fixture
def transcript():
    return dict(language='en',segments=[
        segment(5,12,'Why did the motor stop?', 'A'),
        segment(13,22,'The boat was taking on water.', 'A'),
        segment(23,31,'We worked together to fix the engine.', 'B'),
        segment(33,42,'The engine started and everyone reached safety.', 'A'),
        segment(53,59,'Everyone cheered when we reached the shore!', 'B')])


def test_interrupted_sentence_extends_to_real_words(transcript):
    units=cs.speech_units(transcript,70)
    a,b=cs.story_boundaries(14,39,units,70)
    assert 12.8<=a<=13 and 42<=b<=42.3
    assert not any(u['start']<a<u['end'] or u['start']<b<u['end'] for u in units)


def test_asr_segment_break_is_not_a_sentence_break():
    t={'segments':[segment(0,8,'We thought the boat'),segment(8.2,18,'would sink but we rescued everyone.')]}
    units=cs.speech_units(t,30)
    assert len(units)==1 and units[0]['end']==18
    assert cs.story_boundaries(6,16,units,30) is None  # too much missing context
    assert cs.story_boundaries(1,16,units,30)==(0,18.25)


def test_long_sentence_is_rejected_instead_of_truncated():
    units=cs.speech_units({'segments':[segment(0,80,'This is one very long unfinished thought.')]},100)
    assert cs.story_boundaries(0,58,units,100,15,60) is None


def test_long_unused_leading_and_trailing_pauses_are_removed(transcript):
    a,b=cs.story_boundaries(0,50,cs.speech_units(transcript,70),70)
    assert a==4.85 and b==42.25


def test_multiple_speakers_and_overlapping_turns_are_preserved():
    t={'segments':[segment(5,15,'Can you explain the result?', 'A'),
                   segment(13,26,'Yes we rescued everyone from the boat.', 'B')]}
    a,b=cs.story_boundaries(6,22,cs.speech_units(t,40),40)
    assert a<=5 and b>=26


def test_payoff_near_end_is_kept_and_visual_reaction_survives(transcript):
    units=cs.speech_units(transcript,70)
    assert cs.story_boundaries(33,55,units,70)[1]>=59
    plain=cs.select_story_candidates([dict(start=33,end=67)],transcript,70)
    visual=cs.select_story_candidates([dict(start=33,end=67,visual_evidence='People cheering on shore')],transcript,70)
    assert plain[0]['end']<60 and visual[0]['end']==67


@pytest.mark.parametrize('a,b',[(None,20),(0,None),(-1,20),(0,80),(20,10),('oops',25),(float('nan'),30),(0,float('inf')),(True,30)])
def test_invalid_ai_timestamps_are_rejected(transcript,a,b):
    assert cs.select_story_candidates([dict(start=a,end=b)],transcript,70)==[]


def test_missing_timestamps_are_not_invented():
    t={'text':'Something interesting happened.', 'segments':[{'text':'Something interesting happened.'},dict(start=0,end=float('nan'),text='broken')]}
    assert cs.speech_units(t,60)==[]
    assert cs.fallback_story_candidates(t,60)==[]
    assert sd.timed_segments(t)==[]
    assert cs.build_transcript_windows(t,60)[0]['text']==t['text']


def test_fallback_extracts_only_real_source_words(transcript):
    rows=cs.fallback_story_candidates(transcript,70)
    assert rows
    source=' '.join(s['text'] for s in transcript['segments'])
    assert all(row['viral_hook_text'] in source and row['predicted_score'] is None for row in rows)
    assert all(row['selection_origin']=='deterministic_transcript_fallback' for row in rows)


def test_ordinary_material_does_not_get_a_viral_claim():
    t={'segments':[segment(0,20,'The room contains a table and a chair.') ]}
    rows=cs.select_story_candidates(cs.fallback_story_candidates(t,30),t,30)
    assert rows and rows[0]['predicted_score'] is None
    report=rows[0]['selection_report']
    assert 'not a view prediction' in report['scoring_method']
    assert report['components']['visual_interest'] is None
    assert report['components']['emotional_engagement'] is None


def test_overlap_and_repeated_openings_are_deduplicated(transcript):
    high={k:95 for k in ('hook_strength','standalone_context','narrative_completeness','pacing','ending_quality')}
    rows=cs.select_story_candidates([dict(start=5,end=42,label='weak'),dict(start=5,end=42,label='strong',story_scores=high)],transcript,70)
    assert len(rows)==1 and rows[0]['label']=='strong'
    assert 'redundancy' in rows[0]['selection_report']
    text='The whole team worked together to save everyone.'
    t={'segments':[segment(0,20,text),segment(40,60,text)]}
    assert len(cs.select_story_candidates([dict(start=0,end=20),dict(start=40,end=60)],t,70))==1


def test_scene_cut_fallback_does_not_move_speech():
    assert cs.story_boundaries(1,22,[],40,15,60,[1.2,21.8])==(1.2,21.8)


@pytest.mark.parametrize('target',[15,30,45,60,37])
def test_duration_targets_are_soft_and_resumable(target,monkeypatch):
    options=clip_target_options(target)
    assert float(options['CLIP_MIN_SECONDS'])<target<float(options['CLIP_MAX_SECONDS'])
    for k,v in options.items(): monkeypatch.setenv(k,v)
    assert cs.clip_duration_bounds()==(target*.75,target*1.2)
    assert set(options)<=RESUME_OPTIONS


@pytest.mark.parametrize('value',['nan','inf',0,151,'bad'])
def test_invalid_targets_rejected(value):
    with pytest.raises(ValueError): clip_target_options(value)


def test_target_honors_explicit_limits():
    assert clip_target_options(30,20,40)['CLIP_MAX_SECONDS']=='40.0'
    with pytest.raises(ValueError): clip_target_options(60,15,30)


def test_analysis_cache_changes_with_transcript(tmp_path,monkeypatch):
    src=tmp_path/'video.mp4';src.write_bytes(b'fixture')
    calls=[]
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    def inspect(*a):
        calls.append(1)
        return dict(chapter_summary='Source chapter',moments=[dict(start=5,end=25,score=60)]),None
    monkeypatch.setattr(sd,'_inspect',inspect)
    sd.analyze_source(src,None,60,tmp_path)
    sd.analyze_source(src,None,60,tmp_path)
    assert len(calls)==1
    sd.analyze_source(src,{'segments':[],'text':'corrected'},60,tmp_path)
    assert len(calls)==2


def test_summary_provider_outage_uses_inspected_ranges_only():
    moments=[dict(id='a',start=0,end=20,score=80,event='Boat in difficulty'),
             dict(id='b',start=40,end=60,score=90,event='Passengers reach shore')]
    def unavailable(*a): raise RuntimeError('unavailable')
    result=sd.plan_summary({'moments':moments},None,90,60,unavailable)
    assert result['selection_fallback']
    assert result['shorts'][0]['recipe']['segments']==[dict(start=0.,end=20.),dict(start=40.,end=60.)]
    assert result['shorts'][0]['viral_hook_text']==''


@pytest.fixture
def pipeline(monkeypatch):
    import main
    monkeypatch.setattr(main.llm_backend,'active',lambda:False)
    monkeypatch.setattr(main,'_gemini_api_keys',lambda:['test-only'])
    for k in ('CLIP_MIN_SECONDS','CLIP_MAX_SECONDS','CLIP_TARGET_SECONDS','CLIP_TARGET_MIN','CLIP_TARGET_MAX','CLIP_STORY_AWARE'):
        monkeypatch.delenv(k,raising=False)
    return main


def test_gemini_errors_use_deterministic_fallback(pipeline,transcript,monkeypatch,tmp_path):
    def fail(*a,**k): raise RuntimeError('provider unavailable')
    monkeypatch.setattr(pipeline,'_run_stage_split',fail)
    result=pipeline.get_viral_clips(transcript,70,output_dir=tmp_path)
    assert result['selection_fallback'] and result['shorts']
    assert not (tmp_path/'clip_selection.json').exists()


def test_pipeline_context_cache_and_invalid_ranges(pipeline,transcript,monkeypatch,tmp_path):
    calls=[]
    visual={'moments':[dict(start=33,end=67,visual_evidence='People cheering on shore')]}
    def stage(client,model,items,prompt,schema,key,costs,label):
        calls.append(prompt(items))
        if label=='score': return [dict(id=items[0]['id'],score=80)]
        return [dict(start=5,end=42,source_window_id=items[0]['id'],predicted_score=50),
                dict(start=float('nan'),end=40,source_window_id=items[0]['id']),
                dict(start=0,end=80,source_window_id=items[0]['id'])]
    monkeypatch.setattr(pipeline,'_run_stage_split',stage)
    first=pipeline.get_viral_clips(transcript,70,visual,tmp_path)
    assert not first['selection_fallback'] and len(first['shorts'])==1
    assert 'People cheering on shore' in calls[0] and 'source_context' in calls[0]
    second=pipeline.get_viral_clips(transcript,70,visual,tmp_path)
    assert second['selection_cache_hit'] and len(calls)==2
    changed=copy.deepcopy(transcript);changed['segments'][0]['text']='Corrected source speech.'
    pipeline.get_viral_clips(changed,70,visual,tmp_path)
    assert len(calls)==4


def test_policy_block_is_not_replaced_by_fallback(pipeline,transcript,monkeypatch):
    import gemini_worker
    def blocked(*a,**k): raise gemini_worker.GeminiBlockedError('blocked')
    monkeypatch.setattr(pipeline,'_run_stage_split',blocked)
    with pytest.raises(gemini_worker.GeminiBlockedError): pipeline.get_viral_clips(transcript,70)


def test_isolated_blocked_window_is_not_reintroduced(pipeline,transcript,monkeypatch):
    import gemini_worker
    def blocked(*a,**k): raise gemini_worker.GeminiBlockedError('blocked')
    monkeypatch.setattr(pipeline,'_run_gemini_stage',blocked)
    assert pipeline.get_viral_clips(transcript,70) is None


def test_opening_assessment_uses_first_three_seconds_only():
    t={'segments':[segment(0,20,'There was a motor problem but how did we solve it?')]}
    result=cs.select_story_candidates([dict(start=0,end=20)],t,25)
    assert '?' not in result[0]['selection_report']['opening_text']
    assert result[0]['selection_report']['components']['hook_strength']==45


def test_exact_whole_source_can_fit_without_padding_it():
    t={'segments':[segment(0,60,'A complete account ending here.')]}
    assert cs.fallback_story_candidates(t,60)[0]['end']==60


def test_invalid_transcript_entries_do_not_discard_good_speech():
    t={'segments':[None,{},dict(start=None,end=20),segment(0,20,'A complete sentence remains available.')]}
    assert len(cs.speech_units(t,30))==1


def test_summary_does_not_hide_a_provider_block():
    import gemini_worker
    def blocked(*a): raise gemini_worker.GeminiBlockedError('blocked')
    with pytest.raises(gemini_worker.GeminiBlockedError):
        sd.plan_summary({'moments':[]},None,90,60,blocked)


def test_legacy_boundary_flag_and_clip_count(pipeline,transcript,monkeypatch):
    monkeypatch.setenv('CLIP_STORY_AWARE','0')
    monkeypatch.setenv('CLIP_TARGET_MAX','1')
    monkeypatch.setenv('CLIP_TARGET_MIN','1')
    monkeypatch.setattr(pipeline,'_gemini_api_keys',lambda:[])
    result=pipeline.get_viral_clips(transcript,70)
    assert len(result['shorts'])==1 and 'selection_report' not in result['shorts'][0]


def test_invalid_scores_spread_shortlist_to_source_end(pipeline,monkeypatch):
    transcript={'segments':[segment(i*20,i*20+18,f'Source sentence number {i} is complete.') for i in range(30)]}
    selected=[]
    def stage(client,model,items,prompt,schema,key,costs,label):
        if label=='score': return []
        selected.extend(items)
        return []
    monkeypatch.setattr(pipeline,'_run_stage_split',stage)
    pipeline.get_viral_clips(transcript,600)
    assert selected and selected[-1]['end']>=590


def test_duplicate_window_ids_do_not_repeat_detail_work(pipeline,transcript,monkeypatch):
    selected=[]
    def stage(client,model,items,prompt,schema,key,costs,label):
        if label=='score': return [dict(id=items[0]['id'],score=80)]*5
        selected.extend(w['id'] for w in items)
        return []
    monkeypatch.setattr(pipeline,'_run_stage_split',stage)
    pipeline.get_viral_clips(transcript,70)
    assert len(selected)==len(set(selected))==1


def test_provider_cost_is_retained_when_detail_falls_back(pipeline,transcript,monkeypatch):
    def stage(client,model,items,prompt,schema,key,costs,label):
        if label=='score':
            costs.append({'total_cost':.01,'input_tokens':10,'output_tokens':2})
            return [dict(id=items[0]['id'],score=80)]
        raise RuntimeError('detail unavailable')
    monkeypatch.setattr(pipeline,'_run_stage_split',stage)
    result=pipeline.get_viral_clips(transcript,70)
    assert result['selection_fallback'] and result['cost_analysis']['total_cost']==.01


def test_gemini_schema_rejects_nan_and_out_of_range_ratings():
    import gemini_worker as gw
    from pydantic import ValidationError
    row=dict(start=0,end=30,source_window_id='w',predicted_score=60,
             video_description_for_tiktok='',video_description_for_instagram='',
             video_title_for_youtube_short='Source title',viral_hook_text='Source quote')
    with pytest.raises(ValidationError): gw.DetailClipModel.model_validate({**row,'start':float('nan')})
    with pytest.raises(ValidationError): gw.DetailClipModel.model_validate({**row,'predicted_score':101})
