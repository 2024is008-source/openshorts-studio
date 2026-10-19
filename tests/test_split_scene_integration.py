"""Positive split promotion through the real renderer, without provider calls."""
import subprocess
from pathlib import Path

import numpy as np


def test_grounded_independent_speaker_views_reach_actual_split_renderer(tmp_path,monkeypatch):
    import main
    import reframe_v2 as r
    import editing_director as d
    import active_speaker
    from scenedetect import FrameTimecode as T
    source=tmp_path/'two-views.mp4';output=tmp_path/'split.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=green:s=1920x1080:r=12:d=2',
        '-vf','drawbox=x=275:y=275:w=150:h=150:color=red:t=fill,drawbox=x=1495:y=275:w=150:h=150:color=blue:t=fill',
        '-c:v','libx264','-threads','2','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True,timeout=30)
    monkeypatch.setenv('EDIT_DIRECTOR','1');monkeypatch.setenv('FRAMING_PRESET','auto')
    monkeypatch.setenv('REFRAME_OUTPUT_SIZE','fullhd');monkeypatch.setenv('AUTO_CAPTIONS','0');monkeypatch.setenv('AUTO_HOOK','0')
    monkeypatch.setattr(main,'detect_scenes',lambda _:([(T(0,12.),T(24,12.))],12.))
    monkeypatch.setattr(main,'analyze_scenes_strategy',lambda *_:['TRACK'])
    monkeypatch.setattr(r.split_layout,'detect_split_scenes',lambda *a,**k:{0:((350,350,150,150),(1570,350,150,150))})
    monkeypatch.setattr(active_speaker,'ENABLED',False);monkeypatch.setattr(r.screencast_layout,'ENABLED',False);monkeypatch.setattr(r.punch_in,'ENABLED',False)
    context={'analysis':{'scene_observations':[dict(start=0,end=2,layout_intent='two_speaker_split',
        layout_evidence='Synthetic fixture: two independent stationary speaker views.',confidence=1.)]}}
    assert r.render(str(source),str(output),9/16,director_context=context)
    plan=d.load(output)
    assert plan['shots'][0]['layout']=='SPLIT' and len(plan['shots'][0]['regions'])==2
    assert 'Retained visual evidence' in plan['shots'][0]['reason']
    assert output.stat().st_size>0
