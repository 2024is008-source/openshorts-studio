import asyncio
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
from types import SimpleNamespace
import urllib.request

import httpx
import pytest
from fastapi import FastAPI
from desktop import import_worker as worker
from desktop.security import LocalAccess
from desktop.video_import import register, MAX_BYTES


@pytest.fixture(scope='module')
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp('native-import') / 'source.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=12:d=1', '-c:v', 'libx264', '-threads', '1', str(path)], check=True, timeout=30)
    return path


@pytest.mark.parametrize('source', ['file:///C:/secret.mp4', 'ftp://example.com/a.mp4', 'https://user:secret@example.com/a.mp4', 'https://example.com:8080/a.mp4', 'not a url', 'https://example.com/page'])
def test_invalid_or_unsupported_url(source):
    with pytest.raises(ValueError):worker.validate_source(dict(kind='url', source=source, acknowledged=True))


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '192.168.1.2', '100.64.0.1', '::1', 'fe80::1', '::ffff:127.0.0.1', '64:ff9b::7f00:1', '2002:7f00:1::'])
def test_private_and_transition_targets_blocked(address):
    with pytest.raises(ValueError):worker.public_ip(address)


def test_dns_all_answers_rebinding_and_redirect_guard(monkeypatch):
    original_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, 'connect', original_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', socket.socket.connect_ex)
    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, 'redirect_request', urllib.request.HTTPRedirectHandler.redirect_request)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('93.184.216.34',443)), (2,1,6,'',('127.0.0.1',443))])
    worker.install_network_guard()
    with pytest.raises(ValueError):socket.getaddrinfo('public.example',443)
    with socket.socket() as sock:
        with pytest.raises(ValueError):sock.connect(('127.0.0.1',80))
        with pytest.raises(ValueError):sock.connect(('169.254.169.254',80))
    handler = urllib.request.HTTPRedirectHandler()
    with pytest.raises(ValueError):handler.redirect_request(None,None,302,'',{},'ftp://public.example/video.mp4')
    request = handler.redirect_request(urllib.request.Request('https://public.example/source.mp4'),None,302,'',{},'http://127.0.0.1/video.mp4')
    assert request.host == '127.0.0.1'
    with socket.socket() as sock:
        with pytest.raises(ValueError):sock.connect((request.host,80))


def test_local_valid_unicode_duplicate_and_preserve(video,tmp_path):
    original = tmp_path / '你好 source.mp4';shutil.copy2(video,original)
    for name in ('first','duplicate'):
        folder=tmp_path/name;folder.mkdir();job=worker.ImportJob(folder);job.local(str(original))
        state=json.loads((folder/'state.json').read_text('utf-8'))
        assert state['state']=='completed' and state['media']['path']==str(original.resolve())
        assert state['width']==320 and state['height']==180 and state['duration']>0
        assert (folder/'manifest.json').exists() and (folder/'preview.jpg').exists()
        assert not (folder/'source.mp4').exists()
    assert original.read_bytes()==video.read_bytes()


def test_long_filename_alias(video,tmp_path):
    original=tmp_path/('long unicode 你好 '+ 'a'*175 +'.mp4');shutil.copy2(video,original)
    folder=tmp_path/'owned';folder.mkdir();worker.ImportJob(folder).local(str(original))
    data=json.loads((folder/'manifest.json').read_text('utf-8'))
    assert len(str(original))>=240
    assert data['path']==str(folder/'source.mp4') and original.exists()


@pytest.mark.parametrize('copy_fallback',[False,True])
def test_long_alias_fallback_preserves_original(video,tmp_path,monkeypatch,copy_fallback):
    original=tmp_path/('original '+ 'b'*180 +'.mp4');shutil.copy2(video,original)
    if copy_fallback:
        monkeypatch.setattr(worker.os,'link',lambda *a: (_ for _ in ()).throw(OSError('Cross-device link')))
    before=original.stat().st_mtime_ns
    folder=tmp_path/'alias';folder.mkdir();worker.ImportJob(folder).local(str(original))
    media=json.loads((folder/'manifest.json').read_text('utf-8'))
    assert media['path']==str(folder/'source.mp4')
    assert original.stat().st_mtime_ns==before and original.read_bytes()==video.read_bytes()
    assert media['mtime_ns']==(folder/'source.mp4').stat().st_mtime_ns


