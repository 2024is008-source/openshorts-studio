"""Clear foreground, diffuse background and lower-band caption regression."""
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

import caption_renderer as cr
import layout_ranges as lr
from caption_timing import caption_position
from framing_geometry import contain_background, blur_strength
from subtitles import _escape_ffmpeg_filter_value
from test_caption_api import caption_job  # noqa: F401
from test_export_quality_api import job, request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401


@pytest.mark.parametrize('source',[(1920,1080),(640,480),(720,720),(1080,1920)])
def test_clear_foreground_bounds_survive_sidecar_and_trims(tmp_path,source):
    clip=str(tmp_path/'clip.mp4')
    lr.write(clip,[(0,4,'BLUR')],source_size=source,output_size=(1080,1920))
    rows=lr.read(clip);bottom=lr.blur_ranges(rows)[0][2]
    expected=(1+min(1080/source[0],1920/source[1])*source[1]/1920)/2
    assert bottom==pytest.approx(expected,abs=1e-6)
    mapped=lr.remap(rows,[dict(start=1,end=3)])
    assert lr.blur_ranges(mapped)==[(0,2,bottom)]
    lr.write(clip,mapped)
    assert lr.read(clip)==mapped
    assert lr.blur_ranges([(0,4,'GENERAL')])==[(0,4,.67)]


def speech():
    return {'segments':[{'words':[dict(word=' SHOPPING',start=.1,end=.5),
                                  dict(word=' CART',start=.55,end=.9)]}]}


@pytest.mark.parametrize('width,height',[(270,480),(1080,1920)])
def test_large_two_line_captions_fit_below_clear_image(tmp_path,width,height):
    path=tmp_path/'captions.ass';bottom=.658203125
    cr.generate(speech(),0,1,path,width,height,preset='bold-creator',blurs=[(0,1,bottom)],
                faces=[dict(x=0,y=.67,width=1,height=.3)])
    text=path.read_text(encoding='utf-8-sig')
    for line in text.splitlines():
        if not line.startswith('Dialogue: 1'):continue
        size=float(re.search(r'\\fs([\d.]+)',line)[1])
        ys=[float(y) for y in re.findall(r'\\pos\([\d.]+,([\d.]+)\)',line)]
        assert min(ys)-size*.6>bottom*height
        assert max(ys)+size*.6<height*.81
    assert caption_position(.2,blurs=[(0,1,bottom)],font_ratio=.03)[1]>.7


def test_placement_switches_at_layout_cut_without_losing_word_clock(tmp_path):
    path=tmp_path/'cut.ass'
    cr.generate(speech(),0,1,path,preset='bold-creator',blurs=[(.3,1,.66)])
    text=path.read_text(encoding='utf-8-sig')
    assert '0:00:00.30' in text
    assert '0:00:00.50' in text and '0:00:00.55' in text


def frame(tmp_path,name,graph):
    path=tmp_path/f'{name}.png'
    subprocess.run(['ffmpeg','-v','error','-y','-nostdin','-f','lavfi','-i',
                    'testsrc2=s=320x180:r=30:d=1,drawgrid=w=12:h=12:t=2:c=white','-filter_complex',graph,'-map','[v]',
                    '-frames:v','1','-threads','1',str(path)],
                   check=True,capture_output=True,timeout=20)
    return np.asarray(Image.open(path).convert('RGB')).astype(float)


def test_real_background_is_more_diffuse_and_foreground_unchanged(tmp_path,monkeypatch):
    # Compare the actual filters, including intentional sharp source graphics.
    monkeypatch.setenv('REFRAME_BLUR_STRENGTH','12')
    weak=frame(tmp_path,'weak',contain_background(270,480))
    monkeypatch.setenv('REFRAME_BLUR_STRENGTH','64')
    strong=frame(tmp_path,'strong',contain_background(270,480))
    assert np.array_equal(weak[170:310],strong[170:310])
    def edges(image):return np.abs(np.diff(image[5:100],axis=1)).mean()
    assert edges(strong)<edges(weak)*.7
    # Render text onto the same background and measure actual changed pixels.
    ass=tmp_path/'sample.ass'
    cr.generate(speech(),0,1,ass,270,480,preset='bold-creator',blurs=[(0,1,.6583)])
    safe=_escape_ffmpeg_filter_value(str(ass))
    fonts=_escape_ffmpeg_filter_value(str(Path('fonts').resolve()))
    graph=contain_background(270,480,output='base')+f";[base]setpts=PTS+0.25/TB,ass=filename='{safe}':fontsdir='{fonts}'[v]"
    captioned=frame(tmp_path,'captioned',graph)
    changes=np.max(np.abs(captioned-strong),axis=2)>35
    y,x=np.where(changes)
    assert len(y)>100 and y.min()>480*.6583 and y.max()<480*.81


def test_blur_settings_bounded_and_missing_values_safe(monkeypatch):
    for value,expected in [('bad',64),('nan',64),('-1',12),('999',96)]:
        monkeypatch.setenv('REFRAME_BLUR_STRENGTH',value)
        assert blur_strength()==expected


def test_editor_receives_blur_geometry_and_exact_preview(caption_job):
    import json
    data=json.loads(caption_job['meta'].read_text())
    data['shorts'][0]['layout_ranges']=[dict(start=0,end=2,layout='blur',content_bottom=.66)]
    caption_job['meta'].write_text(json.dumps(data))
    response=request('GET','/api/clip/quality-job/0/transcript')
    assert response.json()['blurRanges']==[[0,2,.66]]
    preview=request('POST','/api/subtitle/preview',json=dict(job_id='quality-job',clip_index=0,caption_preset='bold-creator'))
    assert preview.status_code==200,preview.text
    assert preview.json()['quality_report']['accepted']
