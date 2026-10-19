"""TASK-001: geometry, actual FFmpeg rasters, and deterministic detector tracks."""
import json
import shutil
import subprocess

import numpy as np
import pytest

import clean_captions
import reframe_v2 as reframe
import split_layout
import panel_layout
from framing_geometry import crop_size, crop_position, subject_position, needs_context


@pytest.fixture(autouse=True)
def smart_defaults(monkeypatch):
    monkeypatch.delenv('SMART_REFRAME', raising=False)
    monkeypatch.delenv('CAPTION_SAFE_BOTTOM_RATIO', raising=False)
    monkeypatch.delenv('REFRAME_OUTPUT_SIZE', raising=False)


SOURCES = [(1920, 1080), (640, 480), (720, 720), (720, 1280),
           (720, 1600), (16, 10), (3, 3), (2, 2)]


@pytest.mark.parametrize('width,height', SOURCES)
def test_bounded_even_crop_and_fullhd_delivery(width, height, monkeypatch):
    monkeypatch.setenv('REFRAME_OUTPUT_SIZE', 'fullhd')
    assert reframe.delivery_size(width, height, 9/16) == (1080, 1920)
    w, h = crop_size(width, height, 9/16)
    for cx, cy in [(-100, -500), (1e8, 1e8), (float('nan'), float('inf'))]:
        x, y = crop_position(width, height, w, h, cx, cy)
        assert 2 <= w <= width and 2 <= h <= height
        assert 0 <= x <= width - w and 0 <= y <= height - h
        assert all(v % 2 == 0 for v in (w, h, x, y))


@pytest.mark.parametrize('width,height,aspect', [(0, 10, .5), (10, 0, .5),
    (10, 10, 0), (10, 10, float('nan')), (float('inf'), 10, .5)])
def test_invalid_source_geometry_is_rejected(width, height, aspect):
    with pytest.raises(ValueError):
        crop_size(width, height, aspect)


def test_invalid_manual_centres_are_ignored_and_extremes_are_clamped():
    xs, strategies = reframe.apply_crop_overrides(
        [10]*8, ['TRACK']*4, [(0,2),(2,4),(4,6),(6,8)],
        {0: float('nan'), 1: float('inf'), 2: -20, 3: 20}, 600, 1920)
    assert xs == [10,10,10,10,0,0,1320,1320]
    splits = {}
    reframe.apply_crop_overrides([0]*4, ['TRACK'], [(0,4)],
        {0: {'top': float('inf'), 'bottom': .5}}, 600, 1920, 1080, splits)
    assert splits == {}


def test_two_subjects_have_headroom_and_stay_in_their_panels():
    centres = [(350, 240, 150, 170), (1600, 800, 160, 180)]
    for cx, cy, fw, fh in centres:
        w, h, x, y, half = split_layout.split_geometry(1920,1080,1080,1920,
                                                      (cx,cy,fw,fh))
        assert x <= cx-fw/2 < cx+fw/2 <= x+w
        assert y <= cy-fh/2 < cy+fh/2 <= y+h
        assert half == 960
    assert split_layout.analyze_scene([
        [dict(box=[cx-fw/2,cy-fh/2,fw,fh],score=fw*fh)
         for cx,cy,fw,fh in centres]]*10,1920) is not None


def test_subject_anchor_reduces_ceiling_without_cutting_head():
    x, y = subject_position(1920,1080,972,864,(1000,480,180,200))
    assert 0 <= x <= 948 and 0 <= y <= 216
    assert y <= 380 and y+864 >= 580
    assert 480-y < .4*864


def test_primary_subjects_outside_one_crop_require_context():
    face=lambda x,w:dict(box=[x,200,w,w],score=w*w)
    assert needs_context([face(100,220),face(1500,160)],1920,1080)
    assert needs_context([face(500,800)],1920,1080)  # close-up wider than crop
    assert not needs_context([face(800,200),face(100,30)],1920,1080)
    assert not needs_context([],1920,1080)


