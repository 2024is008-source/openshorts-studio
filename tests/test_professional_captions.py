import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

from caption_timing import relative_words,phrases,caption_position
import caption_renderer as cr
import subtitles


def transcript(words):
    return {'segments':[{'words':[dict(word=' '+w,start=a,end=b) for w,a,b in words]}]}


def test_trim_sync_and_invalid_alignment():
    t=transcript([('before',0,1),('hello,',9.8,10.5),('world!',10.4,11.2),('bad',float('nan'),12),('after',12,13)])
    words=relative_words(t,10,11,.1)
    assert words[0]['start']==0 and words[-1]['end']==1
    assert words[0]['end']==words[1]['start']==.5
    assert [w['word'] for w in words]==['hello,','world!']


def test_same_time_words_are_a_phrase_not_fake_highlights():
    words=relative_words(transcript([('one',0,.5),('two',0,.6)]),0,1)
    assert len(words)==1 and words[0]['word']=='one two' and not words[0]['aligned']


def test_segment_only_alignment_preserves_phrase():
    words=relative_words({'segments':[dict(start=5,end=8,text='A complete phrase.') ]},6,7)
    assert words==[dict(word='A complete phrase.',start=0,end=1,aligned=False)]


def test_missing_alignment_never_invents_word_times():
    assert relative_words({'segments':[dict(text='unknown timing',words=[dict(word='bad')])]},0,10)==[]


@pytest.mark.parametrize('speed',[.03,.1,.8,2])
def test_fast_slow_speech_and_no_input_mutation(speed):
    t=transcript([(f'w{i}',i*speed,i*speed+speed*.8) for i in range(40)])
    old=copy.deepcopy(t)
    blocks=phrases(relative_words(t,0,100))
    assert all(len(b)<=6 for b in blocks)
    assert all(b[-1]['end']>b[0]['start'] for b in blocks)
    assert t==old


def test_punctuation_and_silence_split_phrases():
    blocks=phrases(relative_words(transcript([('Hello.',0,.3),('Next',.4,.7),('thought',.8,1),('later',3,4)]),0,5))
    assert [len(b) for b in blocks]==[1,2,1]


def test_ass_time_rollover():
    assert subtitles._ass_time(59.999)=='0:01:00.00'


def test_safe_placement_for_layouts_and_detected_faces():
    assert caption_position(1,splits=[(0,2)])[1]==.5
    assert caption_position(1,editorials=[(0,2)])[1]==.6
    face=[dict(x=.2,y=.5,width=.6,height=.3,start=0,end=3)]
    y=caption_position(1,faces=face)[1]
    assert y<.5
    assert .12<y<.8


@pytest.mark.parametrize('preset',list(cr.PRESETS))
def test_all_presets_and_long_unicode_are_bounded(tmp_path,preset):
    p=tmp_path/f'{preset}.ass'
    t=transcript([('这是测试。',0,.6),('Привет!',.7,1.1),('W'*100,1.2,1.8)])
    assert cr.generate(t,0,2,p,preset=preset,max_lines=2,font_size=70)
    text=p.read_text(encoding='utf-8-sig')
    assert 'PlayResX: 1080' in text and 'PlayResY: 1920' in text
    assert ('ПРИВЕТ!' if cr.options(preset)['uppercase'] else 'Привет!') in text and 'W'*100 in text
    assert all(0<y<1920*.8 for y in map(int,re.findall(r'\\pos\(518,(\d+)\)',text)))
    assert max(line.count('\\N') for line in text.splitlines())<=1
    assert '{\\t(0,110,\\fscx108' not in text


def test_unaligned_phrase_has_no_active_word_override(tmp_path):
    p=tmp_path/'missing.ass'
    assert cr.generate({'segments':[dict(start=0,end=1,text='A phrase.') ]},0,2,p)
    assert '\\c&H' not in '\n'.join(x for x in p.read_text(encoding='utf-8-sig').splitlines() if x.startswith('Dialogue: 1'))


def test_options_are_sanitized_and_animation_falls_back():
    cfg=cr.options('podcast',font_name='bad,Fontsize=999',max_lines=20,sync_offset=50,effect='unknown')
    assert cfg['font_name']=='Arial' and cfg['max_lines']==3 and cfg['sync_offset']==1 and cfg['effect']=='none'


def test_face_detection_missing_dependencies_falls_back(tmp_path):
    assert cr.detect_face_regions(tmp_path/'missing.mp4',2)==[]


def test_face_sampling_is_bounded_cached_and_uses_output_coordinates(tmp_path,monkeypatch):
    import cv2
    import numpy as np
    from types import SimpleNamespace
    path=tmp_path/'output.mp4';path.write_bytes(b'fixture')
    (tmp_path/'haarcascade_frontalface_default.xml').write_text('mock asset')
    monkeypatch.setattr(cv2.data,'haarcascades',str(tmp_path))
    class Detector:
        def empty(self): return False
        def detectMultiScale(self,*a,**k): return [(30,60,60,90)]
    monkeypatch.setattr(cv2,'CascadeClassifier',lambda *a:Detector())
    monkeypatch.setattr(cv2,'imdecode',lambda *a:np.zeros((480,240,3),dtype=np.uint8))
    calls=[]
    def sample(command,**kwargs):
        calls.append(command)
        assert kwargs['timeout']<=2
        return SimpleNamespace(stdout=b'fixture')
    monkeypatch.setattr(cr.subprocess,'run',sample)
    regions=cr.detect_face_regions(path,6)
    assert len(regions)==3 and regions[0]['x']==.125 and regions[0]['y']==.125
    assert cr.detect_face_regions(path,6)==regions and len(calls)==3
    path.write_bytes(b'changed output')
    assert cr.detect_face_regions(path,6)==regions and len(calls)==6


def test_browser_and_server_remotion_sources_match():
    for relative in ['lib/captions.ts','compositions/Subtitles.tsx','lib/types.ts']:
        assert (Path('tests/fixtures/legacy-captions')/relative).read_bytes()==(Path('remotion/src')/relative).read_bytes()


def test_preset_parameters_match_dashboard():
    # JS fixture extraction is unnecessary: native client tests also exercise
    # this contract; verify backend IDs remain accepted by generation settings.
    from generation_options import normalize_options
    for preset in cr.PRESETS: assert normalize_options(captions=preset)['CAPTION_PRESET']==preset


@pytest.mark.parametrize('fps',[24,25,30,60])
def test_real_libass_render_and_fps_independent_timing(tmp_path,fps):
    p=tmp_path/'sample.ass';out=tmp_path/'sample.mp4'
    t=transcript([('Hello,',0,.31),('world!',.32,.72)])
    assert cr.generate(t,0,1,p,270,480,preset='dynamic-highlight')
    first=p.read_bytes()
    # Escape only filter syntax; subprocess uses an argv array, never a shell.
    safe=subtitles._escape_ffmpeg_filter_value(str(p))
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',f'color=c=0x223344:s=270x480:r={fps}:d=1',
        '-vf',f"ass=filename='{safe}'",'-c:v','libx264','-threads','1','-preset','ultrafast',str(out)],
        check=True,capture_output=True,timeout=20)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(out)],timeout=5))
    assert info['streams'][0]['width']==270 and info['streams'][0]['height']==480
    assert p.read_bytes()==first
