"""Source-backed headline decisions and time-based ASS animation. No AI calls.

Automatic text is extractive: retained Gemini suggestions can rank a quote,
but cannot introduce words or events absent from the selected source speech.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ANIMATIONS = ('none', 'fade', 'scale-pop', 'slide-up', 'spring', 'highlight-reveal')
KINDS = ('challenge', 'curiosity', 'emotional', 'question', 'fact', 'funny')


class Layer(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=300)
    start: float = Field(default=0, ge=0)
    end: float = Field(gt=0)
    position: Literal['top', 'center', 'bottom'] = 'top'
    y: float | None = Field(default=None, ge=.04, le=.26)
    size: Literal['S', 'M', 'L'] = 'M'
    style: Literal['classic','dark','yellow','red','outline','outline_yellow'] = 'classic'
    animation: Literal['none','fade','scale-pop','slide-up','spring','highlight-reveal'] = 'fade'

    @model_validator(mode='after')
    def valid(self):
        if self.end <= self.start or not self.text.strip():
            raise ValueError('Hook needs nonempty text and an increasing display interval.')
        if any(ord(c)<32 and c not in '\n\t' for c in self.text):
            raise ValueError('Hook contains control characters.')
        return self


def normalized(text):
    return ' '.join(str(text).casefold().split())


def grounded(text, context):
    """Quote complete utterances so trimming a negation cannot reverse a claim."""
    quote,source=normalized(text),normalized(context)
    if not quote:return False
    start=source.find(quote)
    while start>=0:
        before=source[:start].rstrip();after=source[start+len(quote):].lstrip()
        if (not before or before[-1] in '.!?。！？') and (not after or quote[-1] in '.!?。！？'):
            return True
        start=source.find(quote,start+1)
    return False


def source_rows(transcript, segments):
    """Map only known speech timing through the selected source segments."""
    if not isinstance(transcript,dict) or not isinstance(transcript.get('segments',[]),list):return []
    rows=[];offset=0.
    for selected in segments:
        a,b=float(selected['start']),float(selected['end'])
        if not math.isfinite(a+b) or not 0<=a<b:raise ValueError('Invalid selected source segment.')
        for segment in (transcript or {}).get('segments',[]):
            if not isinstance(segment,dict):continue
            words=segment.get('words')
            for word in words if isinstance(words,list) and words else [segment]:
                if not isinstance(word,dict):continue
                try:s,e=float(word['start']),float(word['end'])
                except (KeyError,TypeError,ValueError):continue
                # Do not quote words or coarse transcript segments cut in half.
                if not (math.isfinite(s+e) and a<=s<e<=b):continue
                text=str(word.get('word',word.get('text',''))).strip()
                if text:rows.append(dict(text=text,start=s-a+offset,end=e-a+offset,source_start=s,source_end=e))
        offset+=b-a
    return rows


def kind(text, context_kind='general'):
    t=text.casefold()
    if context_kind=='comedy' or re.search(r'\b(laugh|funny|joke|hilarious)\b',t): return 'funny'
    if context_kind=='emotional' or re.search(r'\b(love|cry|family|miss|heart)\b',t): return 'emotional'
    if context_kind=='challenge' or re.search(r'\b(challenge|win|beat|finish|million)\b',t): return 'challenge'
    if '?' in text: return 'question'
    if re.search(r'\b(actually|percent|fact|times|seconds)\b|\d',t): return 'fact'
    return 'curiosity'


def suggest(rows, duration, *, hint='', context_kind='general', scenes=(), requested_kind=None):
    """Rank natural spoken openings. Never trim/reorder footage implicitly.

    Rows are clip-relative retained speech; source timestamps stay in evidence.
    Only complete, short sentences in the first three seconds qualify. Unknown
    timings and oversized/fragmentary speech produce no automatic headline.
    """
    valid=[]
    for row in rows[:12000]:
        try:
            s,e=float(row['start']),float(row['end'])
            if not (math.isfinite(s) and math.isfinite(e) and 0<=s<e<=duration+.01):continue
            text=str(row.get('text',row.get('word',''))).strip()
            if text:valid.append(dict(row,start=s,end=e,text=text))
        except (TypeError,ValueError,KeyError):continue
    valid.sort(key=lambda r:r['start'])
    candidates=[];phrase=[]
    for row in valid:
        if row['start']>=3:break
        if phrase and (row['start']-phrase[-1]['end']>.65 or
            (row.get('source_start') is not None and phrase[-1].get('source_end') is not None and
             abs(row['source_start']-phrase[-1]['source_end'])>1.)):phrase=[]
        phrase.append(row)
        text=' '.join(r['text'] for r in phrase)
        if text.endswith(('.', '!', '?', '。', '！', '？')):
            if 2<=len(text.split())<=18 and len(text)<=160:
                category=kind(text,context_kind)
                if category=='curiosity' and not (hint and grounded(text,hint)) and not re.search(r'\b(look|inside|discover\w*|secret|unexpected|happen\w*|found|wonder\w*|why|how)\b',text.casefold()):
                    phrase=[];continue
                if requested_kind and category!=requested_kind:
                    phrase=[];continue
                scene_match=any(abs(float(t)-phrase[0]['start'])<.35 for t in scenes if isinstance(t,(int,float)))
                score=(2 if '?' in text else 0)+(2 if category!='curiosity' else 0)+(3 if hint and grounded(text,hint) else 0)+int(scene_match)-phrase[0]['start']*.25
                candidates.append(dict(text=text,kind=category,start=0.,end=min(3.,duration),
                    opening_start=phrase[0]['start'],opening_end=row['end'],score=round(score,3),
                    evidence=[dict(start=r['start'],end=r['end'],source_start=r.get('source_start'),source_end=r.get('source_end'),text=r['text']) for r in phrase],
                    reason='Exact retained speech; opening timing'+(' and retained scene boundary.' if scene_match else '.'),
                    version=1))
            phrase=[]
    candidates.sort(key=lambda c:(-c['score'],c['opening_start'],c['text']))
    return candidates[0] if candidates else None


def placement(layer, faces=()):
    """Reserve an independent top band; omit when known subjects occupy it.

    Face envelopes cover the whole display interval, including tracked motion.
    Callers may pass other protected regions with the same normalized geometry.
    This cannot establish safety for visual information that was never detected.
    """
    layer=Layer.model_validate(layer)
    preferred=layer.y if layer.y is not None else {'top':.06,'center':.42,'bottom':.68}[layer.position]
    choices=[preferred] if layer.position!='top' else list(dict.fromkeys([preferred,.06,.16,.26]))
    for y in choices:
        if all(not (float(f.get('start',0))<layer.end and float(f.get('end',layer.end))>layer.start and
            float(f['x'])<.94 and float(f['x'])+float(f['width'])>.06 and
            float(f['y'])<y+.16 and float(f['y'])+float(f['height'])>y-.025) for f in faces):
            return y
    return None


def context_regions(ranges):
    """Protect layouts chosen to retain distributed screen/editorial content."""
    import layout_ranges
    return [dict(start=r['start'],end=r['end'],x=0.,y=0.,width=1.,height=.6)
        for r in layout_ranges.normalise(ranges) if r['layout'] in ('editorial','screencast','inset')]


def ass_event(layer, width, height, *, faces=(), appearance=None):
    """An independent ASS layer, shared by director preview and final export."""
    from PIL import ImageFont
    from subtitles import _ass_time, _escape_ass_text
    layer=Layer.model_validate(layer)
    y=placement(layer,faces)
    if y is None:return ''
    # Use the app's existing Arial preset. Windows DirectWrite can ignore a
    # bundled Noto family even when libass reports loading the font file.
    family=appearance['font'] if appearance else 'Arial'
    windows_font={'Arial':'arialbd.ttf','Verdana':'verdanab.ttf','Georgia':'georgiab.ttf',
                  'Impact':'impact.ttf','Courier New':'courbd.ttf','Helvetica':'arialbd.ttf'}
    paths=[Path('C:/Windows/Fonts')/windows_font.get(family,'arialbd.ttf'),
           Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf'),Path(__file__).parent/'fonts'/'NotoSerif-Bold.ttf']
    font_path=next((p for p in paths if p.is_file()),paths[-1])
    # Fit both width and height; preserve manual newlines and break long words.
    base=width*.045*{'S':.8,'M':1.,'L':1.3}[layer.size]
    if appearance:base*=appearance['scale']
    lines=[]
    for size in range(max(8,round(base)),3,-1):
        font=ImageFont.truetype(str(font_path),size) if font_path.is_file() else ImageFont.load_default(size=size)
        lines=[]
        for paragraph in layer.text.splitlines():
            line=''
            for word in paragraph.split():
                if font.getlength((line+' '+word).strip())<=width*.78:line=(line+' '+word).strip();continue
                if line:lines.append(line);line=''
                for char in word:
                    if line and font.getlength(line+char)>width*.78:lines.append(line);line=''
                    line+=char
            if line:lines.append(line)
        if len(lines)*size*1.4<=height*.13:break
    if not lines or len(lines)*size*1.4>height*.13:
        raise ValueError('Headline cannot fit the hook safe area; shorten the text.')
    text=r'\N'.join(_escape_ass_text(line) for line in lines)
    # All animation timing is milliseconds, independent of export frame rate.
    ms=min(280,round((layer.end-layer.start)*1000/3));fade=min(100,ms)
    x=round(width/2);py=round(height*(y+.08))
    tags=rf'\an5\pos({x},{py})\fnArial\b1\fs{size}\q2'
    if layer.animation=='fade':tags+=rf'\fad({ms},{fade})'
    elif layer.animation=='scale-pop':tags+=rf'\fscx85\fscy85\t(0,{ms},\fscx100\fscy100)\fad({fade},{fade})'
    elif layer.animation=='spring':tags+=rf'\fscx85\fscy85\t(0,{ms//2},\fscx105\fscy105)\t({ms//2},{ms},\fscx100\fscy100)\fad({fade},{fade})'
    elif layer.animation=='slide-up':
        tags=tags.replace(rf'\pos({x},{py})',rf'\move({x},{py+round(height*.02)},{x},{py},0,{ms})')+rf'\fad({fade},{fade})'
    elif layer.animation=='highlight-reveal':tags+=rf'\clip(0,0,0,{height})\t(0,{ms},\clip(0,0,{width},{height}))\fad({fade},{fade})'
    # Existing presets supply text color, contrasting stroke/background, shadow.
    colors={'classic':('000000','FFFFFF'),'dark':('FFFFFF','141212'),'yellow':('000000','00D6FF'),'red':('FFFFFF','2626DC'),'outline':('FFFFFF','000000'),'outline_yellow':('00D6FF','000000')}
    fg,bg=colors[layer.style]
    if appearance:
        from subtitles import _hex_to_ass_inline_color
        fg=_hex_to_ass_inline_color(appearance['color']).removeprefix('&H').removesuffix('&')
        bg=_hex_to_ass_inline_color(appearance['background'] if not layer.style.startswith('outline') else appearance['outline']).removeprefix('&H').removesuffix('&')
        tags=tags.replace(r'\fnArial',rf'\fn{appearance["font"]}')
    border=1 if layer.style.startswith('outline') else 3
    stroke=max(.5,appearance['border']*width/1080) if appearance else max(1,width*.006)
    tags+=rf'\c&H{fg}&\3c&H{bg}&\bord{stroke:.2f}\shad{width*.002:.2f}'
    # A distinct style is required for opaque backgrounds (BorderStyle 3).
    style=f'Hook{border}'
    return f'Dialogue: 2,{_ass_time(layer.start)},{_ass_time(layer.end)},{style},,0,0,0,,{{{tags}}}{text}\n'


def append_ass(content, event):
    styles=''.join(f'Style: Hook{b},Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,{b},3,1,5,0,0,0,1\n' for b in (1,3))
    return content.replace('[Events]',styles+'\n[Events]')+event


def render(video, output, layer, *, faces=(), runner=None, preview=False):
    import json
    import subprocess
    import tempfile
    import caption_renderer
    import reframe_v2
    from ffmpeg_utils import escape_filter_value, METADATA_SCRUB
    layer=Layer.model_validate(layer)
    probe=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height:format=duration','-of','json',str(video)],timeout=30)
    try:
        info=json.loads(probe);stream=info['streams'][0];w,h=int(stream['width']),int(stream['height'])
        duration=float(info['format']['duration'])
        if not (2<=w<=8192 and 2<=h<=8192 and w*h<=33177600 and math.isfinite(duration) and duration>0):raise ValueError()
    except (KeyError,IndexError,TypeError,ValueError):raise ValueError('A readable, bounded video stream and duration are required.')
    if layer.end>duration+.05:raise ValueError('Hook interval exceeds this clip.')
    seek=max(0.,layer.start-.3) if preview else 0.
    length=min(8.,duration-seek) if preview else None
    if preview:
        layer=layer.model_copy(update=dict(start=layer.start-seek,end=min(layer.end-seek,length)))
        faces=[dict(f,start=float(f.get('start',0))-seek,end=float(f.get('end',layer.end))-seek) for f in faces]
    event=ass_event(layer,w,h,faces=faces)
    if not event:raise ValueError('No hook safe area is clear of retained subjects; remove or reposition the hook.')
    with tempfile.TemporaryDirectory(prefix='hook_layer_') as work:
        path=Path(work)/'hook.ass'
        caption_renderer.generate({'segments':[dict(start=0,end=.05,text='header')]},0,layer.end,str(path),w,h)
        content='\n'.join(l for l in path.read_text(encoding='utf-8-sig').splitlines() if not l.startswith('Dialogue:'))+'\n'
        path.write_text(append_ass(content,event),encoding='utf-8-sig')
        cmd=['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_threads','1',*(['-ss',str(seek)] if preview else []),'-i',str(video),*(['-t',str(length)] if preview else []),'-vf',f"ass=filename='{escape_filter_value(str(path))}':fontsdir='{escape_filter_value(str(Path(__file__).parent/'fonts'))}'",'-map','0:v:0','-map','0:a?',*reframe_v2.director_encoder(w,h),'-c:a','aac' if preview else 'copy',*METADATA_SCRUB,'-movflags','+faststart',str(output)]
        if runner:runner(cmd)
        else:subprocess.run(cmd,check=True,capture_output=True,timeout=300)
    return True
