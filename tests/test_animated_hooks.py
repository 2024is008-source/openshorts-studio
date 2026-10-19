import subprocess

import pytest
from pydantic import ValidationError

import hook_layer as h
from test_export_quality import real_clip  # noqa: F401


@pytest.mark.parametrize('text,category',[
    ('Can we finish the challenge?', 'challenge'), ('What is inside?', 'question'),
    ('I miss my family.', 'emotional'), ('That joke was funny!', 'funny'),
    ('It takes 20 seconds.', 'fact'), ('Look at this discovery!', 'curiosity'),
])
def test_source_grounded_categories_and_explainable_evidence(text,category):
    rows=[dict(text=text,start=.2,end=1.7,source_start=10.2,source_end=11.7)]
    decision=h.suggest(rows,5,hint='Unsupported million dollar prize',scenes=[.2],requested_kind=category)
    assert decision==h.suggest(rows,5,hint='Unsupported million dollar prize',scenes=[.2],requested_kind=category)
    assert decision['text']==text and decision['kind']==category
    assert decision['evidence'][0]['source_start']==10.2
    assert decision['end']==3 and 'scene boundary' in decision['reason']


@pytest.mark.parametrize('rows',[[],[dict(text='Missing times')],
    [dict(text='No punctuation',start=0,end=1)],
    [dict(text='Later complete sentence.',start=4,end=5)],
    [dict(text='Hello.',start=0,end=1)],
    [dict(text='We walked home.',start=0,end=1)],
    [dict(text='Too many words '*25+'.',start=0,end=2)],
    [dict(text='Bad timestamp.',start=float('nan'),end=2)]])
def test_missing_context_and_no_suitable_hook_are_safe(rows):
    assert h.suggest(rows,6) is None


def test_mapping_drops_cut_words_and_preserves_source_evidence():
    assert h.source_rows('bad transcript',[dict(start=0,end=3)])==[]
    transcript={'segments':[dict(words=[dict(word=' cut',start=9,end=10.2),
        dict(word=' Actual',start=10.2,end=10.5),dict(word=' quote.',start=10.5,end=10.9)])]}
    rows=h.source_rows(transcript,[dict(start=10,end=11),dict(start=10,end=11)])
    assert len(rows)==4 and rows[0]['source_start']==10.2
    assert rows[2]['start']==pytest.approx(1.2)
    assert h.grounded('ACTUAL\nquote.','Actual quote.')
    assert not h.grounded('I won a million dollars!','Actual quote.')
    assert not h.grounded('won a million dollars.','We never won a million dollars.')
    result=h.suggest([dict(text='Interrupted',start=0,end=.5,source_start=1,source_end=1.5),
        dict(text='What happened?',start=.5,end=1,source_start=20,source_end=20.5)],3)
    assert result['text']=='What happened?'


@pytest.mark.parametrize('change',[dict(start=-1),dict(end=0),dict(start=2,end=1),
    dict(end=float('inf')),dict(animation='unsafe'),dict(text='x'*301),dict(y=.9),dict(text='\x00')])
def test_invalid_layers_rejected(change):
    with pytest.raises(ValidationError):h.Layer.model_validate(dict(dict(text='Actual speech.',end=3),**change))


def test_safe_area_covers_motion_and_omits_when_no_band_is_clear():
    layer=dict(text='Actual speech.',start=0,end=3)
    assert h.placement(layer,[dict(start=0,end=2,x=.3,y=.05,width=.2,height=.15)])==.26
    assert h.placement(layer,[dict(start=0,end=2,x=.1,y=0,width=.8,height=.7)]) is None
    assert h.placement(layer,[dict(start=4,end=5,x=.1,y=0,width=.8,height=.7)])==.06
    assert h.ass_event(layer,1080,1920,faces=[dict(x=0,y=0,width=1,height=1)])==''


@pytest.mark.parametrize('animation',h.ANIMATIONS)
def test_animation_tags_and_safe_text_fitting(animation):
    event=h.ass_event(dict(text='A long headline ' * 12+'\nSpecial {\\pos(0,0)} & 100%!',start=.5,end=2.5,animation=animation),1080,1920)
    assert '0:00:00.50,0:00:02.50' in event
    assert r'\N' in event and r'{\pos(0,0)}' not in event
    assert len(event)<2000 and 'Hook3' in event
    expected={'fade':r'\fad','scale-pop':r'\fscx85','spring':r'\fscx105',
        'slide-up':r'\move','highlight-reveal':r'\clip','none':r'\pos'}
    assert expected[animation] in event


@pytest.mark.parametrize('fps',[24,30,60])
def test_real_animations_have_bounded_timing_and_keep_audio(real_clip,tmp_path,monkeypatch,fps):
    import export_quality as q
    monkeypatch.setenv('FFMPEG_ENCODER','libx264')
    source=real_clip('source',video=f'color=c=green:s=216x384:r={fps}:d=2')
    for animation in h.ANIMATIONS:
        output=tmp_path/f'{animation}.mp4'
        h.render(source,output,dict(text='Actual\nsource speech!',start=.5,end=1.5,animation=animation))
        video,audio=q.streams(q.probe(output))
        assert (video['width'],video['height'])==(216,384) and audio
        def frame(path,t):
            return subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],timeout=15)
        import numpy as np
        def difference(t):
            return np.abs(np.frombuffer(frame(source,t),dtype=np.uint8).astype(float)-np.frombuffer(frame(output,t),dtype=np.uint8)).mean()
        assert difference(.1)<2 and difference(1.8)<2
        assert difference(1.)>2


def test_no_font_download_and_missing_media_fail_safely(tmp_path,monkeypatch):
    import hooks
    monkeypatch.setattr(hooks,'download_font_if_needed',lambda:pytest.fail('No network font download'))
    assert h.ass_event(dict(text='Available source.',end=2),1080,1920)
    with pytest.raises(subprocess.SubprocessError):h.render(tmp_path/'missing.mp4',tmp_path/'out.mp4',dict(text='Source.',end=2))
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:b'{"streams":[]}')
    with pytest.raises(ValueError,match='readable'):h.render('damaged.mp4',tmp_path/'out.mp4',dict(text='Source.',end=2))


def test_auto_generation_reuses_speech_and_can_skip(monkeypatch,tmp_path):
    import main
    import hooks
    import caption_renderer
    monkeypatch.setattr(caption_renderer,'detect_face_regions',lambda *_:[])
    calls=[]
    monkeypatch.setattr(hooks,'add_hook_to_video',lambda *a,**k:calls.append((a,k)))
    clip=dict(start=0,end=5,viral_hook_text='Unsupported prize')
    assert main.auto_hook_clip(str(tmp_path/'clip.mp4'),clip,None,0,5) is None
    result=main.auto_hook_clip(str(tmp_path/'clip.mp4'),clip,
        {'segments':[dict(text='Can we finish?',start=0,end=2)]},0,5)
    assert result[1]['text']=='Can we finish?' and calls[0][1]['animation']=='fade'
    assert result[1]['grounding']['version']==1
    assert main.auto_hook_clip(str(tmp_path/'clip.mp4'),dict(clip,layout_ranges=[dict(start=0,end=3,layout='editorial')]),
        {'segments':[dict(text='Can we finish?',start=0,end=2)]},0,5) is None
