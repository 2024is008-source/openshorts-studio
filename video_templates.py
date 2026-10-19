"""Versioned visual identity settings over the existing ASS/FFmpeg renderer.

Templates contain style only. Timed headlines/labels belong to individual edits.
No network, external assets, arbitrary filter strings or automatic AI requests.
"""
import copy
import json
import os
from pathlib import Path
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import caption_renderer
import hook_layer
from ffmpeg_utils import escape_filter_value, METADATA_SCRUB

Color = Annotated[str, Field(pattern=r'^#[0-9A-Fa-f]{6}$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)


class Fonts(Strict):
    family: Literal['Anton','Arial','Verdana','Impact','Georgia','Courier New','Helvetica','Noto Serif'] = 'Arial'
    caption_size: float = Field(default=58,ge=24,le=240)
    hook_scale: float = Field(default=1,ge=.7,le=1.3)


class Colors(Strict):
    base: Color = '#15191E'
    text: Color = '#FFFFFF'
    primary: Color = '#00D9EC'
    secondary: Color = '#FFE500'
    outline: Color = '#111418'


class Borders(Strict):
    width: float = Field(default=3,ge=0,le=20)
    shadow: float = Field(default=1,ge=0,le=4)


class SafeZones(Strict):
    side: float = Field(default=.12,ge=.08,le=.2)
    top: float = Field(default=.12,ge=.12,le=.24)
    bottom: float = Field(default=.2,ge=.2,le=.32)


class HookStyle(Strict):
    enabled: bool = True
    panel: bool = False
    animation: Literal['none','fade','scale-pop','slide-up','spring','highlight-reveal'] = 'fade'
    y: float = Field(default=.06,ge=.04,le=.18)
    seconds: float = Field(default=3,ge=.5,le=4)


class Captions(Strict):
    preset: Literal['openshorts-dynamic','creator-bold','clean-podcast','cinematic','minimal','green-pop','teal-reveal','paper-focus'] = 'openshorts-dynamic'
    position: Literal['top','middle','bottom'] = 'bottom'
    max_lines: int = Field(default=2,ge=1,le=2)
    max_words: int = Field(default=5,ge=2,le=8)


class Motion(Strict):
    accent: Literal['none','line','corner'] = 'line'
    entrance: Literal['none','fade','slide'] = 'fade'
    seconds: float = Field(default=2,ge=.5,le=4)


class Layout(Strict):
    preference: Literal['preserve','context','subject'] = 'preserve'
    split_supported: bool = True


class Logo(Strict):
    enabled: bool = False
    text: str = Field(default='OpenShorts',min_length=1,max_length=24)
    position: Literal['top-left','top-right'] = 'top-left'

    @field_validator('text')
    @classmethod
    def printable(cls,value):
        if any(ord(c)<32 for c in value):raise ValueError('Logo text must be printable')
        return value


class Audio(Strict):
    preset: Literal['natural','dialogue','original'] = 'natural'
    target: float = Field(default=-16,ge=-24,le=-12)
    ceiling: float = Field(default=-2,ge=-6,le=-1)
    fade: float = Field(default=0,ge=0,le=2)
    noise: bool = False


class Template(Strict):
    version: Literal[1] = 1
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    name: str = Field(min_length=1,max_length=80)
    fonts: Fonts = Field(default_factory=Fonts)
    colors: Colors = Field(default_factory=Colors)
    borders: Borders = Field(default_factory=Borders)
    safe: SafeZones = Field(default_factory=SafeZones)
    hook: HookStyle = Field(default_factory=HookStyle)
    captions: Captions = Field(default_factory=Captions)
    motion: Motion = Field(default_factory=Motion)
    layout: Layout = Field(default_factory=Layout)
    logo: Logo = Field(default_factory=Logo)
    transition: Literal['cut'] = 'cut'
    audio: Audio = Field(default_factory=Audio)


class Headline(Strict):
    text: str = Field(default='',max_length=300)
    start: float = Field(default=0,ge=0)
    end: float = Field(default=3,gt=0,le=180)


class Label(Strict):
    kind: Literal['speaker','progress']
    text: str = Field(min_length=1,max_length=50)
    start: float = Field(ge=0)
    end: float = Field(gt=0,le=180)
    evidence: str = Field(min_length=1,max_length=400)

    @field_validator('text','evidence')
    @classmethod
    def nonempty(cls,value):
        if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('Labels require printable source text')
        return value


class Content(Strict):
    headline: Headline = Field(default_factory=Headline)
    labels: list[Label] = Field(default_factory=list,max_length=12)


def normalize(value):
    return Template.model_validate(value).model_dump(mode='json')


@lru_cache(maxsize=1)
def _starters():
    path=Path(__file__).parent/'assets'/'video_templates.json'
    return [normalize(t) for t in json.loads(path.read_text(encoding='utf-8'))]


def catalog(directory=None):
    templates=copy.deepcopy(_starters())
    if directory is not None:
        custom=Path(directory)/'custom_video_templates.json'
        if custom.is_file():
            if custom.stat().st_size>256*1024:raise ValueError('Template library too large')
            data=json.loads(custom.read_text(encoding='utf-8'))
            if not isinstance(data,list) or len(data)>50:raise ValueError('Invalid template library')
            templates.extend(normalize(t) for t in data)
    return templates


def selected(template_id, context=None):
    if template_id in (None,'','none'):return None
    if template_id=='auto':
        story=(context or {}).get('story') or {}
        mode=story.get('mode') or (context or {}).get('editing_kind')
        template_id={'challenge':'challenge','podcast':'podcast','educational':'story-focus','emotional':'story-focus','comedy':'creator-energy'}.get(mode,'minimal-studio')
    if os.getenv('VIDEO_TEMPLATES_ENABLED','1')=='0':
        raise ValueError('Video templates are disabled')
    for template in catalog():
        if template['id']==template_id:return template
    raise ValueError('Unknown starter video template')


def framing_preference():
    """Reuse existing subject/context policies; never force a split or crop."""
    explicit=os.getenv('FRAMING_PRESET')
    if explicit in ('auto','balanced','subject','editorial'):return explicit
    template=selected(os.getenv('VIDEO_TEMPLATE'))
    if template:return {'context':'editorial','subject':'subject','preserve':'auto'}[template['layout']['preference']]
    return 'auto'



def source_text(transcript):
    from caption_timing import relative_words
    return ' '.join(w['word'] for w in relative_words(transcript,0,180)).strip()


def content(value,transcript,duration):
    parsed=Content.model_validate(value or {}).model_dump(mode='json')
    headline=parsed['headline']
    context=source_text(transcript)
    if headline['text']:
        if not 0<=headline['start']<headline['end']<=duration+.001:
            raise ValueError('Template headline interval must fit the clip')
        if not hook_layer.grounded(headline['text'],context):
            raise ValueError('Template headline must be a complete source-backed quote')
    for label in parsed['labels']:
        if not 0<=label['start']<label['end']<=duration+.001:raise ValueError('Invalid label timing')
        # Do not label a visual expression as a known emotion or invent a score.
        import re
        evidence=hook_layer.normalized(label['evidence'])
        text=hook_layer.normalized(label['text'])
        if evidence not in hook_layer.normalized(context) or not re.search(r'(?<!\w)'+re.escape(text)+r'(?!\w)',evidence):
            raise ValueError('Labels require their exact text in retained source speech')
        if label['kind']=='progress' and not re.search(r'\d',text):
            raise ValueError('Progress overlays require source-backed numbers')
        if label['kind']=='progress' and not hook_layer.grounded(label['text'],context):
            raise ValueError('A progress label must quote a complete numeric source statement, including its qualifiers')
        if any(ord(c)<32 for c in label['text']+label['evidence']):
            raise ValueError('Labels must contain printable text')
    return parsed


def initial_content(template,transcript,duration):
    decision=hook_layer.suggest(hook_layer.source_rows(transcript,[dict(start=0,end=duration)]),duration)
    return dict(headline=dict(text=decision['text'] if decision else '',start=0,
                end=min(duration,template['hook']['seconds'])),labels=[])


def audio_settings(template):
    import audio_mastering
    cfg=normalize(template)['audio']
    return audio_mastering.settings(audio_mastering.options(cfg['preset'],cfg['target'],cfg['ceiling'],cfg['fade'],cfg['noise']))


def _clear(rect,start,end,faces):
    x,y,w,h=rect
    return not any(f.get('start',0)<end and f.get('end',1e9)>start and
        max(x,f['x'])<min(x+w,f['x']+f['width']) and
        max(y,f['y'])<min(y+h,f['y']+f['height']) for f in faces)


def make_ass(path,template,transcript,duration,size,*,text=None,ranges=(),faces=(),captions=True,auto_effects=()):
    """Shared preview/final graphics: ASS vectors, existing captions and hooks."""
    from subtitles import _ass_time,_escape_ass_text,_hex_to_ass_inline_color
    import layout_ranges
    cfg=normalize(template);w,h=size
    data=content(text,transcript,duration)
    protected=list(faces)
    visual_regions=list(faces)+hook_layer.context_regions(ranges)
    headline=data['headline'];event=''
    if cfg['hook']['enabled'] and headline['text']:
        layer=dict(**headline,animation=cfg['hook']['animation'],
            style='dark' if cfg['hook']['panel'] else 'outline',y=cfg['hook']['y'])
        event=hook_layer.ass_event(layer,w,h,faces=visual_regions,
            appearance=dict(font=cfg['fonts']['family'],scale=cfg['fonts']['hook_scale'],
                color=cfg['colors']['text'],background=cfg['colors']['base'],
                outline=cfg['colors']['outline'],border=cfg['borders']['width']))
        if event:protected.append(dict(start=headline['start'],end=headline['end'],x=.08,
            y=hook_layer.placement(layer,visual_regions),width=.84,height=.16))
    made=False
    if captions:
        made=caption_renderer.generate(transcript,0,duration,str(path),w,h,cfg['captions']['preset'],
            auto_effects=auto_effects,
            font_name=cfg['fonts']['family'],font_size=cfg['fonts']['caption_size'],
            font_color=cfg['colors']['text'],highlight_color=cfg['colors']['primary'],
            border_color=cfg['colors']['outline'],border_width=cfg['borders']['width'],shadow=cfg['borders']['shadow'],
            safe_top=cfg['safe']['top'],safe_bottom=cfg['safe']['bottom'],safe_side=cfg['safe']['side'],
            **{k:v for k,v in cfg['captions'].items() if k!='preset'},
            splits=layout_ranges.split_ranges(ranges),editorials=layout_ranges.editorial_ranges(ranges),blurs=layout_ranges.blur_ranges(ranges),faces=protected)
        import render_runtime
        render_runtime.require_captions(transcript,0,duration,True,made)
    if not made:
        caption_renderer.generate({'segments':[dict(start=0,end=.05,text='header')]},0,duration,str(path),w,h)
        raw=Path(path).read_text(encoding='utf-8-sig')
        Path(path).write_text('\n'.join(line for line in raw.splitlines() if not line.startswith('Dialogue:'))+'\n',encoding='utf-8-sig')
    raw=Path(path).read_text(encoding='utf-8-sig')
    raw=hook_layer.append_ass(raw,event)
    def vector(rect,color,start,end,slide=False):
        x,y,bw,bh=[round(v*(w if i%2==0 else h)) for i,v in enumerate(rect)]
        position=rf'\move({x-round(w*.02)},{y},{x},{y},0,220)' if slide else rf'\pos({x},{y})'
        tags=rf'\an7{position}\bord0\shad0\c{_hex_to_ass_inline_color(color)}\p1'
        if cfg['motion']['entrance']!='none':tags+=r'\fad(180,150)'
        return f'Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{{{tags}}}m 0 0 l {bw} 0 {bw} {bh} 0 {bh}\n'
    # A narrow identity accent occupies <0.1% of the picture and disappears early.
    accent=cfg['motion']['accent'];finish=min(duration,cfg['motion']['seconds'])
    rect=(cfg['safe']['side'],.055,.12,.004)
    if accent!='none' and _clear(rect,0,finish,visual_regions):
        raw+=vector(rect,cfg['colors']['primary'],0,finish,cfg['motion']['entrance']=='slide')
        if accent=='corner':raw+=vector((rect[0],rect[1],.006,.028),cfg['colors']['secondary'],0,finish)
        elif _clear((rect[0]+rect[2]+.008,rect[1],.025,rect[3]),0,finish,visual_regions):
            raw+=vector((rect[0]+rect[2]+.008,rect[1],.025,rect[3]),cfg['colors']['secondary'],0,finish)
    def label_event(label,start,end,rect,color):
        if not _clear(rect,start,end,protected+visual_regions):return ''
        x,y,_,_=rect
        from caption_timing import display_width
        font_size=min(w*.025,rect[2]*w/max(1,display_width(label)*1.05))
        tags=rf'\an7\pos({round(x*w)},{round(y*h)})\fn{cfg["fonts"]["family"]}\fs{font_size:.2f}\bord{w*.0015:.2f}\shad0\c{_hex_to_ass_inline_color(color)}\fad(100,100)'
        return f'Dialogue: 3,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{{{tags}}}{_escape_ass_text(label)}\n'
    if cfg['logo']['enabled']:
        x=cfg['safe']['side'] if cfg['logo']['position']=='top-left' else .56
        raw+=label_event(cfg['logo']['text'],0,duration,(x,.075,.3,.04),cfg['colors']['text'])
    for label in data['labels']:
        raw+=label_event(label['text'],label['start'],label['end'],(.14,.35,.7,.045),cfg['colors']['secondary'])
    Path(path).write_text(raw,encoding='utf-8-sig')
    return cfg


def render(clean,output,template,transcript,duration,*,text=None,size=None,ranges=(),faces=None,captions=True,runner=None,auto_effects=()):
    import tempfile
    import export_quality
    import reframe_v2
    cfg=normalize(template)
    if os.getenv('VIDEO_TEMPLATES_ENABLED','1')=='0':raise ValueError('Video templates are disabled')
    if size is None:
        video,_=export_quality.streams(export_quality.probe(clean));size=(video['width'],video['height'])
    if faces is None:faces=caption_renderer.detect_face_regions(clean,duration)
    with tempfile.TemporaryDirectory(prefix='template_',dir=Path(output).parent) as work:
        ass=Path(work)/'template.ass'
        make_ass(ass,cfg,transcript,duration,size,text=text,ranges=ranges,faces=faces,captions=captions,auto_effects=auto_effects)
        command=['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_threads','1','-i',str(clean),
            '-vf',f"ass=filename='{escape_filter_value(str(ass))}':fontsdir='{escape_filter_value(str(Path(__file__).parent/'fonts'))}'",
            '-map','0:v:0','-map','0:a?',*reframe_v2.director_encoder(*size),'-c:a','copy',
            *METADATA_SCRUB,'-movflags','+faststart',str(output)]
        (runner or reframe_v2._run)(command)
    return cfg
