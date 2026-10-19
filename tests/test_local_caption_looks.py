"""Independent local styles, never dependent on the supplied Premiere extension."""
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image
import pytest

import caption_renderer as cr
import generation_options
import timeline_project
import video_templates
from subtitles import _escape_ffmpeg_filter_value
from test_caption_api import caption_job  # noqa: F401
from test_export_quality_api import job, request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401
from test_editing_director import signals, compile as compile_edl  # noqa: F401

LOOKS = ('green-pop', 'teal-reveal', 'paper-focus')


def speech():
    return {'segments': [{'words': [dict(word=' To', start=.1, end=.4),
                                   dict(word=' get', start=.6, end=.9),
                                   dict(word=' started!', start=1, end=1.4)]}]}


@pytest.mark.parametrize('preset', LOOKS)
def test_existing_director_keeps_selected_look(signals, monkeypatch, preset):
    monkeypatch.setenv('CAPTION_PRESET', preset)
    assert compile_edl(signals)['caption_preset'] == preset


@pytest.mark.parametrize('preset', LOOKS)
def test_settings_survive_generation_and_saved_editor(preset):
    assert generation_options.normalize_options(captions=preset)['CAPTION_PRESET'] == preset
    edits = timeline_project.initial({}, [dict(start=0, end=2)], None)['edits']
    edits['style']['preset'] = preset
    assert timeline_project.normalize(edits, 2, [])['style']['preset'] == preset
    template = video_templates.selected('minimal-studio')
    template['captions']['preset'] = preset
    assert video_templates.normalize(template)['captions']['preset'] == preset


@pytest.mark.parametrize('preset', LOOKS)
def test_unaligned_text_is_readable_without_invented_highlights(tmp_path, preset):
    ass = tmp_path/'missing.ass'
    assert cr.generate({'segments': [dict(start=10, end=12, text='Long {text} \\ café 世界!')]},
                       10, 12, ass, preset=preset)
    text = ass.read_text(encoding='utf-8-sig')
    events = '\n'.join(x for x in text.splitlines() if x.startswith('Dialogue: 1'))
    assert r'\c&H' not in events and r'\alpha&HFF&' not in events
    assert '(TEXT)' in events.upper() and '{text}' not in events and '世界' in events
    assert not cr.generate({}, 0, 2, tmp_path/'empty.ass', preset=preset)


@pytest.mark.parametrize('preset', LOOKS)
def test_preview_apply_and_reopen_preserve_large_style(caption_job, preset):
    base = dict(job_id='quality-job', clip_index=0, caption_preset=preset)
    before = caption_job['meta'].read_bytes()
    response = request('POST', '/api/subtitle/preview', json=base)
    assert response.status_code == 200, response.text
    assert response.json()['quality_report']['accepted']
    assert caption_job['meta'].read_bytes() == before
    response = request('POST', '/api/subtitle', json=base)
    assert response.status_code == 200, response.text
    saved = request('GET', '/api/clip/quality-job/0/transcript').json()['captionSettings']
    assert saved['caption_preset'] == preset and saved['font_name'] == 'Anton'
    assert saved['font_size'] == cr.PRESETS[preset]['font_size']
    if preset == 'paper-focus':
        assert saved['font_color'] == '#A0A0A0' and saved['bg_color'] == '#FFFFFF'


@pytest.mark.parametrize('preset', LOOKS)
def test_real_frames_follow_word_clock_and_remain_inside_frame(tmp_path, preset):
    ass = tmp_path/'sample.ass'; video = tmp_path/'sample.mp4'
    cr.generate(speech(), 0, 1.8, ass, 270, 480, preset=preset)
    safe = _escape_ffmpeg_filter_value(str(ass))
    fonts = _escape_ffmpeg_filter_value(str(Path('fonts').resolve()))
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                    'color=c=0x223344:s=270x480:r=30:d=1.8', '-vf',
                    f"ass=filename='{safe}':fontsdir='{fonts}'", '-c:v', 'libx264',
                    '-threads', '1', '-preset', 'ultrafast', str(video)],
                   check=True, capture_output=True, timeout=20)
    def frame(t):
        png = tmp_path/f'{t}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(video),
                        '-frames:v', '1', str(png)], check=True, capture_output=True, timeout=10)
        return np.asarray(Image.open(png).convert('RGB')).astype(int)
    during, gap, ending = frame(.25), frame(.5), frame(1.7)
    if preset != 'paper-focus':
        def colored(a):
            r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
            return (g > 120) & (g-r > 60) & ((g-b > 60) if preset == 'green-pop' else (b > 100))
        assert colored(during).sum() > 15
        assert colored(gap).sum() == 0 and colored(ending).sum() == 0
        y, x = np.where(colored(during))
    else:
        mask = during.min(axis=2) > 180  # actual opaque paper panel
        assert mask.sum() > 200
        y, x = np.where(mask)
        assert not (ending.min(axis=2) > 180).any()
    assert x.min() > 0 and x.max() < 269 and y.min() > 480*.12 and y.max() < 480*.8
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                              '-of', 'json', str(video)], timeout=5))
    assert (info['streams'][0]['width'], info['streams'][0]['height']) == (270, 480)
