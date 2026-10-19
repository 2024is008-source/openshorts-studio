"""Resolution-aware professional ASS captions using existing libass rendering."""
from pathlib import Path
from contextlib import contextmanager
from functools import lru_cache
import json
import os
import subprocess
import time
from caption_timing import relative_words,phrases,caption_position,display_width,finite
from subtitles import _ass_time,_escape_ass_text,hex_to_ass_color,_hex_to_ass_inline_color

PRESETS={
    'clean-minimal':dict(font_name='Arial',font_size=52,highlight_color='#FFFFFF',effect='fade',border_width=2,shadow=1),
    'bold-creator':dict(font_name='Anton',font_size=220,highlight_color='#FFE500',effect='pop',border_width=14,shadow=2,uppercase=True,max_words=4,line_spacing=1.05),
    'dynamic-highlight':dict(font_name='Arial',font_size=60,highlight_color='#00FF88',effect='glow',border_width=3,shadow=1),
    'podcast':dict(font_name='Arial',font_size=54,highlight_color='#FFD700',effect='none',border_width=2,bg_opacity=.55,shadow=1),
    'cinematic':dict(font_name='Georgia',font_size=50,highlight_color='#E8D7B5',effect='fade',border_width=1,shadow=2),
}
FONTS={'Anton','Arial','Verdana','Impact','Georgia','Courier New','Helvetica','Noto Serif'}
PRESETS.update({
    'openshorts-dynamic':dict(font_name='Arial',font_size=62,highlight_color='#00FF88',effect='bounce',border_width=3,shadow=1.5),
    'creator-bold':dict(font_name='Anton',font_size=220,highlight_color='#FFE500',effect='pop',border_width=14,shadow=2,uppercase=True,max_words=4,line_spacing=1.05),
    'clean-podcast':dict(font_name='Arial',font_size=54,highlight_color='#00FFFF',effect='none',border_width=2,bg_opacity=.35,shadow=1),
    'minimal':dict(font_name='Arial',font_size=50,highlight_color='#FFFFFF',effect='none',border_width=1,shadow=.5),
})
# Local looks built from the existing word-clock effects; no CEP code/assets.
PRESETS.update({
    'green-pop':dict(font_name='Anton',font_size=180,highlight_color='#00FF38',effect='pop',border_width=10,shadow=2,uppercase=True,max_words=4,line_spacing=1.1),
    'teal-reveal':dict(font_name='Anton',font_size=160,highlight_color='#45E6C0',effect='reveal',border_width=7,shadow=1,uppercase=True,max_words=4,line_spacing=1.1),
    'paper-focus':dict(font_name='Anton',font_size=140,font_color='#A0A0A0',highlight_color='#151515',effect='none',border_width=0,shadow=0,bg_color='#FFFFFF',bg_opacity=.95,max_words=4,line_spacing=1.1),
})
DISPLAY_PRESETS=('openshorts-dynamic','creator-bold','clean-podcast','cinematic','minimal')
FACE_PLACEMENT_VERSION=2
RENDER_VERSION=4


@lru_cache(maxsize=1)
def _anton_metrics():
    from PIL import ImageFont
    return ImageFont.truetype(str(Path(__file__).parent/'fonts'/'Anton-Regular.ttf'),1000)


def _line_width(text,size,cfg):
    if cfg['uppercase']:text=text.upper()
    # Preserve conservative sizing for scripts rendered by fallback fonts.
    if cfg['font_name']=='Anton' and text.isascii():
        try:return _anton_metrics().getlength(text)*size/1000
        except (OSError,ImportError):pass
    return display_width(text)*size*1.05


