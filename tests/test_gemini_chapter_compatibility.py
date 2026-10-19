"""No-network chapter retry contract, keeping local schema validation strict."""
import json
from types import SimpleNamespace as NS

from google.genai.errors import ClientError
import pytest
import story_director as sd


def invalid():
    return ClientError(400,{'error':{'code':400,'status':'INVALID_ARGUMENT',
                                  'message':'Request contains an invalid argument.'}})


@pytest.fixture
def provider(monkeypatch):
    from google import genai
    import gemini_worker
    calls=[];uploaded=[];deleted=[];closed=[];answers=[]
    active=NS(name='files/local-fixture',state=NS(name='ACTIVE'))
    def generate(**kwargs):
        calls.append(kwargs)
        value=answers.pop(0)
        if isinstance(value,Exception):raise value
        if isinstance(value,NS):return value
        return NS(parsed=None,text=json.dumps(value))
    def upload(**kwargs):uploaded.append(kwargs);return active
    client=NS(files=NS(upload=upload,get=lambda **kw:active,
                       delete=lambda **kw:deleted.append(kw)),
              models=NS(generate_content=generate),close=lambda:closed.append(True))
    monkeypatch.setattr(sd,'api_keys',lambda:['test-only-placeholder'])
    monkeypatch.setattr(genai,'Client',lambda **kw:client)
    monkeypatch.setattr(gemini_worker,'raise_if_blocked',lambda response:None)
    monkeypatch.setattr(gemini_worker,'_calculate_cost_analysis',lambda *a:None)
    return NS(calls=calls,uploaded=uploaded,deleted=deleted,closed=closed,answers=answers)


def test_invalid_structured_request_reuses_upload_and_locally_validates(provider):
    provider.answers[:]=[invalid(),dict(chapter_summary='Observed scene.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Use verified footage.','fixture-model')
    assert result['moments']==[]
    assert len(provider.calls)==2 and len(provider.uploaded)==1
    assert provider.calls[0]['config'].response_schema is not None
    assert provider.calls[1]['config'].response_schema is None
    assert provider.calls[1]['config'].response_mime_type=='application/json'
    assert 'Use verified footage.' in provider.calls[1]['contents'][1]
    assert 'Return one JSON object matching this schema' in provider.calls[1]['contents'][1]
    assert len(provider.deleted)==len(provider.closed)==1


def test_repeated_invalid_argument_does_not_loop_or_reupload(provider):
    provider.answers[:]=[invalid(),invalid()]
    with pytest.raises(ClientError):sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert len(provider.calls)==2 and len(provider.uploaded)==1
    assert len(provider.deleted)==len(provider.closed)==1


def test_json_compatibility_does_not_accept_invalid_timestamps(provider):
    moment=dict(start=0,end=1,score=50,role='setup',event='Observed.',visual_evidence='Visible.',
        video_title_for_youtube_short='',viral_hook_text='',video_description_for_tiktok='',
        video_description_for_instagram='',story=dict(evidence=[dict(id='e1',start=0,end=0,channel='visual')]))
    provider.answers[:]=[invalid(),dict(chapter_summary='Observed.',moments=[moment]),dict(chapter_summary='Observed.',moments=[moment])]
    with pytest.raises(ValueError):sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert len(provider.calls)==3 and len(provider.deleted)==1


def test_validation_failure_retries_with_field_feedback(provider):
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[],scene_observations=[dict(
        start=0,end=2,shot_type='group',event='Observed action',layout_intent='single_subject',
        layout_evidence='Visible presenter',confidence=9)]),dict(chapter_summary='Observed.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==2 and len(provider.uploaded)==1
    feedback=provider.calls[1]['contents'][1]
    assert 'scene_observations.0.confidence' in feedback and 'less_than_equal' in feedback


@pytest.mark.parametrize('label',['talking_head','medium shot','two_people','split-screen','', 'UNKNOWN PROVIDER LABEL'])
def test_unrecognized_shot_labels_do_not_fail_chapter_or_invent_layout(provider,label):
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[],scene_observations=[dict(
        start=0,end=2,shot_type=label,event='Observed presenter',layout_intent=label,
        layout_evidence='A person is visible',confidence=.9)])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert len(provider.calls)==1 and len(result['scene_observations'])==1
    shot=result['scene_observations'][0]
    assert shot['shot_type']=='unknown' and shot['layout_intent']=='uncertain'
    import editing_director as director
    assert director.scene_layout_policy({'analysis':result},0,48,24)[0]=='uncertain'


def test_absent_classification_defaults_are_conservative():
    result=sd._schema().model_validate(dict(chapter_summary='Observed.',moments=[],
        scene_observations=[dict(start=0,end=2,event='Observed action',confidence=.8)]))
    assert result.scene_observations[0].shot_type=='unknown'
    assert result.scene_observations[0].layout_intent=='uncertain'


@pytest.mark.parametrize('value',[[],{},42])
def test_nontext_classifications_are_still_rejected(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):sd._schema().model_validate(dict(chapter_summary='Observed.',moments=[],
        scene_observations=[dict(start=0,end=2,event='Observed action',confidence=.8,shot_type=value)]))


def test_missing_layout_explanation_preserves_chapter_without_inventing_evidence(provider):
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[],scene_observations=[dict(
        start=0,end=2,shot_type='group',event='Two people share a counter',
        layout_intent='two_speaker_split',confidence=.9)])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert len(provider.calls)==1
    assert result['scene_observations'][0]['layout_evidence']==''
    import editing_director as director
    assert director.scene_layout_policy({'analysis':result},0,48,24)[0]=='uncertain'


