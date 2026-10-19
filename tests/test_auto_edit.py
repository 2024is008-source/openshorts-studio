import copy
import json
from pathlib import Path
import subprocess

import pytest

import auto_edit as a
import editing_director as director
import export_quality as quality
from test_export_quality import real_clip  # noqa: F401


def plan(kind='general'):
    return dict(duration=3.,kind=kind,segments=[dict(source_start=10.,source_end=13.)],
        shots=[dict(start=0.,end=3.,source_start=10.,source_end=13.,renderer='TRACK',
            faces=[dict(x=145.,y=55.,width=20.,height=25.)],protected_regions=[],
            keyframes=[dict(time=0.,x=110.,y=0.,width=100.,height=180.)])],
        captions=[dict(start=.5,end=1.,source_start=10.5,source_end=11.,text='100',aligned=True)])


def observation(kind='surprise',confidence=.95,quote='100'):
    return {'moments':[{'editing_cues':[dict(kind=kind,start=10.5,end=12.,
        evidence='The speaker reveals the measured result aloud.',quote=quote,confidence=confidence)]}]}


def manual(kind='smooth_zoom_in',start=.5,end=1.5):
    settings=a.generate(plan())
    settings['effects']=[a.Effect(id='manual',type=kind,category=a.category(kind),source_scene='scene-0',
        start=start,end=end,duration=end-start,origin='manual',reason='Local authorized test cue.',confidence=1.).model_dump(mode='json')]
    return settings


def test_grounded_decisions_are_deterministic_and_not_periodic():
    assert a.generate(plan())['effects']==[]
    first=a.generate(plan(),observation());assert first==a.generate(plan(),observation())
    assert {e['type'] for e in first['effects']}=={'fast_punch_in','keyword_highlight'}
    assert all(.5<=e['start']<e['end']<=2 for e in first['effects'])
    assert a.generate(plan(),observation(confidence=.4))['effects']==[]


@pytest.mark.parametrize('kind',['emotional','general'])
def test_serious_speech_preserves_pauses_and_does_not_invent_emotions(kind):
    source=observation('serious') if kind=='general' else observation('reaction')
    result=a.generate(plan(kind),source)
    assert result['effects']==[] and result['skipped']


def test_unsafe_faces_objects_and_shared_layout_veto_extra_zoom():
    for change in ('face','object','layout'):
        p=plan()
        if change=='face':p['shots'][0]['faces'][0]['x']=110
        if change=='object':p['shots'][0]['protected_regions']=[dict(x=109,y=0,width=80,height=80)]
        if change=='layout':p['shots'][0]['renderer']='GENERAL'
        result=a.generate(p,observation(quote='invented quote'))
        assert result['effects']==[] and result['skipped']


def test_manual_override_regeneration_and_category_disable():
    value=manual();value['effects'][0]['intensity']=.2
    result=a.generate(plan(),observation(),value)
    assert next(e for e in result['effects'] if e['id']=='manual')['intensity']==.2
    result['zoom']=False
    assert all(e['category']!='camera' for e in a.active(result))
    result['enabled']=False;assert a.active(result)==[]


def test_bad_timestamps_conflicts_and_unsupported_effects_fail_safely():
    value=manual();value['effects'][0]['end']=4;value['effects'][0]['duration']=3.5
    with pytest.raises(ValueError):a.normalize(value,3)
    value=manual();value['effects'][0]['intensity']=float('nan')
    with pytest.raises(ValueError):a.normalize(value,3)
    value=manual('freeze_frame');assert a.active(value)==[]
    value=manual();value['limits']['max_effects']=0;assert a.active(value)==[]
    value=manual();duplicate=copy.deepcopy(value['effects'][0]);duplicate['id']='another';value['effects'].append(duplicate)
    assert len(a.active(a.normalize(value,3)))==1


def test_trim_reorder_preserves_source_correspondence_and_skips_partial_animations():
    value=manual()
    result=a.retime(value,[dict(start=11.,end=13.),dict(start=10.,end=11.)])
    assert result['effects']==[]  # Animation straddles the edit join, so neither half plays.
    result=a.retime(value,[dict(start=10.25,end=13.)])
    checked=a.normalize(result,2.75)
    assert checked['effects'][0]['start']==.25
    assert checked['effects'][0]['origin']=='manual'
    assert a.retime(checked,[dict(start=10.25,end=13.)])==checked


@pytest.mark.parametrize('easing',a.EASINGS)
def test_easing_has_fixed_endpoints_and_is_frame_rate_independent(easing):
    assert a.ease(0,easing)==pytest.approx(0)
    assert a.ease(1,easing)==pytest.approx(1)
    assert a.ease(12/24,easing)==a.ease(30/60,easing)
    assert all(-.001<=a.ease(i/100,easing)<=1.06 for i in range(101))