def test_camera_motion_dropout_and_empty_scene_cut():
    main = pytest.importorskip('main')
    cam = main.SmoothedCameraman(1080,1920,1920,1080)
    cam.begin_scene()
    cam.update_target([300,200,100,140])
    first = cam.get_crop_box()[0]
    cam.update_target([1600,200,100,140])  # isolated detector outlier
    assert cam.get_crop_box()[0] == first
    for _ in range(3):
        cam.update_target([1000,200,100,140])
    trajectory = [cam.get_crop_box()[0] for _ in range(90)]
    assert all(0 <= b-a <= 18 for a,b in zip(trajectory,trajectory[1:]))
    assert trajectory[-1] <= 1050 <= trajectory[-1]+cam.crop_width
    for _ in range(10):
        cam.update_target(None)
    assert cam.get_crop_box()[0] == trajectory[-1]
    cam.begin_scene()
    x,y,x2,y2 = cam.get_crop_box(force_snap=True)
    assert abs((x+x2)/2-960) <= 2
    assert y == 0 and y2 == 1080
    cam.update_target([1450,200,100,140])
    x,_,x2,_ = cam.get_crop_box()
    assert abs((x+x2)/2-1500) <= 2


def test_tall_portrait_vertical_crop_is_bounded_and_smoothed():
    main = pytest.importorskip('main')
    cam = main.SmoothedCameraman(1080,1920,720,1800)
    cam.begin_scene()
    cam.update_target([300,200,120,180])
    _,y,_,y2 = cam.get_crop_box()
    assert y2-y == cam.crop_height < 1800
    cam.update_target([300,1400,120,180])
    ys = [cam.get_crop_box()[1] for _ in range(60)]
    assert all(0 <= b-a <= 22 for a,b in zip(ys,ys[1:]))
    assert all(0 <= v <= 1800-cam.crop_height for v in ys)


def test_tall_source_is_not_assumed_to_fit_and_fallback_keeps_top_bottom():
    main=pytest.importorskip('main')
    assert not reframe.source_already_fits(90,200,9/16)
    frame=np.full((200,90,3),100,np.uint8)
    frame[:20]=(0,0,255)
    frame[-20:]=(255,0,0)
    image=main.create_general_frame(frame,1080,1920)
    assert tuple(image[10,540]) == (0,0,255)
    assert tuple(image[-10,540]) == (255,0,0)


@pytest.mark.parametrize('reserve,expected', [('0.12',230), ('bad',384),
                                                           ('nan',384), ('1',672)])
def test_caption_reserve_changes_text_only(tmp_path, monkeypatch, reserve, expected):
    monkeypatch.setenv('CAPTION_SAFE_BOTTOM_RATIO', reserve)
    transcript={'segments':[{'words':[{'word':'hello','start':0,'end':1}]}]}
    path=tmp_path/'caption.ass'
    assert clean_captions.generate(transcript,0,2,path)
    style = next(line for line in path.read_text(encoding='utf-8-sig').splitlines()
                 if line.startswith('Style:'))
    assert int(style.split(',')[-2]) == expected
    assert crop_size(1920,1080,9/16) == (606,1080)


def test_classic_caption_reserve_and_explicit_margin(tmp_path, monkeypatch):
    import subtitles
    monkeypatch.setenv('CAPTION_SAFE_BOTTOM_RATIO','.25')
    transcript={'segments':[{'words':[{'word':'hello','start':0,'end':1}]}]}
    path=tmp_path/'classic.ass'
    assert subtitles.generate_ass(transcript,0,2,path)
    style=next(s for s in path.read_text(encoding='utf-8').splitlines() if s.startswith('Style:'))
    assert int(style.split(',')[-2]) == 72
    assert subtitles.generate_ass(transcript,0,2,path,margin_v=20)
    style=next(s for s in path.read_text(encoding='utf-8').splitlines() if s.startswith('Style:'))
    assert int(style.split(',')[-2]) == 20


def test_fast_untrackable_motion_preserves_entire_scene(monkeypatch):
    """Reuse the detectors once; never pan away from an untrackable subject."""
    import io
    main=pytest.importorskip('main')
    frame=np.full((180,320,3),100,np.uint8)
    class Decoder:
        stdout=io.BytesIO(frame.tobytes()*12)
        returncode=0
        def wait(self,timeout=None): return 0
    monkeypatch.setattr(reframe.subprocess,'Popen',lambda *a,**k:Decoder())
    positions=iter([10,240,240])
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:
        [dict(box=[next(positions),30,50,60],score=3000)])
    monkeypatch.setattr(main,'DETECT_STRIDE',4)
    monkeypatch.setattr(main,'SCENE_CUT_RESET',True)
    strategies=['TRACK']
    cam=main.SmoothedCameraman(1080,1920,320,180)
    xs=reframe._analyze_trajectory('unused',[(0,12)],strategies,30.,320,180,
                                  cam,main.SpeakerTracker())
    assert len(xs) == 12
    assert strategies == ['GENERAL']


