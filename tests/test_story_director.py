import asyncio
import json
from pathlib import Path
import subprocess

import pytest

import story_director as sd
from generation_options import normalize_options
import clean_captions
import recut


def moments():
    return [dict(id='a',start=0,end=10,chapter=0,score=70),
            dict(id='b',start=60,end=80,chapter=1,score=80),
            dict(id='c',start=120,end=140,chapter=2,score=90)]


def test_summary_chronological_and_bounded():
    parts=sd.summary_segments({'moment_ids':['c','a','b']},moments(),60,150)
    assert parts == [{'start':0.,'end':10.},{'start':60.,'end':80.},{'start':120.,'end':140.}]
    assert recut.total_duration(parts)==50


@pytest.mark.parametrize('ids', [['a','a'],['a','unknown'],['a'],['a','b','c']])
def test_invalid_summary_is_rejected_not_silently_trimmed(ids):
    with pytest.raises(ValueError): sd.summary_segments({'moment_ids':ids},moments(),30,150)


def test_overlapping_summary_rejected():
    ms=[dict(id='a',start=0,end=20,chapter=0),dict(id='b',start=15,end=30,chapter=1)]
    with pytest.raises(ValueError,match='overlapping'):
        sd.summary_segments({'moment_ids':['a','b']},ms,60,90)


def test_selection_rejects_bad_times_and_deduplicates():
    rows=[dict(start=0,end=20,score=70),dict(start=1,end=21,score=90),
          dict(start=float('nan'),end=10),dict(start=60,end=500),dict(start=50,end=51)]
    assert sd.validate_moments(rows,100)==[dict(start=1.,end=21.,score=90,predicted_score=90)]


def test_prompt_timing_is_source_grounded():
    transcript={'segments':[dict(start=50,end=60,text='a complete thought'),dict(start=80,end=90,text='payoff')]}
    assert sd.timed_segments(transcript,45,70,45)==[dict(id='s0',start=5,end=15,text='a complete thought')]


@pytest.mark.parametrize('value',['nan','inf',0,181,'oops'])
def test_summary_duration_validation(value):
    with pytest.raises(ValueError): normalize_options(seconds=value)


def test_highlights_always_requests_full_visual_analysis():
    assert normalize_options(mode='highlights',analysis='transcript')['ANALYSIS_MODE']=='hybrid'


def test_summary_plan_retries_invalid_ids_without_fabricating_timestamps():
    calls=[]
    def ask(prompt,schema):
        calls.append(prompt)
        return {'moment_ids':['missing','a'] if len(calls)==1 else ['a','b','c'],
                'story_summary':'setup, development, payoff'},None
    result=sd.plan_summary({'moments':moments()},None,150,60,ask)
    assert len(calls)==2 and result['shorts'][0]['recipe']['source_montage']
    assert result['shorts'][0]['duration']==50


def test_summary_plan_repairs_provider_plan_that_exceeds_budget():
    ms = [dict(id='a', start=0, end=25, chapter=0, score=90),
          dict(id='b', start=50, end=75, chapter=1, score=88),
          dict(id='c', start=100, end=125, chapter=2, score=86)]
    calls = []
    def ask(prompt, schema):
        calls.append(prompt)
        if len(calls) == 3:
            assert 'exactly these moment_ids' in prompt
            return {'moment_ids': ['a', 'b'],
                    'story_summary': 'revised to match the retained moments'}, None
        return {'moment_ids': ['a', 'b', 'c'],
                'story_summary': 'stale story copy'}, None
    result = sd.plan_summary({'moments': ms}, None, 150, 60, ask)
    clip = result['shorts'][0]
    assert len(calls) == 3
    assert clip['duration'] <= 60
    assert len(clip['recipe']['segments']) >= 2
    assert clip['duration'] >= 20
    assert clip['story_summary'] == 'revised to match the retained moments'


def test_planner_receives_spoken_context_and_never_keeps_stale_copy():
    ms = [dict(id='a', start=0, end=25, chapter=0, score=90,
               event='boat sinking'),
          dict(id='b', start=50, end=75, chapter=1, score=80,
               event='boat rescued'),
          dict(id='c', start=100, end=125, chapter=2, score=70,
               event='other activity')]
    transcript = {'segments': [dict(start=1, end=8, text='The boat started to sink.'),
                               dict(start=51, end=58, text='We rescued everyone.')],
                  'language': 'en'}
    prompts = []
    def ask(prompt, schema):
        prompts.append(prompt)
        return {'moment_ids': ['a', 'b', 'c'],
                'story_summary': 'stale three-scene story'}, None
    result = sd.plan_summary({'moments': ms}, transcript, 150, 60, ask)
    assert 'The boat started to sink.' in prompts[0]
    assert result['shorts'][0]['story_summary'] != 'stale three-scene story'


def test_speech_edges_extend_to_complete_nearby_segments():
    transcript = {'segments': [dict(start=10, end=18,
                                    text='The boat was sinking.'),
                               dict(start=20, end=29,
                                    text='Right if I hit this it falls.') ]}
    assert sd._complete_speech_edges(12, 25, transcript, 100) == (10, 29)


def test_clean_captions_have_explicit_geometry_and_escape_input(tmp_path):
    transcript={'segments':[{'words':[dict(word=' Hello',start=0,end=.5),
                                   dict(word=' {world}',start=.5,end=1.0)]}]}
    p=tmp_path/'captions.ass'
    assert clean_captions.generate(transcript,0,2,p,1080,1920)
    text=p.read_text(encoding='utf-8-sig')
    assert 'PlayResX: 1080' in text and 'PlayResY: 1920' in text
    assert 'Arial,64' in text and '(WORLD)' in text and '{WORLD}' not in text


