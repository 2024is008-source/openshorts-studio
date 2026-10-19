"""TASK-007: generated deterministic media, including decoded AAC peak checks."""
import json
from pathlib import Path
import subprocess
import time

import pytest

import audio_mastering as a
import export_quality as q
from generation_options import normalize_options, RESUME_OPTIONS


@pytest.fixture(autouse=True)
def defaults(monkeypatch):
    for key in RESUME_OPTIONS:
        if key.startswith('AUDIO_'): monkeypatch.delenv(key,raising=False)


def media(tmp_path, expression, rate=48000, delay=0):
    path=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=96x160:r=24:d=3',
        '-itsoffset',str(delay),'-f','lavfi','-i',f'aevalsrc={expression}:s={rate}:d={3-delay}',
        '-map','0:v','-map','1:a','-c:v','libx264','-threads','1','-c:a','aac',str(path)],
        check=True,capture_output=True,timeout=15)
    return path


@pytest.mark.parametrize('expression,rate',[
    ('0.005*sin(2*PI*440*t)',48000),  # quiet dialogue surrogate
    ('0.85*sin(2*PI*440*t)',48000),   # loud
    ('0.07*sin(2*PI*440*t)+0.01*sin(2*PI*7811*t)',48000), # background noise
    ('if(lt(t,1.5),0.015*sin(2*PI*330*t),0.3*sin(2*PI*660*t))',48000), # speakers
    ('0.12*sin(2*PI*440*t)+0.08*sin(2*PI*110*t)',48000), # mixed music and speech
    ('0',48000),
    ('0.1*sin(2*PI*440*t)',22050),
    ('0.1*sin(2*PI*440*t)',44100),
    ('clip(2*sin(2*PI*440*t),-1,1)',48000), # preexisting flat tops
])
def test_real_encoded_loudness_and_peak(tmp_path,expression,rate):
    # Escape lavfi expression commas inside its quoted expression.
    path=media(tmp_path,"'"+expression+"'",rate)
    original=q.probe(path)
    report=a.master(path)
    if expression=='0':
        assert report['status']=='SILENT'
        assert q.probe(path)==original
    else:
        assert report['status']=='PASS'
        assert report['after']['true_peak_dbtp']<=-1.95
        assert not report['after']['possible_existing_clipping']
        assert abs(report['after']['integrated_lufs']+16)<1.6
        assert q.streams(q.probe(path))[1]['sample_rate']=='48000'
    assert report['attempts']<=2
    assert abs(float(q.streams(q.probe(path))[0]['duration'])-3)<.05


def test_delay_and_video_packets_are_preserved(tmp_path):
    path=media(tmp_path,'0.07*sin(2*PI*440*t)',delay=.25)
    def video_hash():
        return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v','-c','copy',
            '-f','hash','-hash','sha256','-'],check=True,capture_output=True,timeout=10).stdout
    before=video_hash();start=float(q.streams(q.probe(path))[1]['start_time'])
    a.master(path)
    assert video_hash()==before
    assert abs(float(q.streams(q.probe(path))[1]['start_time'])-start)<.06


def test_nonzero_container_clock_keeps_relative_sync(tmp_path):
    original=media(tmp_path,'0.03*sin(2*PI*440*t)',delay=.25)
    shifted=tmp_path/'shifted.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(original),'-c','copy',
        '-output_ts_offset','2',str(shifted)],check=True,capture_output=True,timeout=10)
    def offset(path):
        video,audio=q.streams(q.probe(path))
        return float(audio['start_time'])-float(video['start_time'])
    before=offset(shifted)
    assert a.master(shifted)['status']=='PASS'
    assert abs(offset(shifted)-before)<.06


def test_cache_no_repeat_processing_and_changed_file_invalidation(tmp_path,monkeypatch):
    path=media(tmp_path,'0.03*sin(2*PI*440*t)')
    first=a.master(path);stamp=q.fingerprint(path)
    monkeypatch.setattr(a,'measure',lambda *args,**kwargs:pytest.fail('valid receipt should avoid decoding'))
    assert a.master(path)==first and q.fingerprint(path)==stamp
    path.touch()
    with pytest.raises(BaseException,match='valid receipt'): a.master(path)


def test_fades_noise_and_explicit_ducked_music(tmp_path):
    path=media(tmp_path,'0.05*sin(2*PI*440*t)')
    music=tmp_path/'music.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=110:duration=1',str(music)],
                   check=True,capture_output=True,timeout=10)
    cfg=a.settings();cfg.update(fade=.1,noise=True)
    report=a.master(path,config=cfg,music=music)
    assert report['status']=='PASS' and report['after']['true_peak_dbtp']<=-1.95
    graph=a._graph(cfg,3,True)
    assert 'sidechaincompress' in graph and 'afftdn' in graph and 'afade' in graph


@pytest.mark.parametrize('kwargs',[dict(preset='bad'),dict(preset=[]),dict(target=float('nan')),dict(target=-5),
    dict(ceiling=0),dict(fade=-1),dict(noise='yes'),dict(fade='1;movie=secret')])
def test_invalid_controls(kwargs):
    with pytest.raises(ValueError): a.options(**kwargs)


def test_generation_settings_and_resume():
    result=normalize_options(audio_preset='dialogue',audio_target=-18,audio_peak=-3,audio_fade=.1,audio_noise=True)
    assert result['AUDIO_TARGET_LUFS']=='-18.0' and result['AUDIO_NOISE_REDUCTION']=='1'
    assert set(k for k in result if k.startswith('AUDIO_')) <= RESUME_OPTIONS


