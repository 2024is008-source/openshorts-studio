import asyncio
import io
import json
import shutil

import httpx
import pytest

import app
import export_quality as q
from test_export_quality import real_clip  # noqa: F401 -- shared real-media fixture


def request(method,path,**kwargs):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            return await client.request(method,path,**kwargs)
    return asyncio.run(go())


@pytest.fixture
def job(tmp_path,monkeypatch,real_clip):
    output=tmp_path/'output';directory=output/'quality-job';directory.mkdir(parents=True)
    uploads=tmp_path/'uploads';uploads.mkdir()
    video=directory/'example_clip_1.mp4';shutil.copy(real_clip(),video)
    clip=dict(start=0,end=2,clip_id='clip_1',video_url='/videos/quality-job/example_clip_1.mp4',
              quality_expected=q.expectations(q.probe(video)))
    meta=directory/'example_metadata.json'
    meta.write_text(json.dumps(dict(shorts=[clip],output_format='horizontal',source_video=video.name)))
    record=dict(status='completed',logs=[],user_id=None,result=dict(clips=[dict(clip)]))
    monkeypatch.setattr(app,'OUTPUT_DIR',str(output));monkeypatch.setattr(app,'UPLOAD_DIR',str(uploads))
    monkeypatch.setitem(app.jobs,'quality-job',record)
    return dict(video=video,meta=meta,record=record,clip=clip,uploads=uploads,directory=directory)


def test_revalidation_no_rerender_and_cache_invalidation(job,monkeypatch):
    import recut
    monkeypatch.setattr(recut,'perform_recut',lambda **k:pytest.fail('must not rerender'))
    url='/api/clip/quality-job/0/quality'
    assert request('GET',url).json()['quality_report'] is None
    before=job['video'].read_bytes()
    report=request('POST',url,json={'force':True}).json()
    assert report['status']=='PASS' and report['accepted']
    assert job['video'].read_bytes()==before
    assert request('GET',url).json()['quality_report']['status']=='PASS'
    job['video'].write_bytes(b'damaged')
    assert request('GET',url).json()['quality_report'] is None
    report=request('POST',url,json={'force':True}).json()
    assert report['status']=='FAIL'
    assert job['record']['status']=='failed'
    assert job['record']['result']['clips']==[]
    assert job['record']['result']['quality_reports'][0]['status']=='FAIL'


def test_post_render_gate_rejects_before_publishing(job,monkeypatch):
    import recut
    def wrong_render(**kwargs):
        name='recut_1_example_clip_1.mp4'
        shutil.copy(job['video'],job['directory']/name)  # 2s output for a 1s edit
        return name,name
    monkeypatch.setattr(recut,'perform_recut',wrong_render)
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:pytest.fail('bad export must not be archived'))
    old=job['record']['result']['clips'][0]['video_url']
    response=request('POST','/api/clip/rerender',json={
        'job_id':'quality-job','clip_index':0,'segments':[{'start':0,'end':1}],
        'snap_to_words':False,'reapply_captions':False})
    assert response.status_code==422
    assert response.json()['detail']['status']=='FAIL'
    assert job['record']['result']['clips'][0]['video_url']==old
    assert json.loads(job['meta'].read_text())['shorts'][0]['video_url']==old
    assert app._canonical_clip_file(str(job['directory']),'example',0)=='example_clip_1.mp4'


def test_required_report_gates_recovery_and_unchanged_cache(job):
    clip=dict(job['clip'],quality_required=True)
    assert app._clips_actually_rendered('quality-job',str(job['directory']),'example',[clip])[0]==[]
    q.enforce(job['video'],'clip_1',clip['quality_expected'])
    assert len(app._clips_actually_rendered('quality-job',str(job['directory']),'example',[clip])[0])==1
    job['video'].write_bytes(b'changed')
    assert app._clips_actually_rendered('quality-job',str(job['directory']),'example',[clip])[0]==[]