@pytest.fixture
def ffmpeg():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/ffprobe are not installed')


def render_raster(tmp_path, graph, size, name='out'):
    out=tmp_path/f'{name}.mp4'
    cmd=['ffmpeg','-v','error','-nostdin','-y','-filter_complex_threads','1',
         '-f','lavfi','-i',f'color=c=0x40c080:s={size[0]}x{size[1]}:r=10:d=0.2',
         '-filter_complex',graph,'-map','[v]','-frames:v','2',
         '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(out)]
    subprocess.run(cmd,check=True,capture_output=True,timeout=60)
    info=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams',
        '-of','json',str(out)],check=True,capture_output=True,timeout=20).stdout)
    stream=info['streams'][0]
    raw=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(out),
        '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],
        check=True,capture_output=True,timeout=30).stdout
    return np.frombuffer(raw,np.uint8).reshape(stream['height'],stream['width'],3)


@pytest.mark.parametrize('size', [(320,180),(320,240),(240,240),(180,320),(90,200),(16,10)])
def test_preserved_image_has_fullhd_raster_and_no_generated_borders(ffmpeg,tmp_path,size):
    image=render_raster(tmp_path,reframe.general_filtergraph(1080,1920),size)
    assert image.shape == (1920,1080,3)
    assert image.min() > 30  # uniform coloured source: any black padding is a bug


@pytest.mark.parametrize('layout', ['split','panel3','panel4','editorial','square_editorial'])
def test_multiview_raster_has_no_black_filler(ffmpeg,tmp_path,layout):
    w,h=320,180
    if layout == 'split':
        # Height not divisible by four used to introduce a 2px black strip.
        graph=split_layout.split_filtergraph(w,h,1080,1922,(70,60),(250,60))
    elif layout.startswith('panel'):
        centres=[(45,60,24,30),(135,60,24,30),(225,60,24,30),(290,60,24,30)]
        graph=panel_layout.panel_filtergraph(w,h,1080,1920,centres[:int(layout[-1])])
    else:
        if layout == 'square_editorial': w,h=240,240
        graph=reframe.editorial_filtergraph(w,h,1080,1920)
    image=render_raster(tmp_path,graph,(w,h))
    assert image.shape[1:] == (1080,3)
    assert image.min() > 30


def test_intentional_dark_source_is_preserved(ffmpeg,tmp_path):
    # Dark source content must survive, not be detected as unwanted padding.
    graph='[0:v]drawbox=x=0:y=0:w=iw/3:h=ih:color=black:t=fill[src];'
    from framing_geometry import contain_background
    graph+=contain_background(1080,1920,'src')
    image=render_raster(tmp_path,graph,(320,180))
    assert image[960,80].max() < 10
    assert image[960,900].min() > 30


def test_no_face_scene_between_speakers_keeps_context(monkeypatch):
    main=pytest.importorskip('main')
    class Capture:
        index=0
        def isOpened(self): return True
        def get(self, _): return 30
        def set(self, _, index): self.index=index
        def read(self): return True,np.full((180,320,3),100,np.uint8)
        def release(self): pass
    cap=Capture()
    monkeypatch.setattr(main.cv2,'VideoCapture',lambda _:cap)
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:
        [] if 90 <= cap.index < 120 else [dict(box=[100,40,50,60],score=3000)])
    from scenedetect import FrameTimecode as T
    scenes=[(T(0,30.),T(90,30.)),(T(90,30.),T(120,30.)),(T(120,30.),T(210,30.))]
    assert main.analyze_scenes_strategy('unused.mp4',scenes) == ['TRACK','GENERAL','TRACK']


