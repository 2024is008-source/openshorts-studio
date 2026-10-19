"""No-provider tests for recovery of an invalid long-chapter response."""
import json
import pytest
import story_director as sd


def result():
    return dict(chapter_summary='Observed.',scene_cuts=[1],moments=[dict(start=2,end=8,score=80,
        role='setup',event='Observed action',visual_evidence='Visible action',
        video_title_for_youtube_short='',viral_hook_text='',video_description_for_tiktok='',
        video_description_for_instagram='',story=dict(evidence=[dict(id='speech',start=3,end=4,
            channel='transcript',description='Source speech',quote='Hello')]))],
        scene_observations=[dict(start=2,end=8,shot_type='group',event='Observed action',
            layout_intent='preserve_scene',layout_evidence='Shared action',preserve_context=True,
            confidence=.9,editing_cues=[dict(kind='action',start=3,end=4,evidence='Visible movement',quote='',confidence=.9)])])


def test_failed_long_response_recovers_sections_and_maps_all_timestamps(tmp_path,monkeypatch):
    calls=[];commands=[]
    monkeypatch.setattr(sd.subprocess,'run',lambda cmd,**kw:commands.append(cmd))
    def inspect(proxy,prompt,model):
        calls.append((str(proxy),prompt))
        if len(calls)==1:raise sd.AnalysisResponseError('invalid JSON',4000)
        return sd._schema().model_validate(result()).model_dump(),dict(total_cost=.01)
    monkeypatch.setattr(sd,'_inspect',inspect)
    merged,cost=sd._inspect_chapter(tmp_path/'chapter.mp4','Source chapter','model',144,
        tmp_path/'sections.json','source-key')
    assert len(calls)==4 and len(commands)==3
    assert [m['start'] for m in merged['moments']]==[2,62,122]
    assert [m['story']['evidence'][0]['start'] for m in merged['moments']]==[3,63,123]
    assert [s['editing_cues'][0]['start'] for s in merged['scene_observations']]==[3,63,123]
    assert merged['scene_cuts']==[1,61,121]
    assert cost['total_cost']==pytest.approx(.03)
    assert '0..24' in calls[-1][1] and 'minus 120' in calls[-1][1]
    assert len(json.loads((tmp_path/'sections.json').read_text())['sections'])==3


def test_resume_sections_never_repeats_successful_requests(tmp_path,monkeypatch):
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    calls=[]
    def inspect(proxy,*args):
        calls.append(str(proxy))
        if len(calls) in (1,3):raise sd.AnalysisResponseError('invalid JSON')
        return sd._schema().model_validate(result()).model_dump(),None
    monkeypatch.setattr(sd,'_inspect',inspect)
    args=(tmp_path/'chapter.mp4','Observe.','model',144,tmp_path/'sections.json','key')
    with pytest.raises(sd.AnalysisResponseError):sd._inspect_chapter(*args)
    assert len(json.loads((tmp_path/'sections.json').read_text())['sections'])==1
    merged,_=sd._inspect_chapter(*args)
    assert len(calls)==5 and sum(p.endswith('chapter.mp4') for p in calls)==1
    assert sum(p.endswith('section-1.mp4') for p in calls)==1
    assert len(merged['moments'])==3


def test_short_response_does_not_split_or_loop(tmp_path,monkeypatch):
    calls=[]
    def inspect(*args):
        calls.append(1);raise sd.AnalysisResponseError('invalid JSON')
    monkeypatch.setattr(sd,'_inspect',inspect)
    with pytest.raises(sd.AnalysisResponseError):sd._inspect_chapter(tmp_path/'chapter.mp4','Observe.','model',30,tmp_path/'s.json','key')
    assert len(calls)==1


def test_auth_or_transport_errors_do_not_trigger_extra_media_requests(tmp_path,monkeypatch):
    def inspect(*args):raise RuntimeError('Authentication failed')
    monkeypatch.setattr(sd,'_inspect',inspect)
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:pytest.fail('Must not split on service failure'))
    with pytest.raises(RuntimeError):sd._inspect_chapter(tmp_path/'chapter.mp4','Observe.','model',180,tmp_path/'s.json','key')


def test_section_out_of_bounds_observations_are_not_clamped_into_evidence(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    def inspect(*args):
        calls.append(1)
        if len(calls)==1:raise sd.AnalysisResponseError('invalid JSON')
        value=result();value['scene_observations'][0]['end']=70
        return value,None
    monkeypatch.setattr(sd,'_inspect',inspect)
    merged,_=sd._inspect_chapter(tmp_path/'c.mp4','Observe.','model',120,tmp_path/'s.json','key')
    assert merged['scene_observations']==[]
    assert len(merged['moments'])==2