def test_browser_export_validation_and_cleanup(job,real_clip):
    data={'job_id':'quality-job','clip_index':'0',
          'expected':json.dumps(dict(width=64,height=36,fps=24,duration=2))}
    path=real_clip('browser')
    response=request('POST','/api/quality/browser-export',data=data,
        files={'file':('export.mp4',path.read_bytes(),'video/mp4')})
    assert response.status_code==200 and response.json()['status']=='PASS'
    noaudio=real_clip('broken-audio',audio=None)
    response=request('POST','/api/quality/browser-export',data=data,
        files={'file':('export.mp4',noaudio.read_bytes(),'video/mp4')})
    assert response.status_code==422 and response.json()['status']=='FAIL'
    assert 'MISSING_AUDIO' in {p['code'] for p in response.json()['problems']}
    assert list(job['uploads'].iterdir())==[]


def test_quality_routes_enforce_ownership_and_paths(job,monkeypatch):
    from types import SimpleNamespace
    job['record']['user_id']='owner'
    monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_): return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET','/api/clip/quality-job/0/quality').status_code==404
    assert request('POST','/api/clip/quality-job/0/quality',json={}).status_code==404


def test_alternate_version_check_does_not_change_current_version(job):
    other=job['directory']/'recut_old_example_clip_1.mp4';shutil.copy(job['video'],other)
    old=dict(job['record']['result']['clips'][0])
    response=request('POST','/api/clip/quality-job/0/quality',json={'filename':other.name})
    assert response.json()['status']=='PASS'
    assert job['record']['result']['clips'][0]==old
    assert not job['record'].get('ready_files')
    assert request('POST','/api/clip/quality-job/0/quality',json={'filename':'../source.mp4'}).status_code==400


def test_quality_marker_is_internal_and_failed_clip_is_not_ready(job):
    report=dict(clip_id='clip_1',status='FAIL',accepted=False,problems=[])
    app.enqueue_output(io.BytesIO(('CLIP_QUALITY '+json.dumps(report)+'\n').encode()),'quality-job')
    assert job['record']['quality_reports']['clip_1']['status']=='FAIL'
    assert job['record']['logs']==[]
    source=open('main.py',encoding='utf-8').read()
    at=source.index("clip['quality_report'] = export_quality.enforce(")
    assert at < source.index('print(f"CLIP_READY {i} "')


def test_zip_checks_before_creating_bundle(job,monkeypatch):
    async def files(*a): return True
    monkeypatch.setattr(app,'_ensure_job_files',files)
    job['video'].write_bytes(b'broken')
    response=request('GET','/api/jobs/quality-job/download-all')
    assert response.status_code==422
    assert not list(job['directory'].glob('*.zip'))


def test_social_export_preserves_quality_failure_without_upload(job,monkeypatch):
    async def files(*a): return True
    async def credentials(*a): return 'test-only', None
    report=q.failure_report(job['video'],'clip_1','TEST_FAILURE','Bad export','Revalidate')
    async def reject(*a,**k): raise app.HTTPException(status_code=422,detail=report)
    monkeypatch.setattr(app,'_ensure_job_files',files)
    monkeypatch.setattr(app,'resolve_upload_post',credentials)
    monkeypatch.setattr(app,'resolve_post_profile',lambda *a:'test-profile')
    monkeypatch.setattr(app,'_validate_clip_export',reject)
    monkeypatch.setattr(app.httpx,'Client',lambda *a,**k:pytest.fail('must not upload failed bytes'))
    response=request('POST','/api/social/post',json={
        'job_id':'quality-job','clip_index':0,'platforms':['youtube'],'user_id':'test-profile'})
    assert response.status_code==422
    assert response.json()['detail']['status']=='FAIL'


def test_failed_media_is_not_servable_and_backup_skips_it(job,monkeypatch):
    import s3_uploader
    report=q.failure_report(job['video'],'clip_1','TEST_FAILURE','Bad export','Revalidate')
    q.save_report(job['video'],report)
    assert not app._servable_export('quality-job/example_clip_1.mp4')
    uploaded=[]
    monkeypatch.setattr(s3_uploader,'upload_file_to_s3',lambda path,*a:uploaded.append(path))
    s3_uploader.upload_job_artifacts(str(job['directory']),'quality-job')
    assert str(job['video']) not in uploaded
    q.enforce(job['video'],'clip_1',job['clip']['quality_expected'],force=True)
    assert app._servable_export('quality-job/example_clip_1.mp4')