def test_real_reframe_cuts_directly_to_new_subject(ffmpeg,tmp_path,monkeypatch):
    """Run decoder, camera, sendcmd, scene encodes, concat and layout sidecar.

    Only scene/face detection is deterministic; the actual media path is used.
    Red and blue rectangles represent the two subjects across a camera cut.
    """
    main=pytest.importorskip('main')
    from scenedetect import FrameTimecode as T
    src=tmp_path/'source.mp4'; out=tmp_path/'reframed.mp4'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
        'color=c=green:s=320x180:r=10:d=0.8', '-vf',
        'drawbox=x=10:y=30:w=50:h=80:color=red:t=fill,'
        'drawbox=x=240:y=30:w=50:h=80:color=blue:t=fill',
        '-c:v','libx264','-pix_fmt','yuv420p',str(src)],
        check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('FFMPEG_ENCODER','x264')
    monkeypatch.setenv('REFRAME_OUTPUT_SIZE','fullhd')
    monkeypatch.setattr(main,'SCENE_CUT_RESET',True)
    monkeypatch.setattr(main,'detect_scenes',lambda _:
        ([(T(0,10.),T(4,10.)),(T(4,10.),T(8,10.))],10.))
    monkeypatch.setattr(main,'analyze_scenes_strategy',lambda *_:['TRACK','TRACK'])
    calls=iter([10,240])
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:
        [dict(box=[next(calls),30,50,80],score=4000)])
    monkeypatch.setattr(split_layout,'ENABLED',False)
    monkeypatch.setattr(reframe.screencast_layout,'ENABLED',False)
    monkeypatch.setattr(reframe.punch_in,'ENABLED',False)
    assert reframe.render(str(src),str(out),9/16)
    for offset,channel in [('0',0),('0.4',2)]:
        raw=subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',offset,
            '-i',str(out),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],
            check=True,capture_output=True,timeout=30).stdout
        image=np.frombuffer(raw,np.uint8).reshape(1920,1080,3)
        assert image[800,540,channel] > 200
        assert image[800,540,1] < 30
    assert json.loads((tmp_path/'reframed.mp4.layout.json').read_text())['ranges'] == [
        dict(start=0.0,end=0.4,layout='track'),dict(start=0.4,end=0.8,layout='track')]


def test_legacy_fallback_adapts_to_resolution_and_aspect_changes(tmp_path,monkeypatch):
    import io
    from types import SimpleNamespace
    main=pytest.importorskip('main')
    from scenedetect import FrameTimecode as T
    frames=iter([np.full((180,320,3),100,np.uint8),
                 np.full((90,160,3),110,np.uint8),
                 np.full((200,90,3),120,np.uint8)])
    class Reader:
        def isOpened(self): return True
        def read(self):
            frame=next(frames,None)
            return frame is not None,frame
        def get(self,_): return 3
        def release(self): pass
    written=[]
    class Sink:
        def write(self,data): written.append(data)
        def close(self): pass
    encoder=SimpleNamespace(stdin=Sink(),stderr=io.BytesIO(),returncode=0,wait=lambda:0)
    monkeypatch.setenv('REFRAME_ENGINE','v1')
    monkeypatch.setenv('REFRAME_OUTPUT_SIZE','fullhd')
    monkeypatch.setenv('FFMPEG_ENCODER','x264')
    monkeypatch.setattr(main.cv2,'VideoCapture',lambda _:Reader())
    monkeypatch.setattr(main,'get_video_resolution',lambda _:(320,180))
    monkeypatch.setattr(main,'detect_scenes',lambda _: ([(T(0,30.),T(3,30.))],30.))
    monkeypatch.setattr(main,'analyze_scenes_strategy',lambda *_:['TRACK'])
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:[])
    monkeypatch.setattr(main,'detect_person_yolo',lambda _:None)
    monkeypatch.setattr(main.subprocess,'Popen',lambda *a,**k:encoder)
    monkeypatch.setattr(main.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    assert main.process_video_to_vertical('unused.mp4',str(tmp_path/'out.mp4'))
    assert len(written) == 3
    for data,expected in zip(written,(100,110,120)):
        image=np.frombuffer(data,np.uint8).reshape(1920,1080,3)
        assert np.all(image==expected)


def test_decoder_detects_resolution_change_before_fixed_crop(ffmpeg,tmp_path):
    main=pytest.importorskip('main')
    parts=[]
    for i,(w,h) in enumerate([(320,180),(160,90)]):
        path=tmp_path/f'part{i}.ts'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
            f'color=c=green:s={w}x{h}:r=25:d=0.2','-c:v','mpeg2video',
            '-f','mpegts',str(path)],check=True,capture_output=True,timeout=30)
        parts.append(path.read_bytes())
    source=tmp_path/'changing.ts'
    source.write_bytes(b''.join(parts))
    cam=main.SmoothedCameraman(1080,1920,320,180)
    with pytest.raises(RuntimeError,match='source resolution changed'):
        reframe._analyze_trajectory(str(source),[(0,50)],['GENERAL'],25.,320,180,
                                    cam,main.SpeakerTracker())
