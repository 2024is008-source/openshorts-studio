"""TASK-003: measured paths and synthetic detector scenarios, not actor recognition."""
import io
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

import framing_geometry as g
import reframe_v2 as r
import editing_director as director
import split_layout

FIXTURE=json.loads((Path(__file__).parent/'fixtures/framing_scenes.json').read_text())


@pytest.mark.parametrize('fps',[10.,24.,30.,60.])
def test_timestamped_paths_compress_with_bounded_error_and_preserve_stops(fps):
    n=round(4*fps)
    boxes=[(100,180,int(min(120,max(0,(i/fps-1)*80)))//2*2,0) for i in range(n)]
    keys=g.compact_keyframes(boxes,fps)
    restored=g.sample_keyframes(keys,fps,n/fps,320,180)
    assert len(keys)<len(boxes)/2 and keys[0]['time']==0
    assert max(abs(a-b) for first,second in zip(boxes,restored) for a,b in zip(first,second))<=4
    assert len(restored)==n and all(box[2]==0 for box in restored[:round(fps)])
    assert len(g.compact_keyframes([(100,180,110,0)]*n,fps))==1


def test_interpolation_is_in_seconds_and_old_hold_paths_remain_readable():
    keys=[dict(time=0.,x=0.,y=0.,width=100.,height=180.),dict(time=1.,x=200.,y=0.,width=100.,height=180.)]
    for fps in (10,30,60):
        path=g.sample_keyframes(keys,fps,1.5,320,180)
        assert path[round(.5*fps)][2]==100
        held=g.sample_keyframes(keys,fps,1.5,320,180,'hold')
        assert held[round(.5*fps)][2]==0 and held[round(1.2*fps)][2]==200


def test_malformed_paths_and_low_resolution_geometry():
    with pytest.raises(ValueError):g.compact_keyframes([],0)
    with pytest.raises(ValueError):g.sample_keyframes([],30,1,320,180)
    keys=[dict(time=0.,x=1000.,y=-500.,width=3.,height=3.)]
    assert g.sample_keyframes(keys,12,1,3,3)==[(2,2,0,0)]*12
    evidence=[]
    g.retain_regions(evidence,[[i,0,10,10] for i in range(100)])
    assert len(evidence)==32 and evidence[-1][0]+evidence[-1][2]==109


def face(cx,cy=60,size=40):return dict(box=[cx-size/2,cy-size/2,size,size],score=size*size)


def test_two_faces_near_same_x_never_share_one_identity():
    import main
    t=main.SpeakerTracker()
    t.get_target([face(140,45),face(145,125)],0,320)
    assert len({k['id'] for k in t.known_faces})==2
    first={k['cy']:k['id'] for k in t.known_faces}
    t.get_target([face(145,125),face(140,45)],4,320)
    assert {k['cy']:k['id'] for k in t.known_faces}==first


def test_motion_prediction_keeps_crossing_subjects_distinct_and_forgets_old_tracks():
    current=[];next_id=0;identities=[]
    for frame,(a,b) in enumerate([(80,240),(110,210),(140,180),(170,150),(200,120)]):
        matched,current,next_id=g.associate_faces([face(a),face(b)],current,frame,320,next_id)
        identities.append(tuple(c['id'] for c in matched))
    assert all(ids==identities[0] for ids in identities)
    assert g.associate_faces([],current,100,320,next_id)[1]==[]


def test_temporary_occlusion_does_not_steal_subject_identity():
    import main
    tracker=main.SpeakerTracker(cooldown_frames=30)
    tracker.get_target([face(80),face(240)],0,320);pid=tracker.active_speaker_id
    assert tracker.get_target([face(240)],4,320) is None
    assert tracker.get_target([face(82),face(240)],8,320)[0]<100
    assert tracker.active_speaker_id==pid
    tracker.reset();assert tracker.get_target([face(240)],9,320)[0]>200


def test_camera_pan_speed_is_time_based_and_headroom_is_bounded():
    import main
    positions=[]
    for fps in (15,30,60):
        cam=main.SmoothedCameraman(1080,1920,1920,1080,fps=fps)
        cam.begin_scene();cam.update_target([200,100,100,160]);cam.get_crop_box()
        for _ in range(3):cam.update_target([1000,100,100,160])
        for _ in range(fps):cam.get_crop_box()
        positions.append(cam.current_center_x)
    assert max(positions)-min(positions)<20
    cam=main.SmoothedCameraman(1080,1920,720,1800)
    cam.begin_scene();cam.update_target([200,600,200,300])
    x,y,x2,y2=cam.get_crop_box()
    assert x<=200<400<=x2 and y<=600<900<=y2
    assert .15<(750-y)/(y2-y)<.5


def test_groups_and_sustained_two_person_movement_do_not_become_static_splits():
    group=[[face(40),face(160),face(280)]]*10
    assert split_layout.analyze_scene(group,320) is None
    moving=[[face(40+i*10),face(200+i*10)] for i in range(10)]
    assert split_layout.analyze_scene(moving,320) is None
    assert split_layout.analyze_scene([[face(60),face(260)]]*10,320)


def test_unclear_speaker_activity_cannot_remove_a_useful_region():
    import active_speaker as s
    assert not s.reliable([None]*10) and not s.reliable([0,1,None,None,None])
    assert s.reliable([0,0,0,0,None]) and s.reliable([0,1,0,1])


def trajectory(monkeypatch, detections, *, bodies=(),fps=12.,count=36,scenes=None):
    import main
    frame=np.full((180,320,3),100,np.uint8)
    class Decode:
        stdout=io.BytesIO(frame.tobytes()*count)
        returncode=0
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(r.subprocess,'Popen',lambda *a,**k:Decode())
    monkeypatch.setattr(main,'DETECT_STRIDE',3)
    monkeypatch.setattr(main,'detect_person_yolo',lambda _:None)
    calls=iter(detections)
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:next(calls))
    monkeypatch.setattr(main,'detect_framing_regions',lambda _:list(bodies))
    strategies=['TRACK']*len(scenes or [(0,count)])
    protected={};ys=[]
    xs=r._analyze_trajectory('unused',scenes or [(0,count)],strategies,fps,320,180,
        main.SmoothedCameraman(1080,1920,320,180,fps=fps),main.SpeakerTracker(fps=fps),ys,
        context_evidence=protected)
    return xs,ys,strategies,protected


def test_body_and_selected_object_context_override_an_unsafe_crop(monkeypatch):
    monkeypatch.setenv('FRAMING_PRESET','balanced')
    rows=[[face(160)]]*12
    for region in [dict(label='person',box=[60,10,200,165]),dict(label='bicycle',box=[10,90,290,80])]:
        xs,ys,strategies,protected=trajectory(monkeypatch,rows,bodies=[region])
        assert strategies==['GENERAL'] and protected[0]
    monkeypatch.setenv('REFRAME_SUBJECT_CONTEXT','0')
    assert trajectory(monkeypatch,rows,bodies=[region])[2]==['TRACK']


def test_fast_movement_long_dropout_and_camera_cuts(monkeypatch):
    assert trajectory(monkeypatch,[[face(40)]]+[[face(280)]]*11)[2]==['GENERAL']
    assert trajectory(monkeypatch,[[face(60)]]+[[]]*11)[2]==['GENERAL']
    assert trajectory(monkeypatch,[[face(60)]]*4+[[]]+[[face(60)]]*7)[2]==['TRACK']
    monkeypatch.setenv('SCENE_CUT_RESET','0')
    import main
    monkeypatch.setattr(main,'SCENE_CUT_RESET',False)
    xs,_,_,_=trajectory(monkeypatch,[[face(60)]]*4+[[face(260)]]*8,scenes=[(0,12),(12,36)])
    assert xs[0]<20 and xs[12]>180  # SMART_REFRAME resets even with the legacy flag off.


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_synthetic_scenes_render_fullhd_with_context_and_no_padding(tmp_path,monkeypatch,case):
    import main
    import active_speaker
    import export_quality as q
    from scenedetect import FrameTimecode as T
    source=tmp_path/'scene.mp4';output=tmp_path/'output.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=0x60B080:s=320x180:r=12:d=3',
        '-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('EDIT_DIRECTOR','1');monkeypatch.setenv('REFRAME_OUTPUT_SIZE','fullhd')
    monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY','general');monkeypatch.setenv('AUTO_CAPTIONS','0');monkeypatch.setenv('AUTO_HOOK','0')
    monkeypatch.setenv('FFMPEG_ENCODER','x264')
    monkeypatch.setenv('FRAMING_PRESET','auto')
    monkeypatch.setattr(main,'detect_scenes',lambda _:([(T(0,12.),T(36,12.))],12.))
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:[dict(box=list(box),score=box[2]*box[3]) for box in case['faces']])
    monkeypatch.setattr(main,'detect_portrait_candidates',lambda _:[dict(box=list(box),score=box[2]*box[3]) for box in case['faces']])
    monkeypatch.setattr(main,'detect_person_yolo',lambda _:None)
    monkeypatch.setattr(main,'detect_framing_regions',lambda _:[dict(label='person',box=case['body'])] if 'body' in case else [])
    monkeypatch.setattr(split_layout,'ENABLED',True);monkeypatch.setattr(active_speaker,'ENABLED',False)
    monkeypatch.setattr(r.screencast_layout,'ENABLED',False);monkeypatch.setattr(r.punch_in,'ENABLED',False)
    context={}
    if case['name'] in ('two_speakers','treadmill_action'):
        context={'analysis':{'moments':[dict(start=0,end=3,
            layout_intent='two_speaker_split' if case['name']=='two_speakers' else 'demonstration',
            layout_evidence='Independent stationary speakers.' if case['name']=='two_speakers' else 'The full exercise movement and equipment are visible.')]}}
    assert r.render(str(source),str(output),9/16,director_context=context)
    plan=director.load(output)
    assert plan['shots'][0]['layout']==case['layout']
    if case['name']=='two_speakers':
        assert 'overlap' in plan['shots'][0]['reason']  # Low-resolution panel crops repeat subjects.
    if case['name']=='two_speakers_uninspected':
        assert 'scene evidence' in plan['shots'][0]['reason']
    video,_=q.streams(q.probe(output));assert (video['width'],video['height'])==(1080,1920)
    raw=subprocess.check_output(['ffmpeg','-v','error','-ss','1','-i',str(output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],timeout=30)
    image=np.frombuffer(raw,np.uint8).reshape(1920,1080,3)
    assert image.min()>35
    if case['layout']=='CENTER':assert plan['shots'][0]['interpolation']=='linear'


def test_low_resolution_does_not_add_optional_zoom_or_tighten_split(monkeypatch):
    import punch_in
    assert punch_in.crop_boxes([0],[5],100,180,320,180)==[(100,180,0,0)]
    assert punch_in.crop_boxes([0],[5],600,1080,1920,1080)[0][0]>=520
    monkeypatch.setattr(split_layout,'SPLIT_TIGHTNESS',.3)
    assert split_layout.split_geometry(320,180,1080,1920,(160,60))[1]==180


def test_real_scene_detection_and_missing_neural_detector_fallback(tmp_path,monkeypatch):
    import scene_detection as s
    source=tmp_path/'cut.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=30:d=1',
        '-f','lavfi','-i','color=c=blue:s=160x90:r=30:d=1','-filter_complex',
        '[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264',str(source)],check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('SCENE_ENGINE','transnetv2')
    def missing(_):raise ImportError('No model installed')
    monkeypatch.setattr(s,'_detect_transnetv2',missing)
    scenes,fps=s.detect_scenes(str(source))
    assert len(scenes)==2 and abs(scenes[1][0].get_seconds()-1)<1/fps


