import asyncio
import json
from pathlib import Path
import httpx
import pytest
from test_native_home import engine, fixture
from desktop.generation_review import progress, review, register, analysis_presentation
from desktop.security import LocalAccess


def test_saved_assembly_reasons_are_visible_in_native_review(tmp_path):
    e=engine(tmp_path);fixture(e)
    e.jobs['job-one']['result']['clips'][0]['assembly_report']=dict(segments=[{},{}],operations=[
        dict(type='remove',source_start=2.4,source_end=5.6,reason='irrelevant_pause')])
    row=review(e,'job-one')['clips'][0]
    assert '3.2s (long pauses)' in row['explanation'] and 'source order preserved' in row['explanation']


def test_missing_visual_analysis_is_visible_even_for_completed_older_job():
    meta=dict(job_options={'ANALYSIS_MODE':'hybrid'},selection_fallback=True)
    data=analysis_presentation(meta)
    assert not data['visual_available'] and 'fallback' in data['warning']
    meta['analysis_status']=dict(status='fallback',error_type='ValidationError',message='secret raw provider detail')
    assert 'secret' not in str(analysis_presentation(meta))
    meta['story_analysis']={'moments':[{'start':0,'end':1}]}
    assert analysis_presentation(meta)['warning']==''


def test_progress_has_no_fabricated_percentage_and_never_leaks_logs(tmp_path):
    e=engine(tmp_path);fixture(e);j=e.jobs['job-one']
    j.update(status='processing',native_started_at=100,logs=['Job started by worker.','Transcribing video...', 'Analyzing with Gemini API_KEY=secret C:\\private\\file.mp4'])
    data=progress(e,'job-one')
    assert data['state']=='running' and data['overall'] is None and data['remaining_seconds'] is None
    assert data['stage']=='Analyzing content with Gemini'
    assert 'secret' not in json.dumps(data) and 'private' not in json.dumps(data)
    assert next(s for s in data['stages'] if s['id']=='transcribe')['percent']==100
    assert next(s for s in data['stages'] if s['id']=='analyze')['percent'] is None
    j['cancel_requested']=True
    assert progress(e,'job-one')['state']=='cancel_requested'
    j['status']='cancelled'
    assert progress(e,'job-one')['state']=='cancelled'
    assert not progress(e,'job-one')['can_cancel']


@pytest.mark.parametrize('log,part',[('429 quota exhausted','quota'),('API key invalid','authentication'),('no space left on device','storage'),('ffmpeg failed','rendering'),('Unexpected exit code 1','worker')])
def test_error_messages_are_actionable_and_sanitized(tmp_path,log,part):
    e=engine(tmp_path);fixture(e);e.jobs['job-one'].update(status='failed',logs=[log+' secret=private'])
    data=progress(e,'job-one');assert part in data['error'];assert 'private' not in str(data)


def test_visual_failure_is_not_misclassified_as_transcription(tmp_path):
    e=engine(tmp_path);path=fixture(e)
    e.jobs['job-one'].update(status='failed',logs=['Transcribing 100%',
        'Video analysis: chapter 8/8', 'Hybrid visual analysis failed after recovery attempts. No transcript-only clips were generated.'])
    (path.parent/'analysis_failure.json').write_text(json.dumps(dict(chapter=8,total_chapters=8,
        completed_chapters=7,issues=[dict(field='scene_observations.7.layout_evidence',type='missing'),
        dict(field='Bearer secret',type='private')])))
    data=progress(e,'job-one')
    assert 'Visual scene analysis failed at chapter 8/8' in data['error']
    assert 'Audio transcription failed' not in data['error']
    assert next(s for s in data['stages'] if s['id']=='analyze')['state']=='failed'
    assert any('layout_evidence (missing)' in row for row in data['diagnostics'])
    assert 'secret' not in json.dumps(data) and 'private' not in json.dumps(data)