@contextmanager
def _face_boxes(cv2):
    """Reuse installed local detectors when an OpenCV wheel omits Haar data."""
    cascade=Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'
    if cascade.is_file():
        detector=cv2.CascadeClassifier(str(cascade))
        if not detector.empty():
            yield lambda image:detector.detectMultiScale(
                cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),scaleFactor=1.15,minNeighbors=5,minSize=(24,24))
            return
    import mediapipe as mp
    # Same packaged face model/backend used by main.py; no downloads or inferred
    # identity/emotion. A separate context keeps concurrent render jobs isolated.
    with mp.solutions.face_detection.FaceDetection(model_selection=1,min_detection_confidence=.5) as detector:
        def boxes(image):
            h,w=image.shape[:2]
            result=detector.process(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
            regions=[]
            for face in result.detections or []:
                b=face.location_data.relative_bounding_box
                x,y=max(0,b.xmin),max(0,b.ymin)
                right,bottom=min(1,b.xmin+b.width),min(1,b.ymin+b.height)
                if right>x and bottom>y:regions.append((x*w,y*h,(right-x)*w,(bottom-y)*h))
            return regions
        yield boxes


def detect_face_regions(path,duration):
    """Best-effort installed face detectors on three output frames, <=6 seconds.

    No source-coordinate boxes or new model download. Unavailable detection
    falls back to safe layout placement. Cache is invalidated by file identity.
    """
    if os.getenv('CAPTION_FACE_PLACEMENT','1')=='0' or duration<=0: return []
    try:
        stat=os.stat(path);key=[FACE_PLACEMENT_VERSION,stat.st_size,stat.st_mtime_ns,duration]
        cache=Path(str(path)+'.caption-regions.json')
        try:
            saved=json.loads(cache.read_text(encoding='utf-8'))
            if saved.get('key')==key: return saved['faces']
        except (OSError,ValueError,AttributeError,KeyError): pass
        import cv2
        import numpy as np
        deadline=time.monotonic()+6;faces=[]
        with _face_boxes(cv2) as boxes:
            for fraction,lo,hi in [(0,0,.25),(.5,.25,.75),(.9,.75,1)]:
                if deadline-time.monotonic()<.2: break
                try:
                    result=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-ss',str(duration*fraction),
                        '-i',str(path),'-frames:v','1','-vf','scale=480:480:force_original_aspect_ratio=decrease','-filter_threads','1',
                        '-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True,
                        timeout=min(2,deadline-time.monotonic()))
                    image=cv2.imdecode(np.frombuffer(result.stdout,dtype=np.uint8),cv2.IMREAD_COLOR)
                    if image is None: continue
                    h,w=image.shape[:2]
                    for x,y,bw,bh in boxes(image):
                        faces.append(dict(start=duration*lo,end=duration*hi,x=float(x/w),y=float(y/h),
                                          width=float(bw/w),height=float(bh/h)))
                except (OSError,subprocess.SubprocessError): continue
        try:
            from story_director import atomic_json
            atomic_json(cache,{'key':key,'faces':faces})
        except OSError: pass
        return faces
    except Exception: return []  # Optional local detection must not block captions.


def options(preset='clean-minimal',**overrides):
    values=dict(font_color='#FFFFFF',border_color='#000000',bg_color='#000000',
                bg_opacity=0,shadow=1,max_lines=2,position='bottom',effect='none',
                sync_offset=0,uppercase=False,base_opacity=1)
    values.update(max_words=6,min_phrase_duration=.45,line_spacing=1.25)
    values.update(PRESETS.get(preset,PRESETS['clean-minimal']))
    values.update({k:v for k,v in overrides.items() if v is not None})
    if values['font_name'] not in FONTS: values['font_name']='Arial'
    for key,lo,hi,default in [('font_size',24,240,52),('border_width',0,20,2),
            ('shadow',0,8,1),('bg_opacity',0,1,0),('max_lines',1,3,2),('sync_offset',-1,1,0),
            ('max_words',1,12,6),('min_phrase_duration',.15,1,.45),('line_spacing',1,1.6,1.25),('base_opacity',.05,1,1)]:
        values[key]=max(lo,min(hi,finite(values.get(key),default)))
    values['max_lines']=int(values['max_lines'])
    values['max_words']=int(values['max_words'])
    if values['effect'] not in ('none','fade','pop','glow','box','scale','reveal','bounce'): values['effect']='none'
    return values


