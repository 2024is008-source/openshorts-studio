import json

import pytest

import app
import clip_ranking
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401


def test_rescore_updates_scores_without_any_render_probe_or_ai(job,monkeypatch):
    data=json.loads(job['meta'].read_text())
    data['transcript']={'segments':[dict(start=0,end=2,text='An actual source sentence.')]}
    job['meta'].write_text(json.dumps(data))
    original=job['video'].read_bytes()
    old_status=job['record']['status']
    monkeypatch.setattr(app.subprocess,'run',lambda *a,**k:pytest.fail('rescoring must not invoke media/AI processes'))
    url='/api/jobs/quality-job/ranking'
    assert request('GET',url).json()['scores'][0]['ranking_report'] is None
    first=request('POST',url+'/rescore',json={'weights':clip_ranking.DEFAULT_WEIGHTS})
    assert first.status_code==200,first.text
    report=first.json()['scores'][0]['ranking_report']
    assert report['scoring_version']==1 and report['metrics']['visual'] is None
    assert report['overall'] is not None
    assert job['video'].read_bytes()==original
    assert job['record']['status']==old_status
    assert job['record']['result']['clips'][0]['video_url']==job['clip']['video_url']
    second=request('POST',url+'/rescore',json={'weights':first.json()['weights']})
    assert second.json()==first.json()
    assert request('GET',url).json()['scores'][0]['ranking_report']==report


def test_legacy_no_analysis_is_retained_with_unknown_metrics(job):
    response=request('POST','/api/jobs/quality-job/ranking/rescore',json={})
    assert response.status_code==200
    report=response.json()['scores'][0]['ranking_report']
    assert report['overall'] is None and report['coverage_percent']==0
    assert len(job['record']['result']['clips'])==1


@pytest.mark.parametrize('weights',[{}, {'hook':25}, {key:0 for key in clip_ranking.DEFAULT_WEIGHTS},
                                  {**clip_ranking.DEFAULT_WEIGHTS,'hook':True}])
def test_invalid_rescore_weights_do_not_modify_metadata(job,weights):
    before=job['meta'].read_bytes()
    response=request('POST','/api/jobs/quality-job/ranking/rescore',json={'weights':weights})
    assert response.status_code==400
    assert job['meta'].read_bytes()==before


def test_busy_jobs_reject_rescore_and_paths_are_guarded(job):
    job['record']['status']='processing'
    assert request('POST','/api/jobs/quality-job/ranking/rescore',json={}).status_code==409
    assert request('POST','/api/jobs/missing/ranking/rescore',json={}).status_code==404


def test_ranking_routes_require_job_ownership(job,monkeypatch):
    from types import SimpleNamespace
    job['record']['user_id']='owner'
    monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET','/api/jobs/quality-job/ranking').status_code==404
    assert request('POST','/api/jobs/quality-job/ranking/rescore',json={}).status_code==404
    assert request('GET','/api/clip/quality-job/0/ranking-thumbnail').status_code==404


def test_thumbnail_generation_is_cached_and_does_not_change_video(job):
    original=job['video'].read_bytes()
    url='/api/clip/quality-job/0/ranking-thumbnail'
    response=request('GET',url)
    assert response.status_code==200,response.text
    assert response.headers['content-type']=='image/jpeg' and response.content[:2]==b'\xff\xd8'
    path=next(job['directory'].glob('ranking_*.jpg'));stamp=path.stat().st_mtime_ns
    assert request('GET',url).status_code==200 and path.stat().st_mtime_ns==stamp
    assert job['video'].read_bytes()==original
