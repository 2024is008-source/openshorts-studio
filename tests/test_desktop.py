"""Desktop boundaries exercised without opening the UI or calling paid services."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from desktop.security import LocalAccess
from desktop.storage import Storage, validate_settings
from desktop.processes import engine_command, environment


def test_local_boundary_covers_api_and_media(tmp_path):
    async def endpoint(request):
        return JSONResponse({'ok': True})
    inner = Starlette(routes=[Route('/api/test', endpoint, methods=['GET', 'POST']),
                              Route('/videos/private.mp4', endpoint)])
    token = 'a' * 48
    app = LocalAccess(inner, token, 'http://127.0.0.1:4321', tmp_path)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:4321') as client:
            for path in ('/api/test', '/videos/private.mp4'):
                assert (await client.get(path)).status_code == 403
                assert (await client.get(path, headers={'X-OpenShorts-Session': 'incorrect'})).status_code == 403
                assert (await client.get(path, headers={'X-OpenShorts-Session': token})).status_code == 200
                assert (await client.get(path, headers={'X-OpenShorts-Session': token, 'Origin': 'https://evil.example'})).status_code == 403
                assert (await client.get(path, headers={'X-OpenShorts-Session': token, 'Host': 'evil.example:4321'})).status_code == 403
            response = await client.post('/api/test', headers={'X-OpenShorts-Session': token, 'Content-Length': str(10**18)})
            assert response.status_code == 507
    asyncio.run(check())


def test_no_session_token_means_no_local_app():
    with pytest.raises(ValueError):
        LocalAccess(None, '', 'http://127.0.0.1:4321')


def test_storage_preserves_projects_and_sources(tmp_path):
    store = Storage(tmp_path / 'local', tmp_path / 'roaming')
    project = store.local / 'output' / 'project.json'
    source = store.local / 'uploads' / 'source.mp4'
    project.write_text('saved')
    source.write_bytes(b'video')
    (store.work / 'scratch').write_text('temporary')
    store.clear_cache()
    assert project.read_text() == 'saved'
    assert source.read_bytes() == b'video'
    assert not list(store.work.iterdir())
    store.save_settings({'encoder': 'x264', 'preset': 'quiet', 'jobs': 99})
    assert store.settings() == {'encoder': 'x264', 'preset': 'quiet', 'jobs': 1}


def test_settings_reject_arbitrary_commands():
    with pytest.raises(ValueError):
        validate_settings({'encoder': 'x264 & calc.exe'})


def test_child_environment_does_not_inherit_production_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__('desktop.processes',fromlist=['resources']),'resources',lambda:tmp_path)
    monkeypatch.setenv('GEMINI_API_KEY', 'production-secret')
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'production-secret')
    monkeypatch.setenv('BILLING_ENABLED', 'true')
    monkeypatch.setenv('PYTHONPATH', 'untrusted')
    store = Storage(tmp_path / 'local', tmp_path / 'roaming')
    env = environment(store, store.settings(), 'user-key')
    assert env['GEMINI_API_KEY'] == 'user-key'
    assert env['BILLING_ENABLED'] == 'false'
    assert env['OUTPUT_MAX_GB'] == '0'
    assert env['PYTHON_DOTENV_DISABLED'] == '1'
    assert 'STRIPE_SECRET_KEY' not in env
    assert 'PYTHONPATH' not in env
    assert len(env['OPENSHORTS_LOCAL_TOKEN']) >= 48


def test_frozen_engine_uses_worker_dispatch(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert engine_command('main.py') == [sys.executable, '--worker', 'main.py']


def test_local_projects_reopen_and_reject_media_traversal(tmp_path):
    from fastapi import FastAPI
    from types import SimpleNamespace
    from desktop.projects import register
    directory = tmp_path / 'job-123'
    directory.mkdir()
    (directory / 'clip.mp4').write_bytes(b'video')
    engine = SimpleNamespace(app=FastAPI(), OUTPUT_DIR=str(tmp_path), jobs={
        'job-123': {'status': 'completed', 'result': {'clips': [{'video_file': 'clip.mp4'}]}},
        'queued': {'status': 'queued', 'result': None}})
    register(engine)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=engine.app), base_url='http://test') as client:
            assert (await client.get('/api/desktop/projects')).json()['projects'][0]['job_id'] == 'job-123'
            valid = {'clips': [{'index': 0, 'server_file': 'clip.mp4', 'active_layers': {'captions': True}}]}
            assert (await client.put('/api/projects/job-123/state', json=valid)).status_code == 200
            restored = (await client.post('/api/desktop/projects/job-123/restore')).json()
            assert restored['project_state'] == valid
            invalid = {'clips': [{'index': 0, 'server_file': '../outside.mp4'}]}
            assert (await client.put('/api/projects/job-123/state', json=invalid)).status_code == 400
            assert (await client.post('/api/desktop/projects/missing/restore')).status_code == 404
    asyncio.run(check())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking')
def test_single_instance_lock(tmp_path):
    from desktop.instance_lock import InstanceLock
    first = InstanceLock(tmp_path / 'lock')
    assert first.acquire()
    second = InstanceLock(tmp_path / 'lock')
    try:
        assert not second.acquire()
        first.close()
        assert second.acquire()
    finally:
        if not first.file.closed: first.close()
        second.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows DPAPI')
def test_credential_roundtrip_never_writes_plaintext(tmp_path):
    from desktop.credentials import CredentialStore
    vault = CredentialStore(tmp_path)
    secret = 'desktop-test-credential'
    vault.save(secret)
    assert secret.encode() not in vault.path.read_bytes()
    assert vault.load() == secret
    vault.save('')
    assert vault.load() == ''


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job Objects')
def test_job_close_kills_grandchildren(tmp_path):
    from desktop.processes import ProcessTree
    marker = tmp_path / 'grandchild.pid'
    # Child cannot create the grandchild until after assignment to the Job.
    script = "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(120)"
    tree = ProcessTree()
    try:
        child = tree.start([sys.executable, '-c', script, str(marker)], env=os.environ.copy(), cwd=tmp_path)
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists(), 'Managed child never reached startup'
        pid = int(marker.read_text())
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        assert handle
        try:
            tree.close()
            assert child.poll() is not None
            assert kernel.WaitForSingleObject(handle, 10000) == 0
        finally:
            kernel.CloseHandle(handle)
    finally:
        tree.close()