def test_saved_sparse_motion_is_replayed_for_preview_and_fullhd(tmp_path,monkeypatch):
    import export_quality as q
    fps=12;frames=[];xs=[]
    for i in range(36):
        cx=60+round(i/35*200)
        frame=np.full((180,320,3),(45,150,75),np.uint8)
        frame[25:130,cx-20:cx+20]=(220,25,25)
        frames.append(frame.tobytes());xs.append(max(0,min(220,cx-50))//2*2)
    source=tmp_path/'moving.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','320x180','-r',str(fps),'-i','-',
        '-c:v','libx264','-pix_fmt','yuv420p',str(source)],input=b''.join(frames),check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('REFRAME_KEYFRAMES','1');monkeypatch.setenv('AUTO_HOOK','0')
    monkeypatch.setenv('EDIT_DIRECTOR_STRATEGY','general');monkeypatch.setenv('FFMPEG_ENCODER','x264')
    plan=director.compile_plan(media=str(source),width=320,height=180,fps=12.,out_size=(1080,1920),
        ranges=[(0,36,'TRACK')],xs=xs,ys=[0]*36,crop_size=(100,180))
    assert plan['shots'][0]['interpolation']=='linear' and len(plan['shots'][0]['keyframes'])<18
    before=json.dumps(plan,sort_keys=True)
    for size in [(360,640),(1080,1920)]:
        output=tmp_path/f'moving-{size[0]}.mp4'
        assert r.render_decisions(str(source),str(output),plan,size=size)
        assert json.dumps(director.load(output),sort_keys=True)==before
        for time in (0.,1.,2.5):
            raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-i',str(output),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],timeout=30)
            image=np.frombuffer(raw,np.uint8).reshape(size[1],size[0],3)
            pixel=image[size[1]//3,size[0]//2]
            assert pixel[0]>180 and pixel[1]<70
            assert np.max(image,axis=2).min()>30  # Colored source, no introduced black canvas.
        assert q.streams(q.probe(output))[0]['width']==size[0]


def test_optional_context_detector_failure_and_manual_crop_are_safe(monkeypatch):
    import main
    # The optional detector is best effort; failure must not lose a crop/clip.
    frame=np.full((180,320,3),100,np.uint8)
    class Decode:
        def __init__(self):self.stdout=io.BytesIO(frame.tobytes()*12)
        returncode=0
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(r.subprocess,'Popen',lambda *a,**k:Decode())
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:[face(160)])
    calls=[]
    def fail(_):calls.append(1);raise RuntimeError('Unavailable local detector')
    monkeypatch.setattr(main,'detect_framing_regions',fail)
    for manual in (False,True):
        strategies=['TRACK']
        xs=r._analyze_trajectory('unused',[(0,12)],strategies,12.,320,180,
            main.SmoothedCameraman(1080,1920,320,180),main.SpeakerTracker(),allow_context=not manual)
        assert len(xs)==12 and strategies==['TRACK']
    assert len(calls)==1  # Disabled after failure; manual overrides do not call it.