def test_missing_invalid_extension_and_invalid_stream(tmp_path):
    with pytest.raises(ValueError):worker.validate_source(dict(kind='local',source=str(tmp_path/'bad.exe')))
    with pytest.raises(ValueError):worker.probe(tmp_path/'missing.mp4')
    bad=tmp_path/'bad.mp4';bad.write_bytes(b'not video')
    with pytest.raises(ValueError,match='FFprobe'):worker.probe(bad)


def test_duration_codec_and_space_limits(video,tmp_path,monkeypatch):
    def result(duration=1,codec='h264'):
        return SimpleNamespace(stdout=json.dumps({'streams':[dict(codec_type='video',codec_name=codec,width=320,height=180)],'format':dict(duration=duration)}))
    monkeypatch.setattr(worker.subprocess,'run',lambda *a,**k:result(7201))
    with pytest.raises(ValueError,match='duration'):worker.probe(video)
    monkeypatch.setattr(worker.subprocess,'run',lambda *a,**k:result(1,'unknown'))
    with pytest.raises(ValueError,match='codec'):worker.probe(video)
    monkeypatch.setattr(worker.shutil,'disk_usage',lambda p:SimpleNamespace(free=1))
    with pytest.raises(ValueError,match='storage'):worker.check_space(tmp_path)


class Response(io.BytesIO):
    def __init__(self,content,total):
        super().__init__(content);self.headers={} if total is None else {'Content-Length':str(total)}


@pytest.mark.parametrize('known',[True,False])
def test_direct_download_real_bytes_and_probe(video,tmp_path,monkeypatch,known):
    content=video.read_bytes()
    class Opener:
        def open(self,request,timeout):return Response(content,len(content) if known else None)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Opener())
    job=worker.ImportJob(tmp_path);job.direct('https://public.example/sample.mp4?token=not-logged')
    data=json.loads((tmp_path/'state.json').read_text('utf-8'))
    assert data['state']=='completed' and data['downloaded']==len(content)
    assert (tmp_path/'source.mp4').read_bytes()==content
    assert 'not-logged' not in (tmp_path/'state.json').read_text('utf-8')


def test_large_metadata_rejected_before_download(tmp_path,monkeypatch):
    calls=[]
    class Opener:
        def open(self,request,timeout):calls.append(request);return Response(b'',MAX_BYTES+1)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Opener())
    with pytest.raises(ValueError,match='limit'):worker.ImportJob(tmp_path).direct('https://public.example/a.mp4')
    assert len(calls)==1 and not list(tmp_path.glob('*.part'))


def test_timeout_retry_and_truncated_download(tmp_path,monkeypatch):
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request)
            if isinstance(request,urllib.request.Request):return Response(b'',None)
            raise TimeoutError()
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Opener())
    with pytest.raises(TimeoutError):worker.ImportJob(tmp_path).direct('https://public.example/a.mp4')
    assert len(calls)==3 and not list(tmp_path.glob('*.part'))
    class Truncated:
        def open(self,*a,**k):return Response(b'x',100)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Truncated())
    with pytest.raises(ValueError,match='complete'):worker.ImportJob(tmp_path).direct('https://public.example/a.mp4')


def test_installed_ytdlp_adapter_metadata_progress_and_safe_transport(video,tmp_path,monkeypatch):
    import yt_dlp
    class UrllibRH:pass
    class Other:pass
    class Ydl:
        def __init__(self,opts):self.opts=opts;self._request_director=SimpleNamespace(handlers={'urllib':UrllibRH(),'native':Other()})
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def extract_info(self,source,download):
            assert not download and self.opts['proxy']=='' and self.opts['remote_components']==set()
            return dict(title='Fixture public video',duration=1,filesize=video.stat().st_size,width=320,height=180,protocol='https',ext='mp4',extractor_key='YouTube')
        def process_info(self,info):
            assert list(self._request_director.handlers)==['urllib']
            shutil.copy2(video,tmp_path/'source.mp4')
            self.opts['progress_hooks'][0](dict(status='downloading',downloaded_bytes=video.stat().st_size,total_bytes=video.stat().st_size))
    monkeypatch.setattr(yt_dlp,'YoutubeDL',Ydl)
    from yt_dlp.networking import _urllib
    monkeypatch.setattr(_urllib.RedirectHandler,'redirect_request',_urllib.RedirectHandler.redirect_request)
    worker.ImportJob(tmp_path).platform('https://youtube.com/watch?v=fixture')
    assert json.loads((tmp_path/'state.json').read_text('utf-8'))['state']=='completed'