def test_text_emphasis_requires_exact_retained_quote():
    value=a.generate(plan(),observation())
    transcript={'segments':[dict(words=[dict(word=' 100',start=.5,end=1.)])]}
    assert a.emphasize(transcript,value)['segments'][0]['words'][0]['emphasis']
    assert 'emphasis' not in transcript['segments'][0]['words'][0]
    assert not a.emphasize({'segments':[dict(words=[dict(word='wrong',start=.5,end=1.)])]},value)['segments'][0]['words'][0].get('emphasis')


@pytest.mark.parametrize('kind',sorted(a.CAMERA|a.VIDEO))
def test_actual_filters_preserve_frame_count_and_audio_sync(tmp_path,real_clip,kind):
    source=real_clip('effect-'+kind)
    value=manual(kind)
    target=tmp_path/'effect.mp4'
    def run(cmd):subprocess.run(cmd,check=True,capture_output=True,timeout=45)
    result=a.render(source,target,value,(64,36),24.,run,['-c:v','libx264','-pix_fmt','yuv420p'])
    assert result==str(target)  # A failed filter must not quietly pass this test via fallback.
    info=quality.probe(target);video,audio=quality.streams(info)
    assert audio and abs(float(info['format']['duration'])-2)<.15
    assert abs(quality.rate(video['avg_frame_rate'])-24)<.001
    assert abs(float(audio['duration'])-float(video['duration']))<.15


def test_optional_filter_failure_has_one_bounded_fallback(tmp_path,real_clip):
    source=real_clip();calls=[]
    def fail(cmd):calls.append(cmd);raise subprocess.CalledProcessError(1,cmd)
    assert a.render(source,tmp_path/'bad.mp4',manual(),(64,36),24.,fail,[])==str(source)
    assert len(calls)==1 and Path(str(source)+'.effects-skipped.json').is_file()


def test_settings_survive_saved_project_normalization():
    import timeline_project as p
    edits=p.initial({},[dict(start=10,end=13)],None)['edits'];edits['auto_edit']=manual()
    checked=p.normalize(edits,20,[])
    assert checked==p.normalize(json.loads(json.dumps(checked)),20,[])


@pytest.mark.parametrize('kind',['kinetic_captions','word_pop','text_reveal'])
def test_timed_caption_animation_uses_existing_ass_renderer(tmp_path,kind):
    import caption_renderer
    config=manual(kind,start=0,end=2)
    transcript={'segments':[dict(start=0,end=2,words=[dict(word=' One',start=.1,end=.5,aligned=True),dict(word=' example',start=.6,end=1.5,aligned=True)])]}
    path=tmp_path/'captions.ass'
    assert caption_renderer.generate(transcript,0,2,str(path),effect='none',auto_effects=a.active(config))
    content=path.read_text(encoding='utf-8-sig')
    assert 'Dialogue:' in content and 'example' in content
    assert ('\\alpha&HFF&' in content) if kind=='text_reveal' else ('\\t(' in content)


def test_effect_only_delivery_survives_without_captions_or_hooks(tmp_path,real_clip,monkeypatch):
    source=real_clip('no-captions')
    monkeypatch.setenv('AUTO_HOOK','0');monkeypatch.setenv('AUTO_CAPTIONS','0')
    decisions=director.compile_plan(media=str(source),width=64,height=36,fps=24.,out_size=(64,36),
        ranges=[(0,48,'TRACK')],xs=[0]*48,ys=[0]*48,crop_size=(64,36),subjects={0:[[27,12,5,8]]})
    config=decisions['auto_edit'];config['effects']=manual()['effects']
    output=tmp_path/'effect-only.mp4'
    assert director.render_layers(str(source),str(output),decisions)
    assert output.is_file() and output.read_bytes()!=source.read_bytes()


def test_actual_nvenc_effect_export_with_cpu_fallback(tmp_path,real_clip,monkeypatch):
    import ffmpeg_utils
    import reframe_v2
    monkeypatch.setenv('FFMPEG_ENCODER','nvenc')
    encoder=reframe_v2.director_encoder(720,1280)
    source=real_clip('nvenc-effects');target=tmp_path/'gpu.mp4'
    # The effect stage expects the existing compositor's output size as its input.
    prepared=tmp_path/'prepared.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(source),'-vf','scale=720:1280','-c:v','libx264','-threads','2','-c:a','copy',str(prepared)],check=True,capture_output=True,timeout=45)
    def run(cmd):subprocess.run(cmd,check=True,capture_output=True,timeout=45)
    assert a.render(prepared,target,manual(),(720,1280),24.,run,encoder)==str(target)
    info=quality.probe(target)
    assert quality.streams(info)[0]['width']==720
    if ffmpeg_utils.nvenc_available():assert 'h264_nvenc' in encoder


