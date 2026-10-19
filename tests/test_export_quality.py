import copy
import json
import subprocess
from pathlib import Path

import pytest

import export_quality as q


@pytest.mark.parametrize('content', ['[]', 'null', '"broken"', '{'])
def test_malformed_sidecars_are_cache_misses(tmp_path, content):
    path=tmp_path/'clip.mp4'
    Path(str(path)+q.SUFFIX).write_text(content)
    assert q.read_report(path,fresh=False) is None


def metadata(audio=True):
    result={'format':{'duration':'2','bit_rate':'100000'},'streams':[
        dict(codec_type='video',width=64,height=36,avg_frame_rate='24/1',
             r_frame_rate='24/1',duration='2',start_time='0',sample_aspect_ratio='1:1')]}
    if audio: result['streams'].append(dict(codec_type='audio',duration='2',start_time='0'))
    return result


@pytest.fixture
def mock_media(tmp_path,monkeypatch):
    path=tmp_path/'clip.mp4';path.write_bytes(b'fake-video')
    monkeypatch.setattr(q,'probe',lambda *a,**k:metadata())
    monkeypatch.setattr(q,'_frames',lambda *a,**k:([bytes([100])*64]*4,8,8))
    monkeypatch.setattr(q,'_audio',lambda *a,**k:dict(rms_dbfs=-20,peak=.2,clipping_fraction=0))
    return path


def codes(report): return {p['code'] for p in report['problems']}


@pytest.mark.parametrize('change,code',[
    ('missing_video','MISSING_VIDEO'),('missing_audio','MISSING_AUDIO'),
    ('resolution','WRONG_DIMENSIONS'),('aspect','WRONG_ASPECT'),
    ('fps','WRONG_FPS'),('duration','WRONG_DURATION'),('audio_timing','AV_TIMING')])
def test_technical_failures_block_export(mock_media,monkeypatch,change,code):
    info=metadata(); expected=q.expectations(info)
    if change=='missing_video': info['streams']=info['streams'][1:]
    elif change=='missing_audio': info['streams']=info['streams'][:1]
    elif change=='resolution': info['streams'][0]['width']=32
    elif change=='aspect': info['streams'][0]['sample_aspect_ratio']='2:1'
    elif change=='fps': info['streams'][0]['avg_frame_rate']='60/1'
    elif change=='duration': info['streams'][0]['duration']='1'
    elif change=='audio_timing': info['streams'][1]['start_time']='1'
    monkeypatch.setattr(q,'probe',lambda *a,**k:info)
    report=q.validate(mock_media,'c1',expected)
    assert report['status']=='FAIL' and not report['accepted']
    assert code in codes(report)


def test_cache_fingerprint_contract_and_revalidation(mock_media,monkeypatch):
    expected=q.expectations(metadata())
    report=q.enforce(mock_media,'c1',expected)
    assert report['status']=='PASS'
    monkeypatch.setattr(q,'validate',lambda *a,**k:pytest.fail('cache should avoid decoding'))
    assert q.enforce(mock_media,'c1',expected)['status']=='PASS'
    mock_media.write_bytes(b'changed')
    assert q.read_report(mock_media) is None
    assert q.read_report(mock_media,fresh=False)['expected']==expected


def test_probe_retry_is_bounded(mock_media,monkeypatch):
    calls=[]
    def timeout(*a,**k):
        calls.append(1);raise subprocess.TimeoutExpired('ffprobe',10)
    monkeypatch.setattr(q,'probe',timeout)
    report=q.validate(mock_media,'c1')
    assert len(calls)==2 and report['attempts']==2 and report['status']=='FAIL'
    assert 'PROBE_TIMEOUT' in codes(report)


def test_damaged_file_not_automatically_retried(mock_media,monkeypatch):
    calls=[]
    def bad(*a,**k):
        calls.append(1);raise subprocess.CalledProcessError(1,'ffprobe')
    monkeypatch.setattr(q,'probe',bad)
    report=q.validate(mock_media,'c1')
    assert len(calls)==1 and 'INVALID_CONTAINER' in codes(report)


def test_missing_empty_unreadable_files(tmp_path,monkeypatch):
    path=tmp_path/'bad.mp4'
    assert 'UNREADABLE_FILE' in codes(q.validate(path,'c'))
    path.touch()
    assert 'EMPTY_FILE' in codes(q.validate(path,'c'))
    monkeypatch.setattr(q,'fingerprint',lambda _:(_ for _ in ()).throw(PermissionError()))
    assert 'UNREADABLE_FILE' in codes(q.validate(path,'c'))


