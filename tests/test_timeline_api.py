import asyncio
import copy
import json
import threading

import httpx
import pytest

import app
import timeline_api
import timeline_project as model
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401

BASE='/api/clip/quality-job/0/editor'


def draft():return request('GET',BASE).json()


def test_save_reopen_and_stale_revision_no_media_changes(job):
    data=draft();project=data['project'];before=job['video'].read_bytes()
    edits=project['edits'];edits['segments']=[{'start':.5,'end':1.5}]
    edits['crop']={'mode':'crop','x':.2,'y':.8}
    response=request('PUT',BASE,json={'revision':0,'edits':edits})
    assert response.status_code==200,response.text
    assert draft()['project']['revision']==1
    assert draft()['project']['edits']==edits
    assert request('PUT',BASE,json={'revision':0,'edits':edits}).status_code==409
    assert job['video'].read_bytes()==before
    assert job['record']['status']=='completed'


def test_workspace_preferences_save_with_revision_and_do_not_affect_edits(job):
    project=draft()['project']
    ui=dict(title='Renamed project',playhead=1.25,preview_ratio='1:1',assets_visible=False,
        inspector_visible=True,segment_index=0,caption_id='0')
    saved=request('PUT',BASE,json=dict(revision=0,edits=project['edits'],ui=ui))
    assert saved.status_code==200,saved.text
    assert draft()['project']['ui']==ui
    assert draft()['project']['edits']==project['edits']
    assert request('PUT',BASE,json=dict(revision=0,edits=project['edits'],ui=ui)).status_code==409
    assert request('PUT',BASE,json=dict(revision=1,edits=project['edits'],ui={'path':'outside'})).status_code==400
    assert draft()['project']['revision']==1


def test_source_change_requires_explicit_reset_and_rejects_paths(job):
    data=draft();edits=data['project']['edits']
    assert request('PUT',BASE,json={'revision':0,'edits':edits}).status_code==200
    metadata=json.loads(job['meta'].read_text());metadata['shorts'][0]['end']=1.5
    job['meta'].write_text(json.dumps(metadata))
    assert draft()['stale']
    assert request('PUT',BASE,json={'revision':1,'edits':edits}).status_code==409
    reset=request('POST',BASE+'/reset',json={'revision':1})
    assert reset.status_code==200 and reset.json()['project']['revision']==2
    assert not draft()['stale']
    edits['path']='../../.env'
    assert request('PUT',BASE,json={'revision':2,'edits':edits}).status_code==400


def test_interrupted_job_and_malformed_project_are_handled(job):
    project=draft()['project'];project.update(status='rendering',run_id='dead')
    path=job['directory']/'editor_project_0.json';path.write_text(json.dumps(project))
    assert draft()['project']['status']=='interrupted'
    path.write_text('{damaged')
    assert request('GET',BASE).status_code==409
    assert job['video'].is_file()


def test_authorization_and_feature_flag(job,monkeypatch):
    from types import SimpleNamespace
    job['record']['user_id']='owner'
    monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET',BASE).status_code==404
    assert request('POST',BASE+'/cancel',json={}).status_code==404
    monkeypatch.setenv('EDITOR_TIMELINE_ENABLED','0')
    assert request('GET',BASE).status_code==404


def test_real_waveform_scenes_are_cached_and_bounded(job):
    result=request('POST',BASE+'/features',json={'revision':0})
    assert result.status_code==200,result.text
    assert 0<len(result.json()['waveform'])<=600
    assert max(result.json()['waveform'])>.05
    assert result.json()['duration']==2
    assert '2 fps' in result.json()['scene_method']
    cache=next(job['directory'].glob('editor_features_*.json'));stamp=cache.stat().st_mtime_ns
    assert request('POST',BASE+'/features',json={'revision':0}).status_code==200
    assert cache.stat().st_mtime_ns==stamp


def test_preview_final_job_and_cancel_are_reopenable(job,monkeypatch):
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            original=job['clip']['video_url']
            for mode in ('preview','final'):
                started=await client.post(BASE+'/run',json={'revision':0,'mode':mode})
                assert started.status_code==200,started.text
                key=('quality-job',0)
                await asyncio.wait_for(timeline_api._active[key]['task'],45)
                result=(await client.get(BASE)).json()['project']
                assert result['status']==('preview_ready' if mode=='preview' else 'completed'),result
                assert result['result']['quality_report']['accepted']
                if mode=='preview':assert job['record']['result']['clips'][0]['video_url']==original
                else: assert job['record']['result']['clips'][0]['video_url']==result['result']['new_video_url']
            assert not (await client.get(BASE)).json()['stale']
            final=(await client.get(BASE)).json()['project']['result']
            assert final['start']==0 and final['end']==2
            metadata=json.loads(job['meta'].read_text())
            assert metadata['shorts'][0]['editor_clean_file'].startswith('recut_')
            assert app._canonical_clip_file(str(job['directory']),'example',0)==final['new_video_url'].split('/')[-1]
            # A later style edit reuses original segment artifacts even after publication.
            changed=copy.deepcopy((await client.get(BASE)).json()['project']['edits'])
            changed['style']['preset']='podcast'
            assert (await client.put(BASE,json={'revision':0,'edits':changed})).status_code==200
            assert (await client.post(BASE+'/run',json={'revision':1,'mode':'final'})).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],45)
            again=(await client.get(BASE)).json()['project']
            assert again['status']=='completed',again
            assert again['result']['cache']['segment_hits']==1
            changed['segments'][0]['start']=.5
            assert (await client.put(BASE,json={'revision':1,'edits':changed})).status_code==200
            assert (await client.post(BASE+'/run',json={'revision':2,'mode':'final'})).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],45)
            trimmed=(await client.get(BASE)).json()['project']
            assert trimmed['status']=='completed' and trimmed['result']['ranking_stale']
            assert trimmed['result']['start']==.5
            assert (await client.post('/api/jobs/quality-job/ranking/rescore',json={})).status_code==200
            assert not job['record']['result']['clips'][0]['ranking_stale']
            assert job['record']['status']=='completed'
            def cancelled(**kwargs):
                kwargs['cancel'].wait(5)
                import timeline_render
                timeline_render.check(kwargs['cancel'])
            monkeypatch.setattr(timeline_api.renderer,'render',cancelled)
            assert (await client.post(BASE+'/run',json={'revision':2,'mode':'preview'})).status_code==200
            blocked=await asyncio.wait_for(client.put(BASE,json={'revision':2,'edits':changed}),2)
            assert blocked.status_code==409
            assert (await client.post(BASE+'/cancel')).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],10)
            assert (await client.get(BASE)).json()['project']['status']=='cancelled'
    asyncio.run(scenario())