def test_summary_transcript_remap_keeps_speech_sync():
    transcript={'segments':[{'words':[dict(word=' setup',start=2,end=3),
                                    dict(word=' payoff',start=65,end=66)]}]}
    mapped=recut.virtual_transcript(transcript,[dict(start=0,end=10),dict(start=60,end=80)])
    assert mapped['segments'][1]['words'][0]['start']==15


def test_full_source_analysis_offsets_and_cache(tmp_path,monkeypatch):
    src=tmp_path/'input.mp4';src.write_bytes(b'test source')
    calls=[]
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k: None)
    def inspect(*args):
        calls.append(1)
        return {'chapter_summary':'A chapter','moments':[dict(start=5,end=15,score=80,
            editing_cues=[dict(kind='explanation',start=6,end=9,evidence='Observed demonstration.',quote='',confidence=.9)])]},None
    monkeypatch.setattr(sd,'_inspect',inspect)
    first=sd.analyze_source(src,None,360,tmp_path)
    assert [m['start'] for m in first['moments']]==[5,182]
    assert [m['editing_cues'][0]['start'] for m in first['moments']]==[6,183]
    # Last 6s chapter's invalid 5..15s suggestion is rejected, not clamped into a fake moment.
    assert len(calls)==3
    second=sd.analyze_source(src,None,360,tmp_path)
    assert len(calls)==3 and first==second


def test_visual_failure_never_claims_complete_analysis(tmp_path,monkeypatch):
    src=tmp_path/'input.mp4';src.write_bytes(b'test')
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k: None)
    monkeypatch.setattr(sd,'_inspect',lambda *a: (_ for _ in ()).throw(RuntimeError('provider failed')))
    with pytest.raises(RuntimeError): sd.analyze_source(src,None,100,tmp_path)


def test_failed_chapter_does_not_discard_successful_checkpoint(tmp_path,monkeypatch):
    src=tmp_path/'input.mp4';src.write_bytes(b'test')
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    monkeypatch.setattr(sd,'chapter_audio_context',lambda *a:[])
    chapter={'chapter_summary':'Observed.','moments':[dict(start=5,end=15,score=80)]}
    calls=[]
    def inspect(*args):
        calls.append(1)
        if len(calls)==2:raise sd.AnalysisResponseError('invalid JSON',20)
        return chapter,None
    monkeypatch.setattr(sd,'_inspect',inspect)
    monkeypatch.setattr(sd,'_inspect_chapter',lambda proxy,prompt,model,*args:inspect(proxy,prompt,model))
    with pytest.raises(sd.AnalysisResponseError):sd.analyze_source(src,None,240,tmp_path)
    cache=json.loads((tmp_path/'story_analysis.json').read_text())
    assert len(cache['chapters'])==1
    failure=json.loads((tmp_path/'analysis_failure.json').read_text())
    assert failure['chapter']==2 and failure['completed_chapters']==1
    assert failure['source_range']==[177,240]
    result=sd.analyze_source(src,None,240,tmp_path)
    assert len(calls)==3 and [m['start'] for m in result['moments']]==[5,182]


def test_key_priority_and_api_accepts_numbered_keys(monkeypatch):
    import app
    for n in ['GEMINI_API_KEY','GEMINI_API_KEY_1','GEMINI_API_KEY_2']:monkeypatch.delenv(n,raising=False)
    monkeypatch.setenv('GEMINI_API_KEY_1','test-key-one')
    class Request: headers={}
    assert asyncio.run(app.resolve_gemini(Request()))=='test-key-one'


def test_filtered_clip_keeps_identity(tmp_path):
    import app
    (tmp_path/'test_clip_2.mp4').write_bytes(b'file')
    kept,_=app._clips_actually_rendered('test',str(tmp_path),'test',[{'title':'first'},{'title':'second'}])
    assert kept[0]['clip_index']==1
    assert app._memory_clip({'result':{'clips':kept}},1)['title']=='second'
    assert not app._has_memory_clip({'result':{'clips':kept}},0)


def test_restart_does_not_complete_metadata_only_job(tmp_path,monkeypatch):
    import app
    p=tmp_path/'job';p.mkdir()
    (p/'test_metadata.json').write_text(json.dumps({'shorts':[dict(start=0,end=10)]}))
    monkeypatch.setattr(app,'OUTPUT_DIR',str(tmp_path));monkeypatch.setattr(app,'jobs',{})
    app._recover_jobs_from_disk()
    assert app.jobs=={}


def test_restart_keeps_in_progress_job_even_with_one_render(tmp_path,monkeypatch):
    import app
    p=tmp_path/'job';p.mkdir()
    (p/'test_metadata.json').write_text(json.dumps({'pipeline_state':'rendering','shorts':[dict(start=0,end=10)]}))
    (p/'test_clip_1.mp4').write_bytes(b'file')
    monkeypatch.setattr(app,'OUTPUT_DIR',str(tmp_path));monkeypatch.setattr(app,'jobs',{})
    app._recover_jobs_from_disk()
    assert app.jobs=={}


def test_request_options_saved_for_recovery(tmp_path,monkeypatch):
    import app
    (tmp_path/'job').mkdir();monkeypatch.setattr(app,'OUTPUT_DIR',str(tmp_path))
    opts=normalize_options(mode='highlights',captions='clean',quality='studio')
    app._write_resume_manifest('job',['python','main.py'],2,None,None,False,job_options=opts)
    saved=json.loads((tmp_path/'job'/app._RESUME_FILE).read_text())
    assert saved['job_options']==opts