def test_decode_failures_and_resource_timeout(mock_media,monkeypatch):
    def bad(*a,**k): raise subprocess.CalledProcessError(1,'ffmpeg')
    monkeypatch.setattr(q,'_frames',bad)
    assert 'DECODE_ERROR' in codes(q.validate(mock_media,'c'))
    monkeypatch.setattr(q,'_frames',lambda *a,**k: (_ for _ in ()).throw(subprocess.TimeoutExpired('ffmpeg',1)))
    assert 'SAMPLING_TIMEOUT' in codes(q.validate(mock_media,'c'))


def test_expected_speech_silence_and_clipping_warn(mock_media,monkeypatch):
    monkeypatch.setattr(q,'_audio',lambda *a,**k:dict(rms_dbfs=-100,peak=0,clipping_fraction=0))
    report=q.validate(mock_media,'c',q.expectations(metadata(),speech_expected=True))
    assert report['status']=='WARNING' and 'UNEXPECTED_SILENCE' in codes(report)
    assert q.validate(mock_media,'c',q.expectations(metadata()))['status']=='PASS'
    monkeypatch.setattr(q,'_audio',lambda *a,**k:dict(rms_dbfs=0,peak=1,clipping_fraction=.5))
    assert 'AUDIO_CLIPPING' in codes(q.validate(mock_media,'c'))


def test_intentional_dark_static_source_is_not_failed(mock_media,monkeypatch):
    monkeypatch.setattr(q,'_frames',lambda *a,**k:([bytes(64)]*4,8,8))
    report=q.validate(mock_media,'c',reference=mock_media)
    assert report['status']=='PASS'
    assert report['measurements']['video_samples'][0]['blank']


def test_unexpected_borders_and_freeze_have_timestamps(mock_media,monkeypatch):
    ref=mock_media.with_name('source.mp4');ref.write_bytes(b'source')
    image=bytes([0]*8+[100]*48+[0]*8)
    monkeypatch.setattr(q,'_frames',lambda path,*a,**k:
        ([bytes([50])*64,bytes([100])*64]*2,8,8) if path==ref else ([image]*4,8,8))
    report=q.validate(mock_media,'c',reference=ref)
    assert {'POSSIBLE_FREEZE','DARK_BORDERS'} <= codes(report)
    assert all('action' in p and p['timestamps'] for p in report['problems'])


def test_sampling_covers_endpoints_periods_and_scenes():
    ts=q.sample_times(30,[3,7,12,21,29],8)
    assert 0 in ts and 29.5 in ts and 14.75 in ts
    assert len(ts)<=8 and any(t in (3,7,12,21,29) for t in ts)


@pytest.fixture
def real_clip(tmp_path):
    import shutil
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): pytest.skip('FFmpeg required')
    def make(name='real',audio='sine=frequency=440:sample_rate=48000:duration=2',video='color=c=green:s=64x36:r=24:d=2'):
        path=tmp_path/f'{name}.mp4'
        cmd=['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',video]
        if audio: cmd+=['-f','lavfi','-i',audio,'-c:a','aac']
        cmd+=['-c:v','libx264','-pix_fmt','yuv420p',str(path)]
        subprocess.run(cmd,check=True,capture_output=True,timeout=30)
        return path
    return make


def test_real_valid_export_and_report(real_clip):
    path=real_clip()
    report=q.enforce(path,'real',q.expectations(q.probe(path)))
    assert report['status']=='PASS'
    assert report['measurements']['bitrate']>0
    assert report['measurements']['audio_samples']
    assert json.loads(Path(str(path)+q.SUFFIX).read_text())['clip_id']=='real'


def test_real_silent_no_audio_and_dark_exports(real_clip):
    for name,audio,video in [('noaudio',None,'color=c=green:s=64x36:r=24:d=2'),
        ('silent','anullsrc=r=48000:cl=mono:d=2','color=c=black:s=64x36:r=24:d=2')]:
        path=real_clip(name,audio,video)
        expected=q.expectations(q.probe(path))
        report=q.validate(path,name,expected,reference=path)
        assert report['status']=='PASS'


def test_real_truncated_container_is_rejected(real_clip):
    path=real_clip(); path.write_bytes(path.read_bytes()[:128])
    assert q.validate(path,'damaged')['status']=='FAIL'


def test_real_missing_expected_audio_is_rejected(real_clip):
    path=real_clip(audio=None)
    expected=q.expectations(q.probe(path));expected['audio_expected']=True
    assert 'MISSING_AUDIO' in codes(q.validate(path,'bad-audio',expected))