def test_failed_export_never_publishes_or_replaces_existing_video(job,monkeypatch):
    async def fail(*a,**k):raise app.HTTPException(422,'Export failed technical validation.')
    monkeypatch.setattr(app,'_validate_clip_export',fail)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            before=job['record']['result']['clips'][0]['video_url']
            assert (await client.post(BASE+'/run',json={'revision':0,'mode':'final'})).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],30)
            assert (await client.get(BASE)).json()['project']['status']=='failed'
            assert job['record']['result']['clips'][0]['video_url']==before
            assert not list(job['directory'].glob('recut_*'))
    asyncio.run(scenario())


def test_shutdown_cancels_editor_work_and_missing_dependencies_are_clear(job,monkeypatch):
    import subprocess
    monkeypatch.setattr(timeline_api.quality,'probe',lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError('ffprobe')))
    response=request('POST',BASE+'/run',json={'revision':0,'mode':'preview'})
    assert response.status_code==503 and 'FFprobe' in response.json()['detail']
    async def lifecycle():
        stopped=asyncio.Event();cancel=threading.Event()
        async def waiting():
            while not cancel.is_set():await asyncio.sleep(.01)
            stopped.set()
        task=asyncio.create_task(waiting());key=('shutdown-test',0)
        async with timeline_api.router(app).lifespan_context(app.app):
            timeline_api._active[key]=dict(cancel=cancel,task=task)
        assert stopped.is_set() and task.done()
        timeline_api._active.pop(key,None)
    asyncio.run(lifecycle())


def test_existing_subtitle_modal_reads_saved_timeline_corrections(job,monkeypatch):
    import caption_renderer
    monkeypatch.setattr(caption_renderer,'detect_face_regions',lambda *a:[])
    data=json.loads(job['meta'].read_text())
    data['transcript']=dict(language='en',segments=[dict(start=0,end=2,text='Original phrase.')])
    data['shorts'][0].update(editor_caption_source_digest=model.digest(data['transcript']),
        editor_caption_overrides={'0':dict(start=.2,end=1.5,text='Corrected phrase.')})
    job['meta'].write_text(json.dumps(data))
    result=request('GET','/api/clip/quality-job/0/transcript')
    assert result.status_code==200,result.text
    caption=result.json()['captions'][0]
    assert caption==dict(text='Corrected phrase.',startMs=200,endMs=1500,aligned=False)


def test_duplicate_is_independent_and_shares_media_without_copy(job):
    original=draft()['project'];edits=original['edits'];edits['segments']=[dict(start=.25,end=1.75)]
    edits['style']['preset']='podcast'
    assert request('PUT',BASE,json=dict(revision=0,edits=edits)).status_code==200
    before={p.name:p.stat().st_size for p in job['directory'].glob('*.mp4')}
    copied=request('POST',BASE+'/duplicate',json=dict(revision=1))
    assert copied.status_code==200,copied.text
    index=copied.json()['clip_index'];assert index==1
    clone_route='/api/clip/quality-job/1/editor'
    clone=request('GET',clone_route).json()
    assert not clone['stale'] and clone['project']['revision']==0
    assert clone['project']['edits']==edits
    changed=clone['project']['edits'];changed['style']['preset']='cinematic'
    assert request('PUT',clone_route,json=dict(revision=0,edits=changed)).status_code==200
    assert draft()['project']['edits']['style']['preset']=='podcast'
    assert before=={p.name:p.stat().st_size for p in job['directory'].glob('*.mp4')}
    assert len(job['record']['result']['clips'])==2
    assert job['record']['result']['clips'][0]['video_url']==job['record']['result']['clips'][1]['video_url']
    assert request('POST',BASE+'/duplicate',json=dict(revision=0)).status_code==409


def test_duplicate_rejects_busy_project_and_preserves_all_existing_records(job):
    job['record']['status']='processing'
    response=request('POST',BASE+'/duplicate',json=dict(revision=0))
    assert response.status_code==409
    assert len(json.loads(job['meta'].read_text())['shorts'])==1


def test_duplicate_without_source_keeps_shared_clean_artifact(job,monkeypatch):
    monkeypatch.setattr(app,'_locate_source',lambda _:None)
    copied=request('POST',BASE+'/duplicate',json=dict(revision=0))
    assert copied.status_code==200,copied.text
    clone=request('GET','/api/clip/quality-job/1/editor').json()
    assert not clone['source_available'] and not clone['stale']
    data=json.loads(job['meta'].read_text())
    assert data['shorts'][1]['editor_clean_file']==job['video'].name
    assert data['shorts'][0].get('editor_clean_file') is None
