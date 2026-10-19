import json
import shutil

import pytest

import app
import export_quality as q
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401


@pytest.fixture
def hook_job(job,real_clip,monkeypatch):
    import caption_renderer
    monkeypatch.setattr(caption_renderer,'detect_face_regions',lambda *_:[])
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    monkeypatch.setenv('FFMPEG_ENCODER','libx264')
    shutil.copyfile(real_clip('portrait',video='color=c=green:s=216x384:r=24:d=2'),job['video'])
    data=json.loads(job['meta'].read_text())
    data['transcript']={'segments':[dict(text='Can we finish?',start=.1,end=1.5)]}
    data['shorts'][0]['quality_expected']=q.expectations(q.probe(job['video']))
    job['meta'].write_text(json.dumps(data))
    return job


def payload(**kwargs):
    return dict(dict(job_id='quality-job',clip_index=0,text='Can we finish?',
        duration_seconds=1.5,animation='scale-pop',start_seconds=.1,position='top'),**kwargs)


def test_suggestions_and_validation_require_source_evidence(hook_job):
    result=request('GET','/api/clip/quality-job/0/hooks').json()
    assert result['suggestion']['text']=='Can we finish?' and result['context']=='Can we finish?'
    assert request('GET','/api/clip/quality-job/0/hooks?kind=funny').json()['suggestion'] is None
    assert request('GET','/api/clip/quality-job/0/hooks?kind=made-up').status_code==422
    assert request('POST','/api/hook/check',json=payload(text='CAN WE\nFINISH?')).status_code==200
    for change in [dict(text='We won a million dollars!'),dict(start_seconds=1),dict(animation='evil'),dict(y=.8)]:
        response=request('POST','/api/hook',json=payload(**change))
        assert response.status_code==422,response.text
    assert not list(hook_job['directory'].glob('hooked_*'))


def test_preview_is_read_only_and_final_export_is_gated(hook_job):
    before=hook_job['meta'].read_bytes();original=hook_job['video'].read_bytes()
    preview=request('POST','/api/hook/preview',json=payload())
    assert preview.status_code==200,preview.text
    assert hook_job['meta'].read_bytes()==before and hook_job['video'].read_bytes()==original
    result=request('POST','/api/hook',json=payload())
    assert result.status_code==200,result.text
    assert result.json()['quality_report']['accepted']
    saved=json.loads(hook_job['meta'].read_text())['shorts'][0]
    assert saved['auto_hook']['animation']=='scale-pop' and saved['auto_hook']['start_seconds']==.1
    assert request('POST','/api/hook',json=payload(remove=True)).json()['burned_hook'] is None
    assert hook_job['video'].read_bytes()==original


def test_replacement_preserves_exact_saved_caption_layer(hook_job,monkeypatch):
    from subtitles import burn_subtitles
    directory=hook_job['directory']
    sidecar=directory/'subs_0_123.ass'
    import caption_renderer
    caption_renderer.generate({'segments':[dict(text='Edited captions!',start=.1,end=1.8)]},0,2,str(sidecar),216,384,'cinematic')
    filename='subtitled_123_example_clip_1.mp4'
    burn_subtitles(str(hook_job['video']),str(sidecar),str(directory/filename))
    data=json.loads(hook_job['meta'].read_text());data['shorts'][0].update(video_url='/videos/quality-job/'+filename,caption_settings={'caption_preset':'cinematic'})
    hook_job['meta'].write_text(json.dumps(data))
    hook_job['record']['result']['clips'][0]['video_url']='/videos/quality-job/'+filename
    content=sidecar.read_bytes()
    monkeypatch.setattr(app,'auto_caption_clip',lambda *a,**k:pytest.fail('Cannot reset caption settings'),raising=False)
    result=request('POST','/api/hook',json=payload(input_filename=filename))
    assert result.status_code==200,result.text
    assert result.json()['new_video_url'].split('/')[-1].startswith('subtitled_')
    assert sidecar.read_bytes()==content
    assert json.loads(hook_job['meta'].read_text())['shorts'][0]['caption_settings']['caption_preset']=='cinematic'
    again=request('POST','/api/hook',json=payload(animation='fade'))
    assert again.status_code==200,again.text
    stamp=again.json()['new_video_url'].split('/')[-1].split('_')[1]
    assert (directory/f'subs_0_{stamp}.ass').read_bytes()==content


def test_missing_context_no_suitable_hook_and_missing_clean_file(hook_job):
    data=json.loads(hook_job['meta'].read_text());data['transcript']={}
    hook_job['meta'].write_text(json.dumps(data))
    assert request('GET','/api/clip/quality-job/0/hooks').json()['suggestion'] is None
    assert request('POST','/api/hook/check',json=payload()).status_code==422
    data['shorts'][0]['auto_hook']={'text':'Legacy headline'}
    hook_job['meta'].write_text(json.dumps(data))
    assert request('POST','/api/hook',json=payload(remove=True)).status_code==409


def test_ownership_stale_and_invalid_clip_requests(hook_job,monkeypatch):
    assert request('POST','/api/hook',json=payload(input_filename='stale.mp4')).status_code==409
    assert request('POST','/api/hook',json=payload(clip_index=-1)).status_code==404
    from types import SimpleNamespace
    hook_job['record']['user_id']='owner';monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET','/api/clip/quality-job/0/hooks').status_code==404
    assert request('POST','/api/hook/check',json=payload()).status_code==404


def test_known_faces_and_top_captions_cannot_be_covered(hook_job,monkeypatch):
    import caption_renderer
    monkeypatch.setattr(caption_renderer,'detect_face_regions',lambda *_:[dict(start=0,end=2,x=0,y=0,width=1,height=.8)])
    assert request('GET','/api/clip/quality-job/0/hooks').json()['suggestion'] is None
    assert request('POST','/api/hook/check',json=payload()).status_code==422


def test_directed_hook_only_clip_does_not_enable_captions_on_edit(hook_job,monkeypatch):
    import editing_director
    data=json.loads(hook_job['meta'].read_text())
    old='subtitled_123_example_clip_1.mp4'
    data['shorts'][0].update(director_delivery_file=old,edit_decision_file='example_clip_1.mp4.edit.json')
    hook_job['meta'].write_text(json.dumps(data))
    (hook_job['directory']/'example_clip_1.mp4.edit.json').write_text('{}')
    monkeypatch.setattr(editing_director,'load',lambda *_:dict(captions_enabled=False,hook={'enabled':True}))
    monkeypatch.setattr(editing_director,'render_layers',lambda *a,**k:pytest.fail('Captions remain disabled'))
    assert app._reapply_captions('quality-job',0,str(hook_job['video']),old)==str(hook_job['video'])
