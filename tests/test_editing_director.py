import copy
import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

import editing_director as d
import reframe_v2 as reframe


@pytest.fixture
def signals(tmp_path,monkeypatch):
    monkeypatch.delenv('CAPTION_PRESET',raising=False)
    monkeypatch.delenv('EDIT_DIRECTOR_STRATEGY',raising=False)
    monkeypatch.setenv('AUTO_HOOK','1')
    fixture=json.loads((Path(__file__).parent/'fixtures/director_signals.json').read_text())
    source=tmp_path/'source.mp4';source.write_bytes(b'source identity only')
    fixture['source_path']=str(source)
    return fixture


def compile(signals,**kw):
    args=dict(media=signals['source_path'],width=320,height=180,fps=10.,out_size=(1080,1920),
        ranges=[(0,10,'TRACK'),(10,20,'GENERAL')],xs=[0]*10+[None]*10,ys=[0]*10+[None]*10,
        crop_size=(100,180),context=signals,subjects={0:[[5,10,30,50]]})
    args.update(kw)
    return d.compile_plan(**args)


def test_edl_is_deterministic_traceable_and_reuses_context(signals):
    plan=compile(signals)
    assert plan==compile(signals)
    assert [s['layout'] for s in plan['shots']]==['TRACK','BLUR']
    assert [s['source_start'] for s in plan['shots']]==[10,40]
    assert [s['keyframes'][0]['time'] for s in plan['shots'] if s['keyframes']]==[0]
    assert plan['captions'][-1]['start']==1.1 and plan['captions'][-1]['source_start']==40.1
    assert plan['hook']['text']=='Can we finish?'
    assert not plan['hook']['enabled']  # Faces/editorial content occupy this opening's top band.
    assert plan['ending']['speech_complete']
    assert plan['audio']['gain_db']==0 and plan['transitions']==[]
    json.dumps(plan,allow_nan=False)


@pytest.mark.parametrize('kind',d.KINDS)
def test_explicit_editing_strategies_and_preserved_natural_timing(signals,monkeypatch,kind):
    monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY',kind)
    plan=compile(signals)
    assert plan['kind']==kind and plan['caption_preset']==d.POLICIES[kind][0]
    assert plan['segments'][1]['source_start']==40
    assert plan['ending']['action']=='preserve'


def test_missing_ai_and_detection_fallback_is_context_preserving(signals):
    signals['analysis']={};signals['transcript']={}
    plan=compile(signals,ranges=[(0,20,'GENERAL')])
    assert plan['kind']=='general'
    assert all(s['layout']=='BLUR' for s in plan['shots'])
    assert plan['captions']==[] and not plan['hook']['enabled']
    assert not plan['ending']['speech_complete']
    assert d.kind_for({'analysis':{'moments':[{'editing_kind':'challenge','start':'bad','end':1}]}})[0]=='general'


def test_disabling_auto_hooks_keeps_caption_decisions(signals,monkeypatch):
    signals['analysis']={}
    on=compile(signals,subjects={})
    assert on['hook']['enabled']
    monkeypatch.setenv('AUTO_HOOK','0')
    off=compile(signals,subjects={})
    assert not off['hook']['enabled']
    assert off['captions']==on['captions'] and off['caption_preset']==on['caption_preset']


def test_explicit_classic_choice_preserves_bold_anton_in_director(signals,monkeypatch):
    monkeypatch.setenv('CAPTION_PRESET','classic')
    assert compile(signals)['caption_preset']=='bold-creator'


def test_ai_context_flags_only_apply_to_overlapping_inspected_shots(signals):
    assert d.context_shots(signals,[(0,10,'TRACK'),(10,20,'TRACK')],10)=={10}
    signals['analysis']['moments'][0]['visual_evidence']=''
    assert d.context_shots(signals,[(0,10,'TRACK'),(10,20,'TRACK')],10)==set()


@pytest.mark.parametrize('change',[
    lambda p:p['shots'][0].update(segment_index=9),
    lambda p:p['shots'][0].update(start=.1),
    lambda p:p['shots'][0].update(layout='SPLIT'),
    lambda p:p['shots'][0]['keyframes'][0].update(x=999),
    lambda p:p['shots'][0]['keyframes'][0].update(time=.1),
    lambda p:p['shots'][0]['keyframes'][0].update(y=float('nan')),
    lambda p:p['segments'][0].update(source_end=100),
    lambda p:p['captions'][0].update(source_start=0),
    lambda p:p['hook'].update(text='Fabricated prize and result'),
    lambda p:p.update(source_ref='../../.env'),
    lambda p:p.update(output_width=1079),
    lambda p:p.update(transitions=[{'filter':'unsafe'}]),
    lambda p:p['audio'].update(gain_db=100),
])
def test_invalid_edl_rejected_before_render(signals,change):
    plan=compile(signals);change(plan)
    with pytest.raises(ValidationError):d.EditPlan.model_validate(plan)


