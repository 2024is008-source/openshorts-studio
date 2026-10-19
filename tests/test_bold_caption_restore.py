"""Restore readable bundled Anton captions without disturbing word timing."""
import re

import caption_renderer as captions
import video_templates


def speech():
    return {'segments':[{'words':[dict(word=' '+word,start=i*.25,end=i*.25+.2)
        for i,word in enumerate(['guys','burn','100,000','calories.'])]}]}


def test_bold_presets_keep_large_bundled_anton_and_original_timestamps(tmp_path):
    for name in ['creator-bold','bold-creator']:
        path=tmp_path/(name+'.ass')
        assert captions.generate(speech(),0,1.5,path,preset=name)
        raw=path.read_text(encoding='utf-8-sig')
        assert 'Style: Default,Anton,220.00' in raw
        assert 'GUYS' in raw and 'CALORIES.' in raw and '0:00:00.25' in raw
        sizes=[float(n) for n in re.findall(r'\\fs([\d.]+)',raw)]
        assert min(sizes)>=180  # do not collapse back to the old ~60px look
        assert r'\c&H00E5FF&' in raw


def test_anton_width_uses_bundled_glyphs_not_a_wide_font_estimate():
    cfg=captions.options('creator-bold')
    width=captions._line_width('guys burn',220,cfg)
    assert 0<width<9*220*.8
    assert captions._line_width('guys burn',220,cfg)==captions._line_width('GUYS BURN',220,cfg)


def test_challenge_starter_has_readable_anton_but_other_styles_stay_available():
    template=video_templates.selected('challenge')
    assert template['fonts']['family']=='Anton' and template['fonts']['caption_size']==220
    assert template['borders']['width']==14
    assert captions.options(template['captions']['preset'])['uppercase']
    assert video_templates.selected('minimal-studio')['fonts']['family']=='Arial'