def test_routes_auth_cancel_start_race_and_owned_cleanup(tmp_path,monkeypatch):
    import desktop.processes
    class Process:
        def __init__(self,done):self.done=done
        def poll(self):return 0 if self.done.is_set() else None
        def wait(self,timeout=None):self.done.wait(3)
    class Tree:
        def __init__(self):self.done=threading.Event()
        def start(self,command,**kwargs):
            folder=Path(command[-1]);(folder/'source.mp4.part').write_bytes(b'partial')
            return Process(self.done)
        def close(self):self.done.set()
    monkeypatch.setattr(desktop.processes,'ProcessTree',Tree)
    engine=SimpleNamespace(app=FastAPI(),UPLOAD_DIR=str(tmp_path/'uploads'));register(engine)
    guarded=LocalAccess(engine.app,'x'*48,'http://127.0.0.1:5510')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded),base_url='http://127.0.0.1:5510') as client:
            assert (await client.post('/api/desktop/imports',json={})).status_code==403
            client.headers['X-OpenShorts-Session']='x'*48
            identity='a'*32
            assert (await client.post(f'/api/desktop/imports/{identity}/cancel',json={})).status_code==200
            body=dict(kind='local',source=str(tmp_path/'source.mp4'),import_id=identity)
            assert (await client.post('/api/desktop/imports',json=body)).status_code==409
            body['import_id']='b'*32
            assert (await client.post('/api/desktop/imports',json=body)).status_code==200
            owned=tmp_path/'uploads'/'native-imports'/body['import_id']
            (owned/'unrelated.txt').write_text('keep')
            assert (await client.get('/api/desktop/imports/not-owned')).status_code==404
            assert (await client.post('/api/desktop/imports/'+body['import_id']+'/cancel',json={})).json()['state']=='cancelled'
            for _ in range(30):
                if not list((tmp_path/'uploads').rglob('*.part')):break
                await asyncio.sleep(.03)
            assert not list((tmp_path/'uploads').rglob('*.part'))
            assert (owned/'unrelated.txt').read_text()=='keep'
            body['import_id']='c'*32
            assert (await client.post('/api/desktop/imports',json=body)).status_code==200
            committed=tmp_path/'uploads'/'native-imports'/body['import_id']
            media=committed/'source.mp4';media.write_bytes(b'committed fixture')
            (committed/'manifest.json').write_text(json.dumps(dict(path=str(media))))
            assert (await client.post('/api/desktop/imports/'+body['import_id']+'/cancel',json={})).json()['state']=='completed'
            assert media.read_bytes()==b'committed fixture'
    unrelated=tmp_path/'keep.mp4';unrelated.write_bytes(b'original')
    asyncio.run(run());assert unrelated.read_bytes()==b'original'


def test_committed_import_can_be_followed_while_worker_exits(tmp_path,monkeypatch):
    import desktop.processes
    done=threading.Event()
    class Process:
        def poll(self):return 0 if done.is_set() else None
        def wait(self,timeout=None):done.wait(5)
    class Tree:
        def start(self,*args,**kwargs):return Process()
        def close(self):done.set()
    monkeypatch.setattr(desktop.processes,'ProcessTree',Tree)
    engine=SimpleNamespace(app=FastAPI(),UPLOAD_DIR=str(tmp_path/'uploads'));register(engine)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=engine.app),base_url='http://test') as client:
            body=dict(kind='local',source=str(tmp_path/'source.mp4'),import_id='d'*32)
            assert (await client.post('/api/desktop/imports',json=body)).status_code==200
            second=dict(body,import_id='e'*32)
            assert (await client.post('/api/desktop/imports',json=second)).status_code==409
            folder=tmp_path/'uploads'/'native-imports'/body['import_id']
            (folder/'manifest.json').write_text(json.dumps(dict(path=str(tmp_path/'source.mp4'))))
            assert (await client.post('/api/desktop/imports',json=second)).status_code==200
    try:asyncio.run(run())
    finally:done.set()


