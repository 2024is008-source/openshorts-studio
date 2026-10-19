import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import httpx
import pytest
from desktop.model_provisioning import Provisioner

def fixture(tmp_path,handler=None):
    content=b'synthetic model bytes for regression only'
    data=dict(id='whisper-small',repository='example/model',revision='a'*40,
        files=[dict(name='model.bin',size=len(content),sha256=hashlib.sha256(content).hexdigest())])
    storage=SimpleNamespace(local=tmp_path,check_space=lambda:None)
    transport=httpx.MockTransport(handler or (lambda request:httpx.Response(200,content=content)))
    service=Provisioner(storage,data,lambda:httpx.Client(transport=transport,trust_env=False))
    return service,content

def finish(service):
    service.thread.join(timeout=4)
    assert not service.thread.is_alive()
    return service.status()

def test_model_download_needs_consent_and_status_never_downloads(tmp_path):
    def forbidden(_):raise AssertionError('No network on availability request')
    service,_=fixture(tmp_path,forbidden)
    assert not service.status()['available']
    with pytest.raises(ValueError):service.start()
    assert service.thread is None

def test_model_verified_and_cached_only_after_correct_bytes(tmp_path):
    service,content=fixture(tmp_path);service.start(True)
    assert finish(service)['available']
    assert (service.folder/'model.bin').read_bytes()==content
    (service.folder/'model.bin').write_bytes(b'corrupted')
    assert not service.status()['available']

def test_resume_pinned_file_with_correct_range(tmp_path):
    requests=[];service,content=fixture(tmp_path)
    def handler(request):
        requests.append(str(request.url));assert request.headers['range']=='bytes=7-'
        return httpx.Response(206,headers={'content-range':f'bytes 7-{len(content)-1}/{len(content)}'},content=content[7:])
    service.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handler));service.folder.mkdir(parents=True)
    (service.folder/'model.bin.partial').write_bytes(content[:7]);service.start(True)
    assert finish(service)['available'] and '/'+service.data['revision']+'/' in requests[0]

def test_bad_partial_is_preserved_and_repaired(tmp_path):
    service,content=fixture(tmp_path);service.folder.mkdir(parents=True)
    (service.folder/'model.bin.partial').write_bytes(b'x'*len(content));service.start(True)
    assert finish(service)['available']
    assert list(service.folder.glob('*.rejected-*'))

def test_offline_is_recoverable(tmp_path):
    def offline(request):raise httpx.ConnectError('private URL must not be logged',request=request)
    service,content=fixture(tmp_path,offline);service.start(True)
    assert finish(service)['state']=='offline'
    service.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=content)))
    service.start(True);assert finish(service)['available']

def test_digest_failure_does_not_install(tmp_path):
    service,content=fixture(tmp_path,lambda _:httpx.Response(200,content=b'x'*40));service.start(True)
    result=finish(service)
    assert not result['available'] and result['state']=='failed'
    assert not (service.folder/'model.bin').exists()

def test_availability_reports_storage_failure_without_private_error(tmp_path,monkeypatch):
    service,_=fixture(tmp_path)
    def denied():raise PermissionError('private customer path')
    monkeypatch.setattr(service,'_check_paths',denied)
    status=service.status()
    assert not status['available'] and status['state']=='failed'
    assert status['error_code']=='verification_or_storage_failed'
    assert 'private customer path' not in json.dumps(status)

def test_cancel_keeps_recoverable_partial(tmp_path):
    service,content=fixture(tmp_path)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield content[:5]
            service.cancelled.set()
            yield content[5:]
    service.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,stream=Stream())))
    service.start(True);assert finish(service)['state']=='cancelled'
    assert not (service.folder/'model.bin').exists()

def test_native_asr_never_fetches_implicit_model(monkeypatch):
    import transcribe_backends as backend
    monkeypatch.setenv('OPENSHORTS_DESKTOP','1')
    monkeypatch.setattr(backend,'get_whisper_config',lambda:dict(model_size='uninstalled-remote-model',device='cpu',compute_type='int8'))
    with pytest.raises(RuntimeError,match='user confirmation'):backend._get_whisper_model()

def test_frozen_deno_uses_resources_and_never_developer_path(tmp_path,monkeypatch):
    import desktop.download_runtime as runtime
    import desktop.processes as processes
    monkeypatch.setattr(processes,'resources',lambda:tmp_path)
    monkeypatch.setattr(runtime.sys,'frozen',True,raising=False)
    monkeypatch.setattr(runtime.sys,'executable',str(tmp_path/'engine.exe'))
    monkeypatch.setattr(runtime.shutil,'which',lambda _:pytest.fail('Developer PATH lookup'))
    assert runtime.deno_path() is None
    (tmp_path/'bin').mkdir();binary=tmp_path/'bin'/('deno.exe' if os.name=='nt' else 'deno');binary.write_bytes(b'fixture')
    assert runtime.deno_path()==str(binary)

def test_sanitized_render_failure_contains_no_content(tmp_path):
    import subprocess
    from desktop.render_diagnostics import record
    error=subprocess.CalledProcessError(7,['ffmpeg','secret-key','private-media-path'],stderr='transcript and customer data')
    data=record(tmp_path,error,'Rendering changed video segments','b'*32)
    text=json.dumps(data)
    assert data['ffmpeg_exit_code']==7 and data['stage']=='segments' and data['worker_pid']>0
    assert all(x not in text for x in ['secret-key','private-media-path','transcript','customer data'])

@pytest.mark.skipif(os.name!='nt',reason='Windows read sharing')
def test_editor_publication_survives_real_reader(tmp_path):
    import ctypes
    from ctypes import wintypes
    from desktop.editor_state import publish
    p=tmp_path/'project.json';p.write_text('{}')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(p),0x80000000,3,None,3,0x80,None)
    assert handle not in (None,ctypes.c_void_p(-1).value)
    release=threading.Timer(.08,lambda:kernel.CloseHandle(handle));release.start()
    try:publish(p,dict(status='preview_ready'))
    finally:release.join()
    assert json.loads(p.read_text())['status']=='preview_ready'

def test_editor_permanent_denial_is_bounded(tmp_path,monkeypatch):
    import desktop.editor_state as state
    waits=[]
    def denied(*_):
        error=PermissionError('redacted');error.winerror=5;raise error
    monkeypatch.setattr(state,'atomic_json',denied);monkeypatch.setattr(state.time,'sleep',waits.append)
    with pytest.raises(PermissionError):state.publish(tmp_path/'project.json',{})
    assert sum(waits)<1

def test_renderer_missing_resources_never_ready(tmp_path,monkeypatch):
    from desktop.renderer_runtime import Renderer
    import desktop.processes as processes
    monkeypatch.setattr(processes,'resources',lambda:tmp_path)
    service=Renderer(SimpleNamespace(),SimpleNamespace(local=tmp_path))
    status=service.start()
    assert not status['ready'] and not status['running'] and status['unavailable']
    assert status['error_code']=='renderer_resources_missing'