def test_render_failure_ignores_incidental_numbers_and_key_configuration(tmp_path):
    e=engine(tmp_path);fixture(e)
    e.jobs['job-one'].update(status='failed',logs=[
        'GEMINI_API_KEY configured', 'Analyzing with Gemini', 'Saved metadata',
        'Processing Clip 1: 401.403s - 429.5s',
        'Clip 1 failed: ValueError: too many values to unpack (expected 2)',
        'No clips could be rendered'])
    data=progress(e,'job-one')
    assert 'Video rendering' in data['error']
    assert next(s for s in data['stages'] if s['id']=='render')['state']=='failed'


def test_review_validates_media_maps_scores_and_partial_results(tmp_path):
    e=engine(tmp_path);path=fixture(e);clip=e.jobs['job-one']['result']['clips'][0]
    clip.update(title='Real title',ranking_report={'overall':94,'reasons':['Complete story'],'metrics':{'clarity':88}},tags=['Insight','Insight'],hook_text='A real hook')
    (path.parent/'test_metadata.json').write_text(json.dumps({'shorts':[{'start':10,'end':20,'title':'Not rendered'}]}))
    data=review(e,'job-one');assert len(data['clips'])==2
    ready=next(c for c in data['clips'] if c['index']==7)
    assert ready['status']=='ready' and ready['score']==94 and ready['tags']==['Insight']
    assert ready['explanation']=='Complete story' and ready['hook']=='A real hook'
    assert data['clips'][0]['status']=='not_rendered'
    path.unlink();assert review(e,'job-one')['clips'][1]['status']=='unavailable'
    clip['ranking_report']['overall']=150
    assert review(e,'job-one')['clips'][1]['score'] is None


def test_state_authentication_revision_recovery_and_invalid_selection(tmp_path):
    e=engine(tmp_path);fixture(e);register(e)
    guarded=LocalAccess(e.app,'x'*48,'http://127.0.0.1:5510')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded),base_url='http://127.0.0.1:5510') as client:
            route='/api/desktop/jobs/job-one/review';headers={'X-OpenShorts-Session':'x'*48}
            assert (await client.get(route)).status_code==403
            for suffix in ('progress','review','clips/7/thumbnail'):
                assert (await client.get('/api/desktop/jobs/job-one/'+suffix)).status_code==403
            state={'revision':0,'selected':[7],'active':7,'sort':'Score','tag':'All tags','history':[{'index':7,'status':'completed','name':'my-export.mp4','at':'2026-10-17'}]}
            saved=await client.put(route,json=state,headers=headers)
            assert saved.status_code==200,saved.text
            assert saved.json()['revision']==1
            assert (await client.put(route,json=state,headers=headers)).status_code==409
            state['revision']=1;state['selected']=[999]
            assert (await client.put(route,json=state,headers=headers)).status_code==400
            assert (await client.get(route,headers=headers)).json()['preferences']['selected']==[7]
            # New registration reads exactly the persisted revision; no in-memory preference dependency.
            assert review(e,'job-one')['preferences']['history'][0]['name']=='my-export.mp4'
            assert review(e,'job-one')['preferences']['active']==7
            assert (await client.get('/api/desktop/jobs/not-a-project/review',headers=headers)).status_code==404
    asyncio.run(run())


def test_real_rendered_thumbnail_and_saved_timeline_export(job,monkeypatch):
    # Reuses real FFmpeg fixture/renderer. No paid AI provider is called.
    import app
    import timeline_api
    from test_timeline_api import BASE
    from desktop.native_api import register as native_register
    if not any(r.path=='/api/desktop/jobs/{job_id}/review' for r in app.app.routes): native_register(app)
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            data=(await client.get(BASE)).json()['project']
            edits=data['edits'];edits['style']['enabled']=False
            assert (await client.put(BASE,json={'revision':data['revision'],'edits':edits})).status_code==200
            assert (await client.post(BASE+'/run',json={'revision':1,'mode':'final','output':{'size':[1080,1920],'fps':24,'encoder':'x264','quality':'fast'}})).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],90)
            rendered=(await client.get(BASE)).json()['project']
            assert rendered['status']=='completed',rendered
            result=review(app,'quality-job');assert result['clips'][0]['status']=='ready'
            assert result['clips'][0]['resolution']=='1080 × 1920'
            thumb=await client.get('/api/desktop/jobs/quality-job/clips/0/thumbnail')
            assert thumb.status_code==200 and Path(thumb.json()['path']).is_file()
    asyncio.run(run())