def test_runtime_uses_local_deno_and_error_messages_are_redacted(tmp_path,monkeypatch):
    runtime=tmp_path/('deno.exe' if worker.os.name=='nt' else 'deno');runtime.write_bytes(b'fixture')
    monkeypatch.setattr(worker.sys,'executable',str(tmp_path/'python.exe'))
    assert worker.javascript_runtimes()=={'deno':{'path':str(runtime)}}
    for message,expected in [('ERROR: video unavailable https://signed.example/x?token=secret','unavailable'),('Requested format is not available https://signed.example/?secret=1','supported'),('HTTP Error 403: signed=secret','refused'),('Please sign in to confirm your age','sign-in')]:
        text=worker.import_error(Exception(message))
        assert expected in text and 'secret' not in text and 'http' not in text.lower()


def test_adaptive_http_streams_merge_locally(video,tmp_path,monkeypatch):
    import yt_dlp
    audio=tmp_path/'fixture.m4a'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','sine=duration=1','-c:a','aac',str(audio)],check=True,timeout=30)
    folder=tmp_path/'owned';folder.mkdir()
    class UrllibRH:pass
    class Ydl:
        def __init__(self,opts):
            self.opts=opts;self.params={'outtmpl':{'default':opts['outtmpl']}}
            self._request_director=SimpleNamespace(handlers={'urllib':UrllibRH()})
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def extract_info(self,*a,**k):
            return dict(title='Adaptive fixture',duration=1,requested_formats=[dict(format_id='v',protocol='https',ext='mp4',vcodec='h264',acodec='none',filesize=video.stat().st_size),dict(format_id='a',protocol='https',ext='m4a',vcodec='none',acodec='aac',filesize=audio.stat().st_size)])
        def prepare_filename(self,item):return self.params['outtmpl']['default'] % item
        def process_info(self,item):
            assert 'requested_formats' not in item and self.opts['fixup']=='never'
            fixture=video if item['format_id']=='0' else audio
            shutil.copy2(fixture,self.prepare_filename(item))
            self.opts['progress_hooks'][0](dict(status='downloading',downloaded_bytes=fixture.stat().st_size,total_bytes=fixture.stat().st_size))
    monkeypatch.setattr(yt_dlp,'YoutubeDL',Ydl)
    job=worker.ImportJob(folder);job.platform('https://youtube.com/watch?v=fixture')
    data=json.loads((folder/'manifest.json').read_text('utf-8'))
    assert data['path']==str(folder/'source.mp4')
    streams=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',data['path']],capture_output=True,check=True,timeout=30).stdout)['streams']
    assert {s['codec_type'] for s in streams}=={'video','audio'}
    assert not (folder/'source.0.mp4').exists() and not (folder/'source.1.m4a').exists()


def test_manifest_committed_between_read_and_exit_poll_is_not_failure(tmp_path,monkeypatch):
    import desktop.processes
    done=threading.Event()
    class Process:
        returncode=0
        def __init__(self,folder):self.folder=folder
        def poll(self):
            (self.folder/'manifest.json').write_text(json.dumps(dict(path=str(tmp_path/'source.mp4'))))
            return 0
        def wait(self,timeout=None):done.wait(5)
    class Tree:
        def start(self,command,**kwargs):return Process(Path(command[-1]))
        def close(self):done.set()
    monkeypatch.setattr(desktop.processes,'ProcessTree',Tree)
    e=SimpleNamespace(app=FastAPI(),UPLOAD_DIR=str(tmp_path/'uploads'));register(e)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=e.app),base_url='http://test') as client:
            identity='f'*32
            assert (await client.post('/api/desktop/imports',json=dict(kind='local',source=str(tmp_path/'source.mp4'),import_id=identity))).status_code==200
            data=(await client.get('/api/desktop/imports/'+identity)).json()
            assert data['state']=='completed'
    try:asyncio.run(run())
    finally:done.set()
