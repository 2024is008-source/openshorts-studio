"""Regression-report checks must distinguish invalid evidence from no evidence."""
from benchmarks.verify_system import ass_audit, caption_audit


def test_missing_haar_uses_packaged_mediapipe_and_clamps_boxes(tmp_path,monkeypatch):
    import cv2
    import numpy as np
    import sys
    from types import SimpleNamespace as NS
    import caption_renderer as captions
    closed=[]
    class Detector:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):closed.append(True)
        def process(self,image):
            box=NS(xmin=-.1,ymin=.1,width=.4,height=1)
            return NS(detections=[NS(location_data=NS(relative_bounding_box=box))])
    monkeypatch.setattr(cv2.data,'haarcascades',str(tmp_path))
    monkeypatch.setattr(cv2,'CascadeClassifier',lambda *args:(_ for _ in ()).throw(AssertionError('Missing asset must not be opened')))
    monkeypatch.setitem(sys.modules,'mediapipe',NS(solutions=NS(face_detection=NS(FaceDetection=Detector))))
    with captions._face_boxes(cv2) as boxes:
        values=boxes(np.zeros((100,200,3),dtype=np.uint8))
    assert values[0][0]==0 and abs(values[0][2]-60)<.001
    assert values[0][1:2]==(10.,) and values[0][3]==90
    assert closed==[True]


def test_missing_both_face_backends_keeps_safe_fallback(tmp_path,monkeypatch):
    import cv2
    import sys
    import caption_renderer as captions
    path=tmp_path/'clip.mp4';path.touch()
    monkeypatch.setattr(cv2.data,'haarcascades',str(tmp_path))
    monkeypatch.setitem(sys.modules,'mediapipe',None)
    assert captions.detect_face_regions(path,1)==[]


def test_caption_audit_clamps_overlap_without_claiming_missing_alignment():
    transcript = {'segments': [{'words': [
        {'word': ' Hello', 'start': 10, 'end': 11},
        {'word': ' there.', 'start': 10.8, 'end': 11.5}]}]}
    result = caption_audit(transcript, 10.2, 11.2)
    assert result['tokens'] == 2 and result['aligned_tokens'] == 2
    assert result['finite_inside_clip'] and result['nonoverlapping']
    assert caption_audit({}, 0, 1)['status'] == 'UNVERIFIED'


def test_ass_audit_rejects_bad_bounds_and_malformed_events():
    valid = 'Dialogue: 0,0:00:00.10,0:00:00.50,Default,,0,0,0,,Hello'
    assert ass_audit(valid, 1)['status'] == 'PASS'
    assert ass_audit(valid, .2)['status'] == 'FAIL'
    assert ass_audit('Dialogue: broken', 1)['status'] == 'FAIL'
    assert ass_audit('[Events]', 1)['status'] == 'UNVERIFIED'