from test_export_quality_api import job
from test_export_quality import real_clip


def test_recorded_elapsed_time_survives_recovery_and_stale_scores_are_hidden(tmp_path):
    e=engine(tmp_path);path=fixture(e)
    (path.parent/'desktop-generation-time.json').write_text(json.dumps(dict(started_at=100,finished_at=142)))
    assert progress(e,'job-one')['elapsed_seconds']==42
    e.jobs['job-one']['result']['clips'][0].update(ranking_stale=True,selection_score=91,ranking_report={'reasons':{'hook':'Actual retained evidence'}})
    row=review(e,'job-one')['clips'][0]
    assert row['score'] is None and row['explanation']=='Actual retained evidence'


def test_corrupt_review_document_is_never_silently_overwritten(tmp_path):
    e=engine(tmp_path);path=fixture(e);(path.parent/'desktop-review.json').write_text('{damaged')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc: review(e,'job-one')
    assert exc.value.status_code==409


def test_measured_step_percentages_do_not_invent_overall_or_skipped_work(tmp_path):
    e=engine(tmp_path);fixture(e);j=e.jobs['job-one']
    j.update(status='processing',logs=['Job started by worker.', 'Transcribing video...', 'Transcribing… 25% (10s)', 'Transcribing… 50% (20s)'])
    data=progress(e,'job-one');stages={s['id']:s for s in data['stages']}
    assert stages['prepare']['state']=='completed' and stages['prepare']['percent']==100
    assert stages['transcribe']['percent']==50 and stages['transcribe']['state']=='active'
    assert stages['analyze']['percent'] is None and data['overall'] is None
    j['logs']=['Analyzing with Gemini', 'Saved metadata', 'Processing Clip 1', 'Clip 1 ready: private-path']
    folder=Path(e.OUTPUT_DIR)/'job-one'
    (folder/'test_metadata.json').write_text(json.dumps({'shorts':[{},{}]}))
    stages={s['id']:s for s in progress(e,'job-one')['stages']}
    assert stages['render']['percent']==50
    assert stages['analyze']['state']=='completed'
    assert stages['transcribe']['state']=='not_reported' and stages['transcribe']['percent'] is None
    j['status']='failed'
    assert progress(e,'job-one')['overall'] is None


def test_finished_transcription_and_hybrid_chapters_move_to_correct_stage(tmp_path):
    e=engine(tmp_path);fixture(e);j=e.jobs['job-one']
    j.update(status='processing',logs=['Job started by worker.', 'Transcribing video...', 'Transcribing… 100% (40s)'])
    data=progress(e,'job-one');transcribe=next(s for s in data['stages'] if s['id']=='transcribe')
    assert transcribe['state']=='completed' and transcribe['percent']==100
    assert data['stage'].startswith('Transcription complete') and data['overall'] is None
    j['logs'].append('Video analysis: chapter 1/5 (0–180s)')
    data=progress(e,'job-one')
    assert data['stage']=='Analyzing content with Gemini'
    assert next(s for s in data['stages'] if s['id']=='analyze')['state']=='active'
    assert next(s for s in data['stages'] if s['id']=='analyze')['percent']==0
    assert next(s for s in data['stages'] if s['id']=='transcribe')['state']=='completed'
    j['logs'].append('Video analysis: chapter 5/5 (708–736s)')
    assert progress(e,'job-one')['stage']=='Analyzing content with Gemini'
