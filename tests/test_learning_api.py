"""Learning routes use the existing local security boundary, with no AI calls."""
import asyncio
from types import SimpleNamespace
import httpx
from fastapi import FastAPI
import pytest
from learning.api import register
from learning.database import Store
from desktop.security import LocalAccess
from test_export_quality_api import job  # noqa: F401
from test_export_quality import real_clip  # noqa: F401
from test_auto_edit_api import attach_plan


def test_learning_routes_feedback_privacy_training_and_delete(job,tmp_path,monkeypatch):
    import app
    monkeypatch.setenv('OPENSHORTS_LEARNING_DIR',str(tmp_path/'learning'))
    routes=FastAPI();register(SimpleNamespace(app=routes,_quality_context=app._quality_context))
    token='t'*48;secured=LocalAccess(routes,token,'http://127.0.0.1:4321')
    attach_plan(job)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=secured,client=('127.0.0.1',1)),base_url='http://127.0.0.1:4321') as client:
            url='/api/desktop/learning';editor='/api/clip/quality-job/0/editor/learning'
            assert (await client.get(url)).status_code==403
            client.headers['X-OpenShorts-Session']=token
            assert (await client.get(url)).json()['database']=='healthy'
            state=(await client.get(editor)).json()
            candidate=next(c['id'] for c in state['candidates'] if c['effect']!='none')
            body=dict(event='explicit-review-1',candidate=candidate,action='approve')
            assert (await client.post(editor,json=body)).json()['status']=='human-approved'
            assert (await client.post(editor,json={**body,'event':'another-uuid'})).json()['status']=='duplicate'
            assert (await client.get(url)).json()['reviewed_examples']==1
            assert (await client.post(editor,json={**body,'candidate':'another-project'})).status_code==400
            prefs=Store(tmp_path/'learning').preferences();prefs['upload']=True
            assert (await client.put(url+'/privacy',json=prefs)).status_code==400
            prefs['upload']=False;prefs['collect']=False
            assert (await client.put(url+'/privacy',json=prefs)).status_code==200
            assert (await client.post(editor,json=body)).status_code==400
            assert (await client.post(url+'/train',json={'epochs':2})).json()['status']=='queued'
            for _ in range(100):
                result=(await client.get(url+'/train')).json()
                if result['status']=='idle':break
                await asyncio.sleep(.01)
            assert result['result']['status']=='insufficient-data'
            assert (await client.post(url+'/models/unknown/active')).status_code==400
            assert (await client.post(url+'/train/cancel')).status_code==200
            assert (await client.post(url+'/delete')).status_code==200
            assert (await client.get(url)).json()['reviewed_examples']==0
            assert job['video'].exists() and job['meta'].exists()
    asyncio.run(check())


def test_learning_location_follows_selected_desktop_library(tmp_path,monkeypatch):
    from desktop.storage import Storage
    import desktop.processes as processes
    monkeypatch.setattr(processes,'resources',lambda:tmp_path)
    storage=Storage(tmp_path/'selected-library',tmp_path/'profile')
    env=processes.environment(storage,storage.settings(),'')
    assert env['OPENSHORTS_LEARNING_DIR']==str(storage.local/'learning')
