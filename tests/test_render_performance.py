"""TASK-010: real encodes, bounded execution, replay, cache and measured clocks."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

import export_quality as q
import ffmpeg_utils as e
import render_runtime as r
import timeline_project
import timeline_render
from test_export_quality import real_clip  # noqa: F401
from test_export_quality_api import job,request  # noqa: F401


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv('FFMPEG_ENCODER','x264');monkeypatch.delenv('QUALITY_PRESET',raising=False)
    monkeypatch.delenv('FFMPEG_X264_PRESET',raising=False);monkeypatch.delenv('FFMPEG_NVENC_PRESET',raising=False)
    monkeypatch.setattr(r,'_gate',None);e.reset_encoder_cache()
    yield
    e.reset_encoder_cache()


def command(source,output,encoder='libx264'):
    args=['-c:v','libx264','-preset','fast','-crf','18'] if encoder=='libx264' else copy.deepcopy(e._NVENC_ARGS[e.QUALITY_FAST])
    return ['ffmpeg','-v','error','-y','-i',str(source),'-t','1',*args,'-c:a','aac',str(output)]


def test_real_atomic_output_progress_and_receipt(tmp_path,real_clip):
    source=real_clip();output=tmp_path/'output.mp4';rows=[]
    r.run(command(source,output),progress=rows.append,duration=1)
    receipt=json.loads(Path(str(output)+'.render.json').read_text())
    assert receipt['effective_encoder']=='libx264' and not receipt['cpu_fallback']
    assert receipt['fingerprint']==q.fingerprint(output) and receipt['frame']==24
    assert rows and max(row['time_seconds'] for row in rows)>.8
    assert all(0<=row['fraction']<1 for row in rows)
    assert q.streams(q.probe(output))[0]['pix_fmt']=='yuv420p'
    raw=output.read_bytes()
    assert raw.index(b'moov')<raw.index(b'mdat')
    assert not list(tmp_path.glob('.render-*'))


def test_failed_nvenc_replays_filters_on_cpu_once(tmp_path,real_clip,monkeypatch):
    source=real_clip();output=tmp_path/'retry.mp4';execute=r._execute;calls=[]
    def failed(command,*args):
        calls.append(list(command))
        if 'h264_nvenc' in command:
            Path(command[-1]).write_bytes(b'partial')
            return dict(returncode=1,stdout=b'',stderr='[h264_nvenc] OpenEncodeSessionEx failed',peak_ram_bytes=10,progress={})
        return execute(command,*args)
    monkeypatch.setattr(r,'_execute',failed)
    argv=command(source,output,'h264_nvenc');saved=list(argv)
    r.run(argv)
    assert len(calls)==2 and 'libx264' in calls[-1] and '-cq' not in calls[-1]
    assert argv==saved and calls[0][calls[0].index('-t')+1]==calls[1][calls[1].index('-t')+1]
    report=q.enforce(output,'retry',q.expectations(q.probe(source),duration=1))
    assert report['render']['cpu_fallback'] and report['render']['effective_encoder']=='libx264'


def test_decode_or_filter_failure_does_not_trigger_hardware_repair(tmp_path,monkeypatch):
    output=tmp_path/'keep.mp4';output.write_bytes(b'previous good output');calls=[]
    def fail(command,*args):
        calls.append(command)
        Path(command[-1]).write_bytes(b'bad')
        return dict(returncode=1,stdout=b'',stderr='Invalid data found when processing input',peak_ram_bytes=None,progress={})
    monkeypatch.setattr(r,'_execute',fail)
    with pytest.raises(subprocess.CalledProcessError):r.run(command('missing.mp4',output,'h264_nvenc'))
    assert len(calls)==1 and output.read_bytes()==b'previous good output'
    assert not list(tmp_path.glob('.render-*'))


def test_cpu_fallback_quality_settings_and_timing_are_preserved(monkeypatch):
    for cq,crf in [('20','16'),('25','18'),('29','22')]:
        args=['ffmpeg','-ss','1.2','-i','in.mp4','-t','3','-filter_complex','[0:v]scale=1080:1920[v]',
            '-map','[v]','-c:v','h264_nvenc','-preset','p6','-cq',cq,'-tune','hq','-b:v','0','-spatial-aq','1','-c:a','copy','out.mp4']
        cpu=e.cpu_fallback_command(args)
        assert cpu[cpu.index('-crf')+1]==crf and 'libx264' in cpu and '-cq' not in cpu
        assert cpu[cpu.index('-filter_complex')+1]==args[args.index('-filter_complex')+1]
        assert cpu[cpu.index('-c:a')+1]=='copy' and cpu[cpu.index('-ss')+1]=='1.2'
    monkeypatch.setenv('FFMPEG_X264_PRESET','veryfast')
    assert e.video_encode_args()[3]=='veryfast'
    monkeypatch.setenv('FFMPEG_X264_PRESET','bad;filter')
    with pytest.raises(ValueError):e.video_encode_args()


def test_encoder_settings_change_cache_identity(monkeypatch):
    first=r.encoder_signature()
    monkeypatch.setenv('QUALITY_PRESET','studio')
    assert first!=r.encoder_signature()
    second=r.encoder_signature();monkeypatch.setenv('FFMPEG_THREADS','2')
    assert second!=r.encoder_signature()


def test_cpu_override_is_thread_local(monkeypatch):
    monkeypatch.setenv('FFMPEG_ENCODER','nvenc');monkeypatch.setattr(e,'_probe_nvenc',lambda:True)
    found=[]
    with e.cpu_encoding():
        thread=threading.Thread(target=lambda:found.append(e.video_encode_args()[1]));thread.start();thread.join()
        assert e.video_encode_args()[1]=='libx264'
    assert found==['h264_nvenc'] and e.video_encode_args()[1]=='h264_nvenc'


def test_binary_waveform_pipe_is_not_mixed_with_progress(real_clip):
    source=real_clip()
    output,_=r.run(['ffmpeg','-v','error','-i',str(source),'-t','0.25','-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'])
    assert len(output)==4000 and b'progress=' not in output and any(output)


def test_cancel_and_timeout_preserve_target_and_release_slots(tmp_path,real_clip):
    source=real_clip();output=tmp_path/'existing.mp4';output.write_bytes(b'keep')
    cancel=threading.Event();timer=threading.Timer(.3,cancel.set);timer.start()
    argv=command(source,output);argv[argv.index('-i'):argv.index('-i')]=['-re']
    with pytest.raises(r.Cancelled):r.run(argv,cancel)
    timer.join();assert output.read_bytes()==b'keep' and not list(tmp_path.glob('.render-*'))
    with pytest.raises(TimeoutError):r.run([sys.executable,'-c','import time;time.sleep(10)'],timeout=.1)
    cancel.clear();r.run(command(source,output),cancel)
    assert q.streams(q.probe(output))[0]


def test_encoder_slot_limit_and_waiting_cancel(tmp_path,monkeypatch):
    monkeypatch.setenv('RENDER_MAX_ENCODERS','1');active=0;peak=0;lock=threading.Lock();entered=threading.Event()
    def execute(*args):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        entered.set();time.sleep(.15)
        with lock:active-=1
        return dict(returncode=0,stdout=b'',stderr='',peak_ram_bytes=None,progress={})
    monkeypatch.setattr(r,'_execute',execute)
    threads=[threading.Thread(target=lambda:r.run(['ffmpeg','-f','null','-'])) for _ in range(3)]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    assert peak==1


def test_waiting_encoder_slot_can_cancel_without_affecting_running_work(monkeypatch):
    gate=threading.BoundedSemaphore(1);gate.acquire();monkeypatch.setattr(r,'_gate',gate)
    cancel=threading.Event();timer=threading.Timer(.15,cancel.set);timer.start()
    try:
        with pytest.raises(r.Cancelled):r.run(['ffmpeg','-f','null','-'],cancel,timeout=2)
        assert not gate.acquire(blocking=False)  # Another render's slot was not released.
    finally:timer.join();gate.release()


def test_capability_api_uses_validated_initialization(monkeypatch):
    monkeypatch.setattr(r,'_caps',None)
    caps=request('GET','/api/render/capabilities')
    assert caps.status_code==200,caps.text
    value=caps.json()
    assert value['libx264_initialized'] and value['filters']['ass']
    assert value['limits']['encoders']<=4 and 'nvenc_initialized' in value


def test_internal_progress_is_not_exposed_as_raw_logs(job):
    import app
    row=dict(clip_index=0,time_seconds=.5,duration=1,fraction=.5,frame=12,attempt=1)
    app.enqueue_output(io.BytesIO(('RENDER_PROGRESS '+json.dumps(row)+'\n').encode()),'quality-job')
    assert job['record']['logs']==[]
    assert request('GET','/api/status/quality-job').json()['render_progress']['0']==row


def test_overlay_frame_check_and_missing_layer_rejection(tmp_path,monkeypatch):
    import caption_renderer
    from ffmpeg_utils import escape_filter_value
    source=tmp_path/'source.mp4';output=tmp_path/'visible.mp4';ass=tmp_path/'captions.ass'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=0x304050:s=270x480:r=24:d=1',
        '-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True,timeout=10)
    caption_renderer.generate({'segments':[dict(start=0,end=.9,text='Visible caption.')]},0,1,str(ass),270,480)
    argv=command(source,output);argv[-1:-1]=['-vf',f"ass=filename='{escape_filter_value(str(ass))}'"]
    r.run(argv)
    receipt=json.loads(Path(str(output)+'.render.json').read_text())
    assert receipt['overlay']['status']=='PASS'
    with pytest.raises(ValueError,match='no measurable raster change'):
        r.overlay_check(argv,source,time.monotonic()+20)


def test_unknown_or_missing_dependencies_do_not_publish(tmp_path,monkeypatch):
    target=tmp_path/'output.mp4';target.write_bytes(b'keep')
    monkeypatch.setattr(r.subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError('ffmpeg')))
    with pytest.raises(FileNotFoundError):r.run(command('in.mp4',target))
    assert target.read_bytes()==b'keep' and not list(tmp_path.glob('.render-*'))


def test_matching_whole_source_avoids_video_encode_and_uses_cache(tmp_path,real_clip):
    source=real_clip('matching-source');edits=timeline_project.initial({},[dict(start=0,end=2)],None)['edits']
    edits['style']['enabled']=False
    kwargs=dict(edits=edits,rows=[],source=str(source),canonical=str(source),canonical_range=dict(start=0,end=2),
        size=(64,36),fps=24,audio=True,directory=tmp_path,cancel=threading.Event(),progress=lambda *a:None)
    output,cache=timeline_render.render(**kwargs)
    assert cache['source_passthrough_parts']==1
    assert not list(tmp_path.glob('editor_part_*.mp4.render.json'))  # copied, never transcoded
    _,again=timeline_render.render(**kwargs)
    assert again['segment_hits']==1 and again['clean_key']==cache['clean_key']
    assert q.streams(q.probe(output))[0]['codec_name']=='h264'


def test_failed_required_captions_are_blocked_but_silent_sources_remain_valid(monkeypatch):
    transcript={'segments':[dict(start=0,end=1,text='A complete sentence.')]}
    with pytest.raises(ValueError,match='Requested captions'):r.require_captions(transcript,0,1,True,False)
    r.require_captions({},0,1,True,False)
    r.require_captions(transcript,0,1,False,False)
    monkeypatch.setenv('RENDER_STRICT_OVERLAYS','0')
    r.require_captions(transcript,0,1,True,False)


def test_remotion_cancel_checks_actual_job_owner(job,monkeypatch):
    import app
    import httpx
    from types import SimpleNamespace
    posts=[]
    class Service:
        def __init__(self,*a,**k):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get(self,url):return SimpleNamespace(status_code=200,json=lambda:dict(jobId='quality-job',clipIndex=0))
        async def post(self,url):posts.append(url);return SimpleNamespace(json=lambda:dict(cancellationRequested=True))
    # Preserve the test client's httpx transport; intercept only the service client.
    original=httpx.AsyncClient
    def client(*args,**kwargs):return original(*args,**kwargs) if 'transport' in kwargs else Service()
    monkeypatch.setattr(httpx,'AsyncClient',client)
    assert request('POST','/api/render/example/cancel').status_code==200 and len(posts)==1
    posts.clear();job['record']['user_id']='owner';monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('POST','/api/render/example/cancel').status_code==404 and not posts


def test_nvenc_reprobe_after_runtime_cooldown(monkeypatch):
    calls=[];monkeypatch.setattr(e,'_probe_nvenc',lambda:calls.append(1) or True)
    e.nvenc_failed()
    assert not e.nvenc_available() and not calls
    monkeypatch.setattr(e,'_nvenc_retry_at',time.monotonic()-1)
    assert e.nvenc_available() and len(calls)==1


@pytest.mark.parametrize('field,wrong,code',[('codec_name','hevc','WRONG_VIDEO_CODEC'),
    ('pix_fmt','yuvj420p','WRONG_PIXEL_FORMAT')])
def test_explicit_export_codec_contract_rejects_wrong_format(real_clip,monkeypatch,field,wrong,code):
    source=real_clip();info=q.probe(source);info['streams'][0][field]=wrong
    expected=q.expectations(info);expected.update(video_codec='h264',pixel_format='yuv420p')
    monkeypatch.setattr(q,'probe',lambda *args,**kwargs:info)
    report=q.validate(source,'codec-contract',expected)
    assert not report['accepted'] and code in {problem['code'] for problem in report['problems']}