def test_static_center_and_two_independent_split_regions(signals):
    plan=compile(signals,ranges=[(0,10,'TRACK'),(10,20,'SPLIT')],xs=[110]*20,ys=[0]*20,
        splits={10:([45,55],[270,65])})
    assert plan['shots'][0]['layout']=='CENTER'
    left,right=plan['shots'][1]['regions'];assert left['x']!=right['x']
    assert plan['shots'][1]['caption_position']=='middle'


def test_tracking_is_reset_to_new_shot_keyframe(signals):
    plan=compile(signals,ranges=[(0,10,'TRACK'),(10,20,'TRACK')],xs=[0]*10+[220]*10,ys=[0]*20)
    assert [s['keyframes'][0]['x'] for s in plan['shots']]==[0,220]
    assert [s['keyframes'][0]['time'] for s in plan['shots']]==[0,0]


def test_quiet_windows_are_evidence_not_automatic_silence_removal():
    audio=d.audio_decision([0,0,0,0,.8,1],1.2)
    assert audio['quiet_intervals']==[[0,.8]] and audio['gain_db']==0
    assert 'not proof' in d.Audio.model_validate(audio).note


def test_renderer_uses_saved_keyframes_without_ai_or_detectors(tmp_path,monkeypatch,signals):
    import export_quality as q
    from test_export_quality import metadata
    plan=compile(signals)
    info=metadata(audio=True);info['streams'][0].update(width=320,height=180)
    monkeypatch.setattr(q,'probe',lambda *_:info)
    commands=[]
    def fake(command):
        commands.append(command)
        if 'sendcmd' in ' '.join(command):
            graph=command[command.index('-filter_complex')+1]
            assert 'x=0.0' in graph
    assert reframe.render_decisions('prepared.mp4',str(tmp_path/'out.mp4'),plan,runner=fake)
    assert len(commands)==3
    assert d.load(tmp_path/'out.mp4')==plan
    assert any('aac' in cmd for cmd in commands)


def test_real_final_and_preview_replay_identical_decisions(tmp_path,monkeypatch):
    import export_quality as q
    from scenedetect import FrameTimecode as T
    import main
    source=tmp_path/'source.mp4';final=tmp_path/'final.mp4';preview=tmp_path/'preview.mp4'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
        'color=c=green:s=320x180:r=10:d=1.2',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1.2',
        '-vf','drawbox=x=10:y=30:w=50:h=80:color=red:t=fill,drawbox=x=240:y=30:w=50:h=80:color=blue:t=fill',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('EDIT_DIRECTOR','1');monkeypatch.setenv('REFRAME_OUTPUT_SIZE','fullhd')
    monkeypatch.setenv('AUTO_HOOK','1');monkeypatch.setenv('AUTO_CAPTIONS','1')
    monkeypatch.delenv('CAPTION_PRESET',raising=False)
    monkeypatch.setattr(main,'SCENE_CUT_RESET',False)  # director must reset even with legacy setting off
    monkeypatch.setattr(main,'DETECT_STRIDE',1000)
    monkeypatch.setattr(main,'detect_scenes',lambda _:([(T(0,10.),T(6,10.)),(T(6,10.),T(12,10.))],10.))
    monkeypatch.setattr(main,'analyze_scenes_strategy',lambda *_:['TRACK','TRACK'])
    boxes=iter([10,240])
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:[dict(box=[next(boxes),30,50,80],score=4000)])
    monkeypatch.setattr(reframe.split_layout,'ENABLED',False)
    monkeypatch.setattr(reframe.screencast_layout,'ENABLED',False)
    monkeypatch.setattr(reframe.punch_in,'ENABLED',False)
    context=dict(source_path=str(source),source_duration=1.2,transcript={'segments':[dict(start=.1,end=.5,text='A real source sentence.')]})
    assert main.render_clip(str(source),str(final),'auto',director_context=context)
    plan=d.load(final)
    assert [s['keyframes'][0]['time'] for s in plan['shots']]==[0,0]
    assert plan['shots'][0]['keyframes'][0]['x']<plan['shots'][1]['keyframes'][0]['x']
    monkeypatch.setattr(main,'detect_scenes',lambda *_:pytest.fail('preview must not analyze again'))
    assert reframe.render_decisions(str(source),str(preview),plan,size=(108,192))
    assert d.load(preview)==plan
    for clean,size in [(final,(1080,1920)),(preview,(108,192))]:
        output=tmp_path/f'captioned_{size[0]}.mp4'
        assert d.render_layers(str(clean),str(output),plan,size=size)
        assert q.enforce(output,'director',q.expectations(q.probe(source),duration=1.2,size=size))['accepted']
        for at,channel in [('0.05',0),('0.65',2)]:
            raw=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-ss',at,'-i',str(output),
                '-frames:v','1','-filter_threads','1','-vf','scale=2:2','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],capture_output=True,check=True,timeout=10).stdout
            assert raw[channel]>raw[1]


