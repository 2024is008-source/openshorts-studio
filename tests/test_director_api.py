import json

import pytest

import app
import editing_director as director
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401

BASE='/api/clip/quality-job/0/editor'


@pytest.fixture
def directed_job(job,monkeypatch):
    monkeypatch.delenv('CAPTION_PRESET',raising=False)
    monkeypatch.setenv('AUTO_HOOK','1')
    monkeypatch.setenv('AUTO_CAPTIONS','1')
    plan=director.compile_plan(media=str(job['video']),width=64,height=36,fps=24.,out_size=(108,192),
        ranges=[(0,48,'TRACK')],xs=[22]*48,ys=[0]*48,crop_size=(20,36),
        context=dict(source_path=str(job['video']),source_duration=2.,
                     transcript={'segments':[dict(start=.2,end=1.5,text='Actual source speech.')]}))
    director.save(job['video'],plan)
    data=json.loads(job['meta'].read_text())
    data['shorts'][0].update(edit_decision_file=job['video'].name+'.edit.json',director_delivery_file=job['video'].name)
    job['meta'].write_text(json.dumps(data))
    return job,plan


def test_director_preview_reuses_saved_plan_and_preserves_final_export(directed_job,monkeypatch):
    job,plan=directed_job
    import main
    monkeypatch.setattr(main,'detect_scenes',lambda *_:pytest.fail('preview cannot reanalyze'))
    monkeypatch.setattr(main,'detect_face_candidates',lambda *_:pytest.fail('preview cannot redetect'))
    monkeypatch.setattr(main,'get_viral_clips',lambda *_:pytest.fail('preview cannot reselect'))
    assert request('GET',BASE+'/director').json()['plan']==plan
    original=job['video'].read_bytes();before=job['meta'].read_bytes()
    result=request('POST',BASE+'/director-preview',json={})
    assert result.status_code==200,result.text
    assert result.json()['quality_report']['accepted']
    preview=job['directory']/result.json()['new_video_url'].split('/')[-1]
    stamp=preview.stat().st_mtime_ns
    assert request('POST',BASE+'/director-preview',json={}).json()['decision_digest']==result.json()['decision_digest']
    assert preview.stat().st_mtime_ns==stamp
    assert job['video'].read_bytes()==original and job['meta'].read_bytes()==before
    assert job['record']['status']=='completed'
    assert not list(job['directory'].glob('temp_director_*'))


def test_missing_and_stale_director_plans_are_not_replayed(job,directed_job):
    job,_=directed_job
    data=json.loads(job['meta'].read_text());data['shorts'][0]['director_delivery_file']='different.mp4'
    job['meta'].write_text(json.dumps(data))
    assert request('GET',BASE+'/director').status_code==409
    data['shorts'][0]['edit_decision_file']='../../.env';job['meta'].write_text(json.dumps(data))
    assert request('GET',BASE+'/director').status_code==404


def test_changed_source_and_invalid_plan_rejected(directed_job):
    job,_=directed_job
    job['video'].write_bytes(b'replaced source')
    response=request('POST',BASE+'/director-preview',json={})
    assert response.status_code==409
    (job['directory']/(job['video'].name+'.edit.json')).write_text('{}')
    assert request('GET',BASE+'/director').status_code==409


def test_director_routes_require_ownership(directed_job,monkeypatch):
    from types import SimpleNamespace
    job,_=directed_job
    job['record']['user_id']='owner';monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET',BASE+'/director').status_code==404
    assert request('POST',BASE+'/director-preview',json={}).status_code==404