def test_text_only_effect_edit_invalidates_captions_but_reuses_video(tmp_path,real_clip):
    import threading
    import timeline_project
    import timeline_render
    source=real_clip('caption-cache')
    edits=timeline_project.initial({},[dict(start=0,end=2)],None)['edits']
    edits['auto_edit']=manual('word_pop',start=.2,end=1.8)
    rows=timeline_project.captions({'segments':[dict(start=.2,end=1.8,text='A local caption.')]})
    args=dict(edits=edits,rows=rows,source=str(source),canonical=str(source),canonical_range=dict(start=0,end=2),
        size=(64,36),fps=24.,audio=True,directory=tmp_path,cancel=threading.Event(),progress=lambda *a:None)
    first,cache=timeline_render.render(**args)
    edits['auto_edit']['effects'][0]['type']='text_reveal'
    second,updated=timeline_render.render(**args)
    assert first!=second and updated['segment_hits']==1
    assert updated['clean_key']==cache['clean_key']
    assert not updated['effects_applied']  # Text belongs to the caption stage.


def test_spoken_number_can_span_a_picture_cut_without_losing_its_real_timing():
    source=plan();source['captions'][0].update(start=.9,end=1.3)
    first=source['shots'][0];first.update(end=1.,source_end=11.,segment_index=0)
    second=copy.deepcopy(first);second.update(start=1.,end=3.,source_start=11.,source_end=13.)
    source['shots'].append(second)
    analysis=observation('number');analysis['moments'][0]['editing_cues'][0].update(start=10.5,end=11.5)
    result=a.generate(source,analysis)
    effects=[e for e in result['effects'] if e['type']=='number_highlight']
    assert len(effects)==1 and effects[0]['source_scene']=='scene-1'
    assert effects[0]['start']>=1 and effects[0]['duration']>=result['limits']['min_duration']-.001
    words={'segments':[dict(words=[dict(word=' 100',start=.9,end=1.3)])]}
    assert a.emphasize(words,result)['segments'][0]['words'][0]['emphasis']


def test_provider_number_label_without_a_number_is_not_converted_to_generic_emphasis():
    source=plan();source['captions'][0]['text']='This time, yes.'
    result=a.generate(source,observation('number',quote='This time, yes.'))
    assert result['effects']==[] and result['skipped'][0]['type']=='number_highlight'


def test_punctuation_is_not_a_grounding_failure():
    speech=[dict(text='oh,',start=.5,end=1.)]
    assert a.aligned_quote(speech,'Oh!',.5,1.)==(.5,1.)


def test_sentence_across_picture_cuts_keeps_grounded_text_effects():
    p=plan();p['shots'][0].update(renderer='GENERAL',end=1.5,source_end=11.5,segment_index=0)
    second=copy.deepcopy(p['shots'][0]);second.update(start=1.5,end=3.,source_start=11.5,source_end=13.)
    p['shots'].append(second)
    p['captions']=[dict(text=t,start=i*.4+.1,end=i*.4+.45,aligned=True)
        for i,t in enumerate(['You','have','successfully','extracted','the','DNA.'])]
    observed=observation('explanation',quote='You have successfully extracted the DNA!')
    result=a.generate(p,observed)
    effects=[e for e in a.active(result) if e['category']=='text']
    assert len(effects)==2
    assert all(e['category']!='camera' for e in a.active(result))
    assert all(e['start']>=next(s['start'] for s in result['scenes'] if s['id']==e['source_scene']) and
               e['end']<=next(s['end'] for s in result['scenes'] if s['id']==e['source_scene']) for e in effects)


def test_matching_quote_fragment_never_invents_missing_provider_words():
    speech=[dict(text=w,start=i*.2,end=i*.2+.2) for i,w in enumerate('You have successfully extracted the DNA'.split())]
    match=a.grounded_quote(speech,'Wait! You have successfully extracted the DNA.',0,1.2)
    assert match and match[2]=='you have successfully extracted the dna'
    assert a.grounded_quote(speech,'Completely invented unrelated statement',0,1.2) is None


def test_spoken_number_is_anchored_to_audio_before_assigning_picture_shot():
    p=plan();p['shots'][0].update(renderer='GENERAL',end=1.,source_end=11.,segment_index=0)
    second=copy.deepcopy(p['shots'][0]);second.update(start=1.,end=3.,source_start=11.,source_end=13.)
    p['shots'].append(second)
    p['captions']=[dict(text='million',start=.1,end=.65,aligned=True),dict(text='dollars,',start=.65,end=.95,aligned=True)]
    analysis=observation('number',quote='For a million dollars we have the fastest car')
    analysis['moments'][0]['editing_cues'][0].update(start=11.8,end=12.5)
    effects=[e for e in a.active(a.generate(p,analysis)) if e['type']=='number_highlight']
    assert len(effects)==1 and effects[0]['source_scene']=='scene-0'
    assert effects[0]['parameters']['quote']=='million dollars'


def test_emphasis_handles_sentence_segments_and_only_marks_timed_words():
    settings=manual('keyword_highlight',.5,1.5)
    settings['effects'][0]['parameters']['quote']='hello world'
    transcript={'segments':[dict(words=[dict(word='Hello,',start=.5,end=1.)]),
        dict(words=[dict(word='world!',start=2,end=2.5)])]}
    result=a.emphasize(transcript,settings)
    assert result['segments'][0]['words'][0]['emphasis']
    assert not result['segments'][1]['words'][0].get('emphasis')
