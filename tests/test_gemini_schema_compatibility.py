"""Exercise the installed SDK conversion that mocked provider calls bypass."""
import pytest
from google.genai import _transformers
from pydantic import ValidationError

import gemini_worker as worker
import story_director as director


@pytest.mark.parametrize('schema',[
    director._schema(), director.summary_schema(), director.story_schema(),
    worker.DetailResponse, worker.VisualResponse, worker.ScoreResponse, worker.GroundedHook,
])
def test_provider_schemas_convert_through_real_installed_google_sdk(schema):
    # This is the SDK's actual Pydantic -> types.Schema conversion, without a
    # client, credentials or network request. Config construction alone misses it.
    converted=_transformers.t_schema(None,schema)
    assert converted is not None and converted.properties


@pytest.mark.parametrize('end',[0,-1,float('nan'),float('inf')])
def test_evidence_still_rejects_invalid_end_timestamps(end):
    value=dict(evidence=[dict(id='test',start=0,end=end,channel='visual',description='A visible source action.')])
    with pytest.raises(ValidationError):director.story_schema().model_validate(value)


@pytest.mark.parametrize('end',[0,-1,float('nan'),float('inf')])
def test_detail_still_rejects_invalid_end_timestamps(end):
    value=dict(start=0,end=end,source_window_id='w0',predicted_score=50,
        video_description_for_tiktok='',video_description_for_instagram='',
        video_title_for_youtube_short='',viral_hook_text='')
    with pytest.raises(ValidationError):worker.DetailClipModel.model_validate(value)


def test_compatible_schemas_preserve_positive_timestamp_precision():
    evidence=director.story_schema().model_validate(dict(evidence=[
        dict(id='test',start=0,end=.001,channel='visual',description='Source action.')]))
    assert evidence.evidence[0].end==.001


@pytest.mark.parametrize('end',[0,-1,float('nan'),float('inf'),.5])
def test_editing_cue_schema_remains_sdk_compatible_and_locally_strict(end):
    schema=director._schema()
    _transformers.t_schema(None,schema)
    value=dict(chapter_summary='Observed.',moments=[dict(start=0,end=2,score=50,role='setup',
        event='Source action.',visual_evidence='Visible subject.',video_title_for_youtube_short='',
        viral_hook_text='',video_description_for_tiktok='',video_description_for_instagram='',
        editing_cues=[dict(kind='explanation',start=.5,end=end,evidence='A visible demonstration.',confidence=.9)])])
    with pytest.raises(ValidationError):schema.model_validate(value)
