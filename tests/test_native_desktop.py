"""Additive native routes retain the prior authenticated desktop boundary."""
import asyncio
from types import SimpleNamespace
from pathlib import Path
import httpx
from fastapi import FastAPI
from desktop.native_api import register
from desktop.security import LocalAccess


def host(tmp_path):
    output=tmp_path/'output';uploads=tmp_path/'uploads'
    (output/'job-1').mkdir(parents=True);uploads.mkdir()
    source=uploads/'job-1_source.mp4';source.write_bytes(b'video')
    clip=output/'job-1'/'clip.mp4';clip.write_bytes(b'video')
    cleared=[]
    engine=SimpleNamespace(app=FastAPI(),OUTPUT_DIR=str(output),UPLOAD_DIR=str(uploads),
        jobs={'job-1':{'status':'queued','result':{'clips':[{'video_url':'/videos/job-1/clip.mp4'}]}}},
        _locate_source=lambda _:str(source),_clear_resume_manifest=lambda jid:cleared.append(jid),
        _servable_export=lambda _:True,_safe_under=lambda root,relative:str(Path(root)/relative))
    register(engine)
    return engine,cleared


def test_native_routes_remain_guarded_and_cancel_queued_job(tmp_path):
    engine,cleared=host(tmp_path);token='a'*48
    app=LocalAccess(engine.app,token,'http://127.0.0.1:5555')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:5555') as client:
            assert (await client.post('/api/desktop/jobs/job-1/cancel')).status_code==403
            client.headers['X-OpenShorts-Session']=token
            assert (await client.post('/api/desktop/jobs/job-1/cancel')).json()['status']=='cancelling'
            assert engine.jobs['job-1']['cancel_requested'] is True
            assert cleared==['job-1']
            assert (await client.get('/api/desktop/source/job-1')).status_code==200
            assert (await client.get('/api/desktop/media/job-1/0')).status_code==200
            assert (await client.get('/api/desktop/media/job-1/10')).status_code==404
    asyncio.run(run())


def test_native_source_cannot_escape_project_storage(tmp_path):
    engine,_=host(tmp_path);outside=tmp_path/'private.mp4';outside.write_bytes(b'private')
    engine._locate_source=lambda _:str(outside)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=engine.app),base_url='http://test') as client:
            assert (await client.get('/api/desktop/source/job-1')).status_code==400
    asyncio.run(run())


def test_native_cancel_closes_pipeline_job_object(tmp_path):
    engine,_=host(tmp_path);closed=[]
    engine.jobs['job-1'].update(status='processing',_desktop_tree=SimpleNamespace(close=lambda:closed.append(True)))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=engine.app),base_url='http://test') as client:
            assert (await client.post('/api/desktop/jobs/job-1/cancel')).status_code==200
    asyncio.run(run())
    assert closed==[True]


def test_real_pipeline_cancellation_keeps_files_and_stops_worker(tmp_path,monkeypatch):
    import os
    import sys
    import app
    output=tmp_path/'output';output.mkdir()
    kept=output/'saved-project.json';kept.write_text('{"saved":true}')
    marker=tmp_path/'worker-ready'
    script="import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(120)"
    data={'cmd':[sys.executable,'-c',script,str(marker)],'env':os.environ.copy(),
          'output_dir':str(output),'logs':[],'status':'queued'}
    monkeypatch.setenv('OPENSHORTS_DESKTOP','1')
    monkeypatch.setitem(app.jobs,'native-cancel-test',data)
    engine=SimpleNamespace(app=FastAPI(),jobs=app.jobs,_clear_resume_manifest=lambda _:None)
    register(engine)
    async def run():
        task=asyncio.create_task(app.run_job('native-cancel-test',data))
        try:
            for _ in range(100):
                if marker.exists():break
                await asyncio.sleep(.05)
            assert marker.exists()
            tree=data['_desktop_tree'];child=tree.children[0]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=engine.app),base_url='http://test') as client:
                assert (await client.post('/api/desktop/jobs/native-cancel-test/cancel')).status_code==200
            await asyncio.wait_for(task,10)
            assert child.poll() is not None
            assert data['status']=='cancelled'
            assert kept.exists()
        finally:
            tree=data.get('_desktop_tree')
            if tree:tree.close()
            if not task.done():task.cancel()
    asyncio.run(run())
