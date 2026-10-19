import json
import subprocess

import pytest
import app
from test_export_quality_api import job,request  # noqa: F401 -- shared real media/ASGI fixture
from test_export_quality import real_clip  # noqa: F401


@pytest.fixture
def caption_job(job,monkeypatch):
    data=json.loads(job['meta'].read_text())
    data['transcript']={'language':'en','segments':[{'words':[
        dict(word=' Hello,',start=.1,end=.7),dict(word=' world!',start=.8,end=3)]}]}
    job['meta'].write_text(json.dumps(data))
    monkeypatch.setenv('CAPTION_FACE_PLACEMENT','0')
    # Tiny 64x36 fixtures are below NVENC's minimum supported height.
    monkeypatch.setenv('FFMPEG_ENCODER','x264')
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    return job


def test_caption_transcript_clamps_end_to_real_clip(caption_job):
    response=request('GET','/api/clip/quality-job/0/transcript')
    assert response.status_code==200
    assert response.json()['captions'][-1]['endMs']==2000
    assert 'splitRanges' in response.json()


def test_professional_subtitle_export_and_customizations(caption_job):
    response=request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,
        caption_preset='podcast',font_size=58,max_lines=1,shadow=2,sync_offset_ms=100,
        font_color='#FFFFFF',highlight_color='#FFDD00',bg_opacity=.4))
    assert response.status_code==200,response.text
    assert response.json()['quality_report']['accepted']
    data=json.loads(caption_job['meta'].read_text())
    settings=data['shorts'][0]['caption_settings']
    assert settings['max_lines']==1 and settings['sync_offset_ms']==100
    assert settings['caption_preset']=='podcast'
    assert request('GET','/api/clip/quality-job/0/transcript').json()['captionSettings']['font_size']==58


def test_unknown_preset_and_invalid_limits_are_rejected(caption_job):
    base=dict(job_id='quality-job',clip_index=0)
    assert request('POST','/api/subtitle',json={**base,'caption_preset':'unknown'}).status_code==400
    assert request('POST','/api/subtitle',json={**base,'max_lines':5}).status_code==422
    assert request('POST','/api/subtitle',json={**base,'sync_offset_ms':1001}).status_code==422


def test_edited_missing_alignment_is_not_promoted_to_word_precision(caption_job):
    response=request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,
        caption_preset='dynamic-highlight',words=[dict(text='An edited phrase.',startMs=0,endMs=3000,aligned=False)]))
    assert response.status_code==200,response.text
    ass=next(caption_job['directory'].glob('subs_*.ass')).read_text(encoding='utf-8-sig')
    assert '\\c&H' not in '\n'.join(line for line in ass.splitlines() if line.startswith('Dialogue: 1'))


def test_interrupted_caption_render_cannot_publish_partial_output(caption_job,monkeypatch):
    def interrupted(source,ass,output,**kwargs):
        from pathlib import Path
        Path(output).write_bytes(b'partial')
        raise subprocess.TimeoutExpired('ffmpeg',300)
    monkeypatch.setattr(app,'burn_subtitles',interrupted)
    response=request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,caption_preset='clean-minimal'))
    assert response.status_code==500
    sidecar=next(caption_job['directory'].glob('subtitled_*.quality.json'))
    report=json.loads(sidecar.read_text())
    assert report['status']=='FAIL' and not report['accepted']
