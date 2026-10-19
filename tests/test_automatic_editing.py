"""Automatic composition must use evidence, not headcount or body overflow alone."""
import io
import numpy as np
import pytest
from scenedetect import FrameTimecode as T

import main
import reframe_v2
from generation_options import normalize_options


def test_automatic_profile_enables_existing_coordinated_features():
    result=normalize_options(framing='auto')
    assert all(result[k]=='1' for k in ['EDIT_DIRECTOR','SMART_REFRAME','REFRAME_KEYFRAMES','SPLIT_LAYOUT','AUTO_LAYOUT'])
    assert normalize_options(framing='balanced')['FRAMING_PRESET']=='balanced'
    assert 'EDIT_DIRECTOR' not in normalize_options(framing='balanced')


@pytest.mark.parametrize('boxes,expected',[
    ([[110,40,20,24],[145,40,20,24]],'TRACK'),
    ([[10,40,30,30],[260,40,30,30]],'GENERAL'),
    ([], 'GENERAL'),
])
def test_automatic_scene_uses_portrait_fit_and_preserves_wide_context(monkeypatch,boxes,expected):
    monkeypatch.setenv('FRAMING_PRESET','auto');monkeypatch.setenv('VIDEO_TEMPLATE','none')
    class Capture:
        def isOpened(self):return True
        def get(self,_):return 30
        def set(self,*args):pass
        def read(self):return True,np.full((180,320,3),100,np.uint8)
        def release(self):pass
    monkeypatch.setattr(main.cv2,'VideoCapture',lambda _:Capture())
    monkeypatch.setattr(main,'detect_portrait_candidates',lambda _:[dict(box=b,score=b[2]*b[3]) for b in boxes])
    assert main.analyze_scenes_strategy('fixture',[(T(0,30.),T(30,30.))])==[expected]


@pytest.mark.parametrize('object_present,expected',[(False,'TRACK'),(True,'GENERAL')])
def test_body_overflow_does_not_force_blur_but_important_object_still_does(monkeypatch,object_present,expected):
    monkeypatch.setenv('FRAMING_PRESET','auto');monkeypatch.setenv('VIDEO_TEMPLATE','none')
    monkeypatch.setenv('SMART_REFRAME','1');monkeypatch.setenv('REFRAME_SUBJECT_CONTEXT','1')
    monkeypatch.setattr(main,'DETECT_STRIDE',4)
    image=np.full((180,320,3),100,np.uint8)
    class Decoder:
        stdout=io.BytesIO(image.tobytes()*60)
        returncode=0
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(reframe_v2.subprocess,'Popen',lambda *a,**k:Decoder())
    monkeypatch.setattr(main,'detect_portrait_candidates',lambda _:[dict(box=[140,40,25,30],score=750)])
    regions=[dict(label='person',box=[110,20,100,160])]
    if object_present:regions.append(dict(label='sports ball',box=[5,80,30,30]))
    monkeypatch.setattr(main,'detect_framing_regions',lambda _:regions)
    cam=main.SmoothedCameraman(1080,1920,320,180)
    strategies=['TRACK']
    xs=reframe_v2._analyze_trajectory('fixture',[(0,60)],strategies,30,320,180,cam,main.SpeakerTracker())
    assert len(xs)==60 and strategies==[expected]


def test_hidden_faces_use_measured_person_anchors_without_claiming_face_detection(monkeypatch):
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:[])
    monkeypatch.setattr(main,'detect_framing_regions',lambda _:[dict(label='person',box=[100,20,80,140]),dict(label='person',box=[5,5,8,10])])
    anchors=main.detect_portrait_candidates(np.zeros((180,320,3),np.uint8))
    assert len(anchors)==1 and anchors[0]['body_anchor']
    assert anchors[0]['box']==[116.,20,48.,49.]


@pytest.mark.parametrize('mode,qualifies',[('auto',True),('balanced',False)])
def test_short_two_subject_shot_can_split_only_in_automatic_mode(monkeypatch,mode,qualifies):
    import cv2
    import split_layout
    monkeypatch.setenv('FRAMING_PRESET',mode);monkeypatch.setenv('VIDEO_TEMPLATE','none')
    monkeypatch.setattr(split_layout,'ENABLED',True)
    class Capture:
        def isOpened(self):return True
        def get(self,key):
            return {cv2.CAP_PROP_FPS:30,cv2.CAP_PROP_FRAME_WIDTH:320,cv2.CAP_PROP_FRAME_COUNT:30}.get(key,0)
        def set(self,*args):pass
        def read(self):return True,np.full((180,320,3),100,np.uint8)
        def release(self):pass
    monkeypatch.setattr(cv2,'VideoCapture',lambda _:Capture())
    boxes=[dict(box=[30,40,35,35],score=1225),dict(box=[240,40,35,35],score=1225)]
    monkeypatch.setattr(main,'detect_portrait_candidates',lambda _:boxes)
    monkeypatch.setattr(main,'detect_face_candidates',lambda _:boxes)
    result=split_layout.detect_split_scenes('fixture',[(T(0,30.),T(30,30.))],['GENERAL'])
    assert bool(result)==qualifies