def test_provider_schema_bounds_invalid_editing_kind():
    import story_director
    schema=story_director._schema().model_json_schema()
    assert 'editing_kind' in schema['$defs']['Moment']['properties']
    assert 'preserve_context' in schema['$defs']['Moment']['properties']
    assert 'layout_evidence' in schema['$defs']['Moment']['properties']
    assert 'two_speaker_split' in schema['$defs']['Moment']['properties']['layout_intent']['enum']


@pytest.mark.parametrize('native',['TRACK','GENERAL','SPLIT','EDITORIAL','SCREENCAST','INSET','WIDE'])
def test_all_existing_native_layout_adapters_render(tmp_path,monkeypatch,real_clip,native):
    import export_quality as q
    source=real_clip('layout-'+native)
    monkeypatch.delenv('CAPTION_PRESET',raising=False);monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY','general')
    plan=d.compile_plan(media=str(source),width=64,height=36,fps=24.,out_size=(108,192),
        ranges=[(0,48,native)],xs=[22]*48,ys=[0]*48,crop_size=(20,36),
        splits={0:([10,12],[54,12])},screencasts={0:(30,12)},inset=(40,2,20,12))
    output=tmp_path/f'{native}-rendered.mp4'
    assert reframe.render_decisions(str(source),str(output),plan)
    report=q.enforce(output,native,q.expectations(q.probe(source),duration=2,size=(108,192)))
    assert report['accepted'],report
    assert 'DARK_BORDERS' not in {p['code'] for p in report['problems']}


def test_caption_geometry_maps_faces_and_retains_director_schema(signals):
    plan=compile(signals)
    faces=d.caption_faces(plan)
    assert faces and all(0<=f['x']<1 and 0<=f['y']<1 for f in faces)
    assert d.EditPlan.model_json_schema()['properties']['shots']['type']=='array'


def test_audio_energy_is_reused_for_existing_punch_in():
    import punch_in
    energy=[.1,.2,.9,.1,.1]
    assert punch_in.emphasis_from_envelope(energy)==[.4]


def test_scene_join_splits_missing_shot_boundary(signals):
    plan=compile(signals,ranges=[(0,20,'TRACK')],xs=[0]*10+[220]*10,ys=[0]*20)
    assert len(plan['shots'])==2
    assert plan['shots'][1]['start']==1 and plan['shots'][1]['keyframes'][0]['time']==0


def test_fractional_source_join_does_not_create_a_subframe_shot(signals):
    signals['segments']=[dict(start=10,end=11.05),dict(start=40,end=40.95)]
    plan=compile(signals,ranges=[(0,10,'TRACK'),(10,20,'TRACK')],xs=[0]*10+[220]*10,ys=[0]*20)
    assert len(plan['shots'])==2
    assert plan['shots'][0]['end']==plan['shots'][1]['start']==1.05
    assert plan['shots'][1]['source_start']==40


def test_director_defaults_full_hd_but_preserves_explicit_size_setting(monkeypatch):
    monkeypatch.setenv('EDIT_DIRECTOR','1');monkeypatch.delenv('REFRAME_OUTPUT_SIZE',raising=False)
    assert reframe.delivery_size(3840,2160,9/16)==(1080,1920)
    monkeypatch.setenv('REFRAME_OUTPUT_SIZE','source')
    assert reframe.delivery_size(3840,2160,9/16)==(1216,2160)