def test_bypass_keeps_original_bytes(tmp_path,monkeypatch):
    path=tmp_path/'fake.mp4';path.write_bytes(b'original')
    monkeypatch.setenv('AUDIO_PRESET','original')
    assert a.master(path)['status']=='DISABLED' and path.read_bytes()==b'original'
    monkeypatch.setenv('AUDIO_PRESET','natural');monkeypatch.setenv('AUDIO_NORMALIZE','0')
    assert a.master(path)['status']=='DISABLED'


def test_no_audio_is_valid(tmp_path):
    path=media(tmp_path,'0')
    silent=tmp_path/'noaudio.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(path),'-an','-c:v','copy',str(silent)],
                   check=True,capture_output=True,timeout=10)
    assert a.master(silent)['status']=='NO_AUDIO'


def test_failure_never_overwrites_and_retry_is_bounded(tmp_path,monkeypatch):
    path=media(tmp_path,'0.05*sin(2*PI*440*t)');before=path.read_bytes()
    real=a.measure
    def over_peak(*args,**kwargs):
        value=real(*args,**kwargs)
        if kwargs.get('prepared') is False: value['true_peak_dbtp']=1
        return value
    monkeypatch.setattr(a,'measure',over_peak)
    with pytest.raises(ValueError,match='two attempts'):a.master(path)
    assert path.read_bytes()==before
    assert not list(tmp_path.glob('.audio-master-*'))


def test_export_failure_blocks_completion_and_recheck_does_not_master(tmp_path,monkeypatch):
    path=tmp_path/'damaged.mp4';path.write_bytes(b'damaged')
    monkeypatch.setattr(a,'master',lambda *args,**kwargs:(_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(q.QualityError) as exc:q.enforce(path,'c',master_audio=True)
    assert exc.value.report['problems'][0]['code']=='AUDIO_MASTERING_FAILED'
    monkeypatch.setattr(a,'master',lambda *args,**kwargs:pytest.fail('read-only recheck'))
    with pytest.raises(q.QualityError):q.enforce(path,'c',force=True)


def test_analysis_parse_silence_and_clipping(monkeypatch):
    log=('silence_start: 1\nsilence_end: 2 | silence_duration: 1\nPeak level dB: 0.000000\nPeak count: 800\n'
         +json.dumps(dict(input_i='-16',input_tp='0',input_lra='1',input_thresh='-26',target_offset='0')))
    monkeypatch.setattr(a,'_run',lambda *args:subprocess.CompletedProcess([],0,stderr=log.encode()))
    result=a.measure('unused',a.settings(),3,time.monotonic()+5)
    assert result['silences']==[dict(start=1,end=2)] and result['possible_existing_clipping']


def test_interrupted_encode_reuses_measurements(tmp_path,monkeypatch):
    path=media(tmp_path,'0.03*sin(2*PI*440*t)');before=path.read_bytes()
    run=a._run
    def interrupted(command,deadline):
        if command[-1].endswith('.mp4'): raise subprocess.TimeoutExpired('ffmpeg',1)
        return run(command,deadline)
    monkeypatch.setattr(a,'_run',interrupted)
    with pytest.raises(subprocess.TimeoutExpired):a.master(path)
    assert path.read_bytes()==before
    assert Path(str(path)+'.audio-analysis.json').exists()
    measure=a.measure
    monkeypatch.setattr(a,'_run',run)
    def cached_input(*args,**kwargs):
        assert kwargs.get('prepared') is False, 'input measurement should be cached'
        return measure(*args,**kwargs)
    monkeypatch.setattr(a,'measure',cached_input)
    assert a.master(path)['status']=='PASS'


def test_project_settings_reopen_without_global_env_changes(tmp_path,monkeypatch):
    monkeypatch.setenv('AUDIO_TARGET_LUFS','-16')
    (tmp_path/'source_metadata.json').write_text(json.dumps(dict(job_options={
        'AUDIO_TARGET_LUFS':'-18','AUDIO_PRESET':'dialogue'})))
    assert a.export_settings(tmp_path/'export.mp4')['target']==-18
    assert a.settings()['target']==-16


@pytest.mark.parametrize('contents',['[]','{"job_options": []}','{"job_options": {"AUDIO_PRESET": []}}'])
def test_malformed_project_audio_settings(tmp_path,contents):
    (tmp_path/'source_metadata.json').write_text(contents)
    with pytest.raises(ValueError): a.export_settings(tmp_path/'clip.mp4')


def test_malformed_cached_measurements_are_not_reused():
    assert not a._valid_measurements({'silent':False,'possible_existing_clipping':False,
        'integrated_lufs':'movie=private-file','true_peak_dbtp':-3,'lra':2,'threshold':-26,'offset':0,'silences':[]})


def test_browser_export_returns_exact_mastered_media(job,real_clip):
    # Existing authenticated ownership/path/size protections also apply here.
    from test_export_quality_api import request
    path=real_clip('browser-master')
    response=request('POST','/api/quality/browser-export',data={
        'job_id':'quality-job','clip_index':'0','master_audio':'true',
        'expected':json.dumps(dict(width=64,height=36,fps=24,duration=2))},
        files={'file':('export.mp4',path.read_bytes(),'video/mp4')})
    assert response.status_code==200, response.text
    report=response.json()
    assert report['audio_mastering']['status']=='PASS'
    assert report['audio_mastering']['after']['true_peak_dbtp']<=-1.95
    target=job['directory']/report['mastered_video_url'].split('/')[-1]
    assert target.is_file() and q.read_report(target)['accepted']
    assert not list(job['uploads'].iterdir())
    before=target.read_bytes()
    rechecked=q.enforce(target,'clip_1',force=True)
    assert rechecked['audio_mastering']['after']==report['audio_mastering']['after']
    assert target.read_bytes()==before


# Reuse the existing real-media/API fixture instead of duplicating app setup.
from test_export_quality_api import job  # noqa: E402,F401
from test_export_quality import real_clip  # noqa: E402,F401