def test_exhausted_validation_stays_strict_without_leaking_inputs(provider):
    bad=dict(chapter_summary='Observed.',moments=[],scene_observations=[dict(start=4,end=2,
        shot_type='group',event='private source text',layout_intent='preserve_scene',
        layout_evidence='Visible group',confidence=.9)])
    provider.answers[:]=[bad,bad]
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as error:sd._inspect('chapter.mp4','Observe.','fixture-model')
    report=sd.analysis_failure(error.value)
    assert report['issues'][0]['field']=='scene_observations.0'
    assert 'private source text' not in json.dumps(report)
    assert len(provider.calls)==2 and len(provider.uploaded)==1 and len(provider.deleted)==1


def test_auth_failure_does_not_trigger_json_schema_retry(provider):
    provider.answers[:]=[ClientError(401,{'error':{'code':401,'message':'Unauthorized','status':'UNAUTHENTICATED'}})]
    with pytest.raises(ClientError):sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert len(provider.calls)==1 and len(provider.deleted)==1


def test_quota_rotates_to_second_key_without_retrying_first(provider,monkeypatch):
    monkeypatch.setattr(sd,'api_keys',lambda:['first-test-key','second-test-key'])
    slept=[];monkeypatch.setattr(sd.time,'sleep',lambda n:slept.append(n))
    provider.answers[:]=[ClientError(429,{'error':{'code':429,'message':'Quota exhausted','status':'RESOURCE_EXHAUSTED'}}),dict(chapter_summary='Observed scene.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==2 and len(provider.uploaded)==2 and not slept


def test_bounded_failover_can_reach_eighth_key(provider,monkeypatch):
    monkeypatch.setattr(sd,'api_keys',lambda:[f'test-key-{i}' for i in range(8)])
    monkeypatch.setattr(sd.time,'sleep',lambda n:pytest.fail('Quota failures should move to next slot'))
    quota=ClientError(429,{'error':{'code':429,'message':'Quota exhausted','status':'RESOURCE_EXHAUSTED'}})
    provider.answers[:]=[quota]*7+[dict(chapter_summary='Observed.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==8
    assert len(provider.uploaded)==len(provider.deleted)==len(provider.closed)==8


@pytest.mark.parametrize('text',['', '{"chapter_summary":"cut off', 'not JSON'])
def test_invalid_response_retries_same_upload_once(provider,text):
    provider.answers[:]=[NS(parsed=None,text=text),dict(chapter_summary='Observed.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['chapter_summary']=='Observed.'
    assert len(provider.calls)==2 and len(provider.uploaded)==1
    assert '24 relevant shot observations' in provider.calls[1]['contents'][1]
    assert provider.calls[1]['config'].max_output_tokens==32768
    assert len(provider.deleted)==len(provider.closed)==1


def test_schema_compatibility_then_malformed_response_can_recover(provider):
    provider.answers[:]=[invalid(),NS(parsed=None,text='{"moments":['),
                        dict(chapter_summary='Observed.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==3 and len(provider.uploaded)==1
    assert provider.calls[-1]['config'].response_schema is None


def test_sdk_json_decode_error_can_recover(provider):
    provider.answers[:]=[json.JSONDecodeError('Invalid response','',0),
                        dict(chapter_summary='Observed.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==2 and len(provider.uploaded)==1


def test_truncated_parsed_object_is_not_accepted(provider):
    partial=dict(chapter_summary='Partial.',moments=[])
    provider.answers[:]=[NS(parsed=partial,text=json.dumps(partial),
        candidates=[NS(finish_reason=NS(name='MAX_TOKENS'))]),
        dict(chapter_summary='Complete.',moments=[])]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['chapter_summary']=='Complete.' and len(provider.calls)==2


def test_complete_fenced_json_needs_no_extra_request(provider):
    provider.answers[:]=[NS(parsed=None,text='\ufeff```json\n{"chapter_summary":"Observed.","moments":[]}\n```')]
    result,_=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert result['moments']==[] and len(provider.calls)==1


def test_repeated_invalid_response_is_bounded_and_safe(provider):
    provider.answers[:]=[NS(parsed=None,text='private malformed response')]*2
    with pytest.raises(sd.AnalysisResponseError) as error:
        sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert 'private' not in str(error.value)
    assert len(provider.calls)==2 and len(provider.uploaded)==1
    assert len(provider.deleted)==len(provider.closed)==1


def test_retry_cost_includes_failed_response(provider,monkeypatch):
    import gemini_worker
    monkeypatch.setattr(gemini_worker,'_calculate_cost_analysis',lambda *a:
        dict(model='fixture-model',total_cost=.01,input_tokens=100,output_tokens=20))
    provider.answers[:]=[NS(parsed=None,text='bad'),dict(chapter_summary='Observed.',moments=[])]
    _,cost=sd._inspect('chapter.mp4','Observe.','fixture-model')
    assert cost['total_cost']==pytest.approx(.02)
    assert cost['input_tokens']==200 and cost['output_tokens']==40


def test_trailing_junk_is_not_accepted_as_scene_evidence():
    with pytest.raises(sd.AnalysisResponseError):
        sd._analysis_response(NS(parsed=None,text='{"chapter_summary":"Observed.","moments":[]} garbage'),sd._schema())
