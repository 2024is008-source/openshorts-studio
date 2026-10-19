"""Regression for loudnorm tails and actionable synchronization failures."""
import subprocess

import pytest
import audio_mastering as audio
import export_quality as quality
from test_audio_mastering import media


def test_filter_tail_is_bounded_to_original_audio_not_video(tmp_path,monkeypatch):
    original=media(tmp_path,'0.04*sin(2*PI*440*t)',delay=.25)
    path=tmp_path/'short-audio.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(original),'-c:v','copy',
                    '-af','atrim=duration=1.5','-c:a','aac',str(path)],
                   check=True,capture_output=True,timeout=10)
    before=quality.streams(quality.probe(path))
    normalizer=audio._normalizer
    # Deterministically reproduce a processing tail before the new final trim.
    monkeypatch.setattr(audio,'_normalizer',lambda *a:normalizer(*a)+',apad=pad_dur=0.08')
    result=audio.master(path,config=audio.settings({'AUDIO_PRESET':'natural','AUDIO_MASTERING':'1','AUDIO_NORMALIZE':'1'}))
    after=quality.streams(quality.probe(path))
    assert result['status']=='PASS' and result['after']['true_peak_dbtp']<=-1.95
    for field in ('start_time','duration'):
        assert abs(float(before[1][field])-float(after[1][field]))<=.06
    assert float(after[1]['duration'])<2
    assert before[0]['duration']==after[0]['duration']


def test_sync_failure_report_retains_measured_reason_without_raw_command(tmp_path,monkeypatch):
    path=tmp_path/'failed.mp4';path.write_bytes(b'preserved')
    def fail(*a,**k):raise audio.TimingError('audio','duration',59.02,59.1)
    monkeypatch.setattr(audio,'master',fail)
    with pytest.raises(quality.QualityError) as exc:
        quality.enforce(path,'failed-job',master_audio=True)
    report=exc.value.report
    assert report['measurements']['audio_mastering_timing']==dict(stream='audio',field='duration',
        before=59.02,after=59.1,difference_seconds=.08,tolerance_seconds=.06)
    assert '+0.080000s' in report['problems'][0]['message']
    assert report['status']=='FAIL' and not report['accepted']
    assert path.read_bytes()==b'preserved'
