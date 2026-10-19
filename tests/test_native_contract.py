import asyncio
from pathlib import Path
from types import SimpleNamespace
import importlib.util

import httpx
from fastapi import FastAPI
from desktop.native_api import register
from desktop.security import LocalAccess


def test_contract_is_authenticated_and_reports_actual_routes():
    engine=SimpleNamespace(app=FastAPI());register(engine)
    guarded=LocalAccess(engine.app,'x'*48,'http://127.0.0.1:5510')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded),base_url='http://127.0.0.1:5510') as client:
            assert (await client.get('/api/desktop/contract')).status_code==403
            response=await client.get('/api/desktop/contract',headers={'X-OpenShorts-Session':'x'*48})
            data=response.json()
            assert data['protocol_version']==1 and data['editor_project_version']==1
            assert {'method':'POST','path':'/api/desktop/jobs/{job_id}/cancel'} in data['routes']
            assert 'aligned-word-edits' in data['features']
            assert 'token' not in str(data).lower()
    asyncio.run(run())


def pair_tool():
    path=Path(__file__).resolve().parents[1]/'tools/native_pair.py'
    spec=importlib.util.spec_from_file_location('native_pair',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_export_recovery_is_complete_and_excludes_runtime_secrets(tmp_path):
    tool=pair_tool();files=tool.source_files()
    assert set(tool.REQUIRED)<=set(files)
    assert not any(set(name.split('/'))&tool.OMIT for name in files)
    assert not any(Path(name).name=='.env' or name.endswith(('.mp4','.pt','.dll','.exe','.dpapi')) for name in files)
    # Test the complete real allowlist, not a fake archive inventory.
    target=tmp_path/'pair.zip';manifest=tool.export(target,files)
    assert tool.verify(target)==manifest
    assert tool.verify(target,tool.ROOT)==manifest
    import pytest
    with pytest.raises(ValueError,match='Extracted source mismatch'):tool.verify(target,tmp_path/'incomplete-transfer')


def test_export_rejects_tampered_inventory(tmp_path):
    import json,zipfile,pytest
    tool=pair_tool();target=tmp_path/'bad.zip'
    with zipfile.ZipFile(target,'w') as z:
        z.writestr('native-pair-manifest.json',json.dumps({'files':{'app.py':'bad'}}))
        z.writestr('app.py','changed')
    with pytest.raises(ValueError,match='hash mismatch'):tool.verify(target)


def test_sanitized_worker_environment_supports_windows_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(__import__('desktop.processes',fromlist=['resources']),'resources',lambda:tmp_path)
    import os,subprocess,sys
    from desktop.storage import Storage
    from desktop.processes import environment
    monkeypatch.setenv('USERNAME','native-test-user')
    monkeypatch.setenv('PRODUCTION_SECRET','never-forward')
    store=Storage(tmp_path/'library',tmp_path/'profile')
    env=environment(store,store.settings(),'')
    assert env['USERNAME']=='native-test-user' and 'PRODUCTION_SECRET' not in env
    assert Path(env['TORCHINDUCTOR_CACHE_DIR']).is_relative_to(store.cache)
    result=subprocess.run([sys.executable,'-c',"import getpass; assert getpass.getuser()=='native-test-user'"],env=env,capture_output=True,timeout=20)
    assert result.returncode==0