def test_real_short_audio_is_rejected(real_clip):
    path=real_clip('short-audio',audio='sine=frequency=440:sample_rate=48000:duration=1')
    assert 'AV_TIMING' in codes(q.validate(path,'short-audio',q.expectations(q.probe(path))))


def test_anamorphic_source_contract_preserves_display_aspect(mock_media,monkeypatch):
    info=metadata();info['streams'][0]['sample_aspect_ratio']='2:1'
    monkeypatch.setattr(q,'probe',lambda *a,**k:info)
    expected=q.expectations(info)
    assert expected['aspect']==64*2/36
    assert q.validate(mock_media,'anamorphic',expected)['status']=='PASS'


def test_required_sampling_budget_and_configuration_are_bounded(monkeypatch):
    monkeypatch.setenv('QUALITY_MAX_SAMPLES','100000')
    monkeypatch.setenv('QUALITY_TIMEOUT_SECONDS','100000')
    monkeypatch.setenv('QUALITY_AV_TOLERANCE','nan')
    limits=q.thresholds()
    assert limits['max_samples']==12 and limits['budget_seconds']==60
    assert limits['av_seconds']==.35


def test_mutating_file_is_not_accepted(mock_media,monkeypatch):
    def frames(*a,**k):
        mock_media.write_bytes(mock_media.read_bytes()+b'x')
        return [bytes([100])*64]*4,8,8
    monkeypatch.setattr(q,'_frames',frames)
    assert 'FILE_CHANGED' in codes(q.validate(mock_media,'changing'))


def test_failed_cli_reference_produces_structured_fail(tmp_path):
    import sys
    response=subprocess.run([sys.executable,'export_quality.py','--input',str(tmp_path/'none.mp4'),
        '--reference',str(tmp_path/'missing-source.mp4')],capture_output=True,timeout=20)
    report=json.loads(response.stdout)
    assert response.returncode==1 and report['status']=='FAIL' and not report['accepted']


def test_silence_compared_to_active_reference_is_reported(mock_media,monkeypatch):
    ref=mock_media.with_name('source.mp4');ref.write_bytes(b'source')
    monkeypatch.setattr(q,'_audio',lambda path,*a,**k:dict(
        rms_dbfs=-20 if path==ref else -100,peak=.2 if path==ref else 0,clipping_fraction=0))
    report=q.validate(mock_media,'muted',reference=ref)
    assert 'UNEXPECTED_SILENCE' in codes(report) and report['accepted']


def test_stereo_phase_cancellation_is_not_mistaken_for_silence(real_clip):
    path=real_clip('phase','aevalsrc=0.2*sin(2*PI*440*t)|-0.2*sin(2*PI*440*t):s=48000:d=2')
    expected=q.expectations(q.probe(path),speech_expected=True)
    report=q.validate(path,'stereo',expected)
    assert report['status']=='PASS'
    assert all(s['rms_dbfs']>-40 for s in report['measurements']['audio_samples'])


def test_white_blank_frames_remain_reviewable_without_false_hard_failure(mock_media,monkeypatch):
    monkeypatch.setattr(q,'_frames',lambda *a,**k:([bytes([255])*64]*4,8,8))
    assert 'BLANK_FRAMES' in codes(q.validate(mock_media,'white'))
    assert q.validate(mock_media,'white',reference=mock_media)['status']=='PASS'


def test_extreme_dimensions_fail_before_decoding(mock_media,monkeypatch):
    info=metadata();info['streams'][0].update(width=100000,height=100000)
    monkeypatch.setattr(q,'probe',lambda *a,**k:info)
    monkeypatch.setattr(q,'_frames',lambda *a,**k:pytest.fail('unsafe size must not decode'))
    assert 'RESOURCE_LIMIT' in codes(q.validate(mock_media,'oversize'))


def test_cli_force_revalidation_retains_the_original_contract(real_clip):
    import sys
    path=real_clip('original')
    q.enforce(path,'clip_1',q.expectations(q.probe(path)))
    replacement=real_clip('wrong-size',video='color=c=green:s=80x36:r=24:d=2')
    path.write_bytes(replacement.read_bytes())
    response=subprocess.run([sys.executable,'export_quality.py','--input',str(path),'--force'],
        capture_output=True,timeout=20)
    report=json.loads(response.stdout)
    assert response.returncode==1 and 'WRONG_DIMENSIONS' in codes(report)
    assert report['expected']['width']==64
