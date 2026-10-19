import asyncio
import hashlib
import json
from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from desktop.security import LocalAccess
from learning.api import register
from learning.database import Store
from learning import highlight_ranking as hr
from test_highlight_learning import pool
from test_export_quality_api import job # noqa
from test_export_quality import real_clip # noqa

def test_native_clip_feedback_auth_provenance_and_privacy(job,tmp_path,monkeypatch):
    import app
    learning=tmp_path/'learning';monkeypatch.setenv('OPENSHORTS_LEARNING_DIR',str(learning))
    store=Store(learning);snaps=hr.observe(store,pool(),hashlib.sha256(b'synthetic API source').hexdigest(),'challenge',synthetic=True)
    original=json.loads(job['meta'].read_text());original['shorts'][0]['learning_candidate_id']=snaps[0]['id'];job['meta'].write_text(json.dumps(original))
    routes=FastAPI();register(SimpleNamespace(app=routes,_quality_context=app._quality_context));token='t'*48
    secured=LocalAccess(routes,token,'http://127.0.0.1:4321')
    before=job['video'].read_bytes()
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=secured,client=('127.0.0.1',1)),base_url='http://127.0.0.1:4321') as client:
            path='/api/clip/quality-job/0/learning-ranking'
            assert (await client.get(path)).status_code==403
            client.headers['X-OpenShorts-Session']=token
            response=await client.get(path);assert response.status_code==200
            data=response.json();assert data['candidate']==snaps[0]['id'] and len(data['alternatives'])==3
            assert (await client.post(path,json={'action':'accept'})).json()['status']=='human-approved'
            assert (await client.post(path,json={'action':'accept'})).json()['status']=='duplicate'
            assert (await client.post(path,json={'action':'reject'})).status_code==400
            assert (await client.post(path,json={'action':'rating','rating':5})).status_code==200
            assert (await client.post(path,json={'action':'trim','start':1,'end':9})).status_code==200
            assert (await client.post(path,json={'action':'alternative','alternative':snaps[1]['id']})).status_code==200
            assert (await client.post(path,json={'action':'accept','api_key':'never-accepted'})).status_code==422
            state=(await client.get('/api/desktop/learning')).json()['highlight_ranking']
            assert state['reviewed_examples']==0 and state['active_model'] is None and not state['enabled']
            prefs=store.preferences();prefs['collect']=False
            assert (await client.put('/api/desktop/learning/privacy',json=prefs)).status_code==200
            assert (await client.post(path,json={'action':'accept'})).status_code==400
            assert (await client.post('/api/desktop/learning/train',json={'task':'wrong'})).status_code==400
            assert (await client.post('/api/desktop/learning/train',json={'task':hr.TASK,'epochs':1})).status_code==200
            for _ in range(100):
                state=(await client.get('/api/desktop/learning/train')).json()
                if state['status']=='idle':break
                await asyncio.sleep(.01)
            assert state['result']['status']=='insufficient-data'
            assert (await client.post('/api/desktop/learning/models/unknown/active')).status_code==400
            (learning/'user-notes.txt').write_text('unrelated user file')
            assert (await client.post('/api/desktop/learning/delete')).status_code==200
            assert not Store(learning).preferences()['collect']
            assert (learning/'user-notes.txt').read_text()=='unrelated user file'
            assert (await client.get(path)).status_code==409
    asyncio.run(check());assert job['video'].read_bytes()==before and job['meta'].exists()

def test_older_project_remains_editable_without_rank_snapshot(job,tmp_path,monkeypatch):
    import app
    monkeypatch.setenv('OPENSHORTS_LEARNING_DIR',str(tmp_path/'learning'))
    routes=FastAPI();register(SimpleNamespace(app=routes,_quality_context=app._quality_context))
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routes),base_url='http://test') as client:
            reply=await client.get('/api/clip/quality-job/0/learning-ranking')
            assert reply.status_code==409 and 'older clip' in reply.json()['detail']
    asyncio.run(check());assert job['video'].exists()