def _curve_tags(elapsed,span,points):
    """Slice an animation's phrase/word clock without restarting at highlights."""
    def value(t):
        for (a,x),(b,y) in zip(points,points[1:]):
            if a<=t<b:return x+(y-x)*(t-a)/(b-a)
        return points[0][1] if t<points[0][0] else points[-1][1]
    scale=value(elapsed)
    tag=f'\\fscx{scale:.3f}\\fscy{scale:.3f}'
    targets=[(time,target) for time,target in points[1:] if elapsed<time<=elapsed+span]
    if not targets or targets[-1][0]<elapsed+span:targets.append((elapsed+span,value(elapsed+span)))
    cursor=0.
    for time,target in targets:
        if abs(target-scale)>1e-6:
            tag+=f'\\t({cursor:.3f},{time-elapsed:.3f},\\fscx{target:.3f}\\fscy{target:.3f})'
        scale=target;cursor=time-elapsed
    return tag


def animation_tags(effect,elapsed,span):
    if effect not in ('pop','bounce'):return ''
    points=[(0.,94.),(100.,102.5),(200.,100.)] if effect=='pop' else [(0.,98.),(90.,101.5),(220.,100.)]
    return _curve_tags(elapsed,span,points)


def generate(transcript,start,end,path,width=1080,height=1920,preset='clean-minimal',
             splits=(),editorials=(),faces=(),media_duration=None,blurs=(),auto_effects=(),**overrides):
    cfg=options(preset,**overrides)
    if width<2 or height<2: raise ValueError('Invalid caption output dimensions')
    duration=min(end-start,finite(media_duration,end-start))
    words=relative_words(transcript,start,start+duration,cfg['sync_offset'])
    # Font size is expressed at portrait 1080p, then constrained by both axes.
    size=min(cfg['font_size']*width/1080,height*.14)
    max_width=width*(1-2*max(.08,min(.2,finite(cfg.get('safe_side'),.12))))
    average=_line_width('ABCDEFGHIJKLMNOPQRSTUVWXYZ',size,cfg)/26 if cfg['font_name']=='Anton' else size*.72
    capacity=max(6,int(max_width/max(1,average)))
    blocks=phrases(words,capacity*cfg['max_lines'],2.5,cfg['max_words'],cfg['min_phrase_duration'])
    if not blocks: return False
    color=cfg['font_color']
    if cfg['base_opacity']<1:
        # Match the live preview's optional inactive-word dimming.
        import re
        if re.fullmatch(r'#[a-fA-F0-9]{6}',color):
            factor=.5+.5*cfg['base_opacity']
            color='#'+''.join(f'{round(int(color[i:i+2],16)*factor):02X}' for i in (1,3,5))
    primary=hex_to_ass_color(color)
    outline=hex_to_ass_color(cfg['border_color'],fallback='000000')
    # ASS BackColour is the shadow; the optional background is drawn separately.
    back=hex_to_ass_color('#000000',.65,fallback='000000')
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{cfg['font_name']},{size:.2f},{primary},{primary},{outline},{back},-1,0,0,0,100,100,0,0,1,{cfg['border_width']*width/1080:.2f},{cfg['shadow']*width/1080:.2f},5,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    for bi,block in enumerate(blocks):
        # Fixed phrase wrapping prevents highlights from changing line breaks.
        lower_band=any(r[0]<block[-1]['end'] and block[0]['start']<r[1] and 0<r[2]<.76 for r in blurs)
        row_limit=1 if lower_band else cfg['max_lines']
        line=0;lines=[[]];used=0
        for word in block:
            n=display_width(word['word'])
            exceeds=(_line_width(' '.join(w['word'] for w in lines[-1]+[word]),size,cfg)>max_width
                     if cfg['font_name']=='Anton' else used+n+1>capacity)
            if used and exceeds and line+1<row_limit:
                lines.append([]);line+=1;used=0
            lines[line].append(word);used+=n+1
        measured=max(_line_width(' '.join(w['word'] for w in row),size,cfg) for row in lines)
        fitted=size*min(1,max_width/max(1,measured))
        end_hold=min(duration,block[-1]['end']+.12,
                     blocks[bi+1][0]['start'] if bi+1<len(blocks) else duration)
        # Minimum reading hold may use a short silent gap, never cover next speech.
        if end_hold-block[0]['start']<cfg['min_phrase_duration']:
            end_hold=min(duration,block[0]['start']+cfg['min_phrase_duration'],
                         blocks[bi+1][0]['start'] if bi+1<len(blocks) else duration)
        blur_bottom=max([r[2] for r in blurs if r[0]<end_hold and block[0]['start']<r[1]]+[0])
        safe_end=1-finite(cfg.get('safe_bottom'),.2)
        if 0 < blur_bottom < safe_end-.04:
            fitted=min(fitted,(safe_end-blur_bottom-.04)*height/(len(lines)*cfg['line_spacing']))
        # Preserve word clocks across layout cuts; placement changes only at cuts.
        cuts=[t for r in blurs for t in r[:2] if block[0]['start']<t<end_hold]
        boundaries=sorted(set([w['start'] for w in block]+[w['end'] for w in block]+[end_hold]+cuts))
        for a,b in zip(boundaries,boundaries[1:]):
            if b-a<.01: continue
            effect=cfg['effect']
            for decision in auto_effects:
                if decision['start']<=a and decision['end']>=b and decision['intensity']>0:
                    effect={'kinetic_captions':'scale','word_pop':'pop','text_reveal':'reveal'}.get(decision['type'],effect)
            fade=''
            if effect=='fade' and a-block[0]['start']<.07:
                elapsed=max(0,(a-block[0]['start'])*1000)
                fade=f'{{\\alpha&H{round((1-elapsed/70)*255):02X}&\\t(0,{round(70-elapsed)},\\alpha&H00&)}}'
            active=next((w for w in block if w['start']<=a<w['end'] and w['aligned']),None)
            placement_time=max([block[0]['start']]+[t for t in cuts if t<=a])
            x,y=caption_position(placement_time,cfg['position'],splits,editorials,faces,
                len(lines),fitted/height,end=end_hold,line_spacing=cfg['line_spacing'],safe_top=finite(cfg.get('safe_top'),.12),safe_bottom=finite(cfg.get('safe_bottom'),.2),blurs=blurs)
            phrase_animation=animation_tags(effect,(a-block[0]['start'])*1000,(b-a)*1000)
            if cfg['bg_opacity']>0:
                rect_w=min(max_width,measured*fitted/size)+fitted*.4
                rect_h=len(lines)*fitted*cfg['line_spacing']+fitted*.3
                left,top=x*width-rect_w/2,y*height-rect_h/2
                drawing=(f'{{\\an7\\pos({left:.2f},{top:.2f})\\bord0\\shad0\\c{_hex_to_ass_inline_color(cfg["bg_color"])}'
                         f'\\alpha&H{round((1-cfg["bg_opacity"])*255):02X}&\\p1}}'
                         f'm 0 0 l {rect_w:.2f} 0 l {rect_w:.2f} {rect_h:.2f} l 0 {rect_h:.2f}')
                events.append(f'Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{drawing}')
            for ri,row in enumerate(lines):
                py=y*height+(ri-(len(lines)-1)/2)*fitted*cfg['line_spacing']
                soften='\\be1' if cfg['shadow']>0 else ''
                pos=f'{{\\an5\\pos({round(x*width)},{round(py)})\\fs{fitted:.2f}{soften}{phrase_animation}}}'
                parts=[]
                for w in row:
                    text=_escape_ass_text(w['word'].upper() if cfg['uppercase'] else w['word'])
                    if effect=='reveal' and w['aligned'] and a<w['start']:
                        parts.append('{\\alpha&HFF&}'+text+'{\\r}'+pos+fade)
                        continue
                    if w is active:
                        color=_hex_to_ass_inline_color(cfg['highlight_color'])
                        tag=f'\\c{color}'
                        if effect=='glow':tag+=f'\\3c{color}\\blur1.2'
                        if effect=='scale' or w.get('emphasis'):
                            ms=(w['end']-w['start'])*1000
                            tag+=_curve_tags((a-w['start'])*1000,(b-a)*1000,[(0.,100.),(min(80.,ms/3),106. if w.get('emphasis') else 103.),(ms,100.)])
                        parts.append('{'+tag+'}'+fade+text+'{\\r}'+pos+fade)
                    else:parts.append(fade+text)
                events.append(f'Dialogue: 1,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{pos}{fade}'+ ' '.join(parts))
    Path(path).write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    return bool(events)