@pytest.mark.parametrize('visual_failure',[False,True])
def test_generation_publishes_validated_director_edl_without_competing_layers(tmp_path,monkeypatch,real_clip,visual_failure):
    """Execute the existing CLI body with deterministic selection, real media rendering."""
    import ast
    import builtins
    import sys
    import main
    import export_quality as q
    from scenedetect import FrameTimecode as T
    source=real_clip('generation-source');out=tmp_path/'job';out.mkdir()
    transcript=tmp_path/'speech.json';transcript.write_text(json.dumps({'segments':[dict(start=.1,end=1.8,text='A grounded opening and ending.')] }))
    monkeypatch.setenv('EDIT_DIRECTOR','1');monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY','challenge')
    monkeypatch.setenv('AUTO_HOOK','1');monkeypatch.setenv('AUTO_CAPTIONS','1');monkeypatch.setenv('CLIP_WORKERS','1')
    monkeypatch.setenv('GENERATION_MODE','clips');monkeypatch.setenv('ANALYSIS_MODE','hybrid' if visual_failure else 'transcript')
    if visual_failure:
        monkeypatch.setattr(main.story_director,'analyze_source',lambda *a:(_ for _ in ()).throw(ValueError('schema test failure')))
    monkeypatch.setenv('WATERMARK','0');monkeypatch.delenv('MAX_SOURCE_MINUTES',raising=False)
    monkeypatch.setattr(main.layout_picker,'ENABLED',False)
    monkeypatch.setattr(main,'detect_scenes',lambda _:([(T(0,24.),T(48,24.))],24.))
    monkeypatch.setattr(main,'analyze_scenes_strategy',lambda *_:['GENERAL'])
    monkeypatch.setattr(main,'speech_is_sparse',lambda *_:False)
    monkeypatch.setattr(main,'get_viral_clips',lambda *a,**k:{'shorts':[dict(start=0,end=2,viral_hook_text='Invented model headline') ]})
    monkeypatch.setattr(reframe.split_layout,'ENABLED',False);monkeypatch.setattr(reframe.screencast_layout,'ENABLED',False)
    monkeypatch.setattr(reframe.punch_in,'ENABLED',False)
    monkeypatch.setattr(main,'auto_hook_clip',lambda *a:pytest.fail('directed hook must not run a competing decision path'))
    monkeypatch.setattr(main,'auto_caption_clip',lambda *a,**k:pytest.fail('directed captions must consume the EDL'))
    monkeypatch.setattr(sys,'argv',['main.py','-i',str(source),'-o',str(out),'--transcript',str(transcript)])
    tree=ast.parse(Path(main.__file__).read_text(encoding='utf-8'))
    guard=next(n for n in tree.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and ast.unparse(n.test)=="__name__ == '__main__'")
    command=builtins.compile(ast.Module(body=guard.body,type_ignores=[]),main.__file__,'exec')
    if visual_failure:
        with pytest.raises(RuntimeError,match='No transcript-only clips were generated'):
            exec(command,dict(main.__dict__))
        assert not list(out.glob('*_metadata.json'))
        assert not list(out.glob('*clip*.mp4'))
        assert json.loads((out/'analysis_failure.json').read_text())['error_type']=='ValueError'
        return
    exec(command,dict(main.__dict__))
    metadata=json.loads(next(out.glob('*_metadata.json')).read_text())
    clip=metadata['shorts'][0]
    assert clip['render_status']=='completed' and metadata['pipeline_state']=='completed'
    assert metadata['analysis_status']['status']=='not_requested'
    assert clip['quality_report']['accepted']
    # General footage no longer duplicates the source in an editorial panel.
    # The independent opening hook can use the unobstructed top safe area.
    assert clip['auto_hook']['text']=='A grounded opening and ending.'
    assert d.load(out/'generation-source_clip_1.mp4')['shots'][0]['layout']=='BLUR'
    assert d.load(out/'generation-source_clip_1.mp4')['hook']['text']=='A grounded opening and ending.'
    assert (out/clip['edit_decision_file']).is_file()
    assert d.load(out/'generation-source_clip_1.mp4')['kind']=='challenge'
    assert q.streams(q.probe(out/clip['delivered_file']))[0]['width']==1080


from test_export_quality import real_clip  # noqa: F401


@pytest.mark.parametrize('kind',['challenge','educational','comedy','emotional','podcast'])
def test_story_category_does_not_force_duplicate_editorial_panel(signals,monkeypatch,kind):
    monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY',kind)
    automatic=compile(signals)
    assert automatic['shots'][1]['renderer']=='GENERAL'
    assert automatic['shots'][1]['layout']=='BLUR'
    assert automatic['shots'][1]['focus_x'] is None
    assert automatic['shots'][1]['caption_position']=='bottom'
    explicit=compile(signals,editorial=True)
    assert explicit['shots'][1]['renderer']=='EDITORIAL'
    assert explicit['shots'][1]['layout']=='EDITORIAL'

