"""Deterministic caption timing/phrase geometry. No model or frame-rate clock."""
import math
import re
import unicodedata


def finite(value, default=None):
    try:
        value=float(value)
        return value if math.isfinite(value) else default
    except (ValueError,TypeError): return default


def relative_words(transcript,start,end,offset=0):
    """Clip source timing, skip unaligned tokens, and resolve overlaps forward.

    Segment-only fallback remains a phrase: do not invent per-word alignment.
    Whisper continuation fragments retain their original timing when merged.
    """
    start,end=finite(start),finite(end)
    if start is None or end is None or end<=start: return []
    offset=max(-1,min(1,finite(offset,0)))
    raw=[]
    if not isinstance(transcript,dict):return []
    for segment in transcript.get('segments',[]) or []:
        if not isinstance(segment,dict): continue
        valid=[]
        for w in segment.get('words',[]) or []:
            if not isinstance(w,dict): continue
            a,b=finite(w.get('start')),finite(w.get('end'))
            text=str(w.get('word') or '')
            if a is not None and b is not None and b>a and text.strip():
                if valid and not text.startswith(' '):
                    valid[-1]['word']+=text;valid[-1]['end']=max(valid[-1]['end'],b)
                    valid[-1]['aligned']=valid[-1]['aligned'] and w.get('aligned',True)
                    if w.get('emphasis'):valid[-1]['emphasis']=True
                else: valid.append(dict(word=text,start=a,end=b,aligned=w.get('aligned',True),**({'emphasis':True} if w.get('emphasis') else {})))
        if not valid:
            a,b=finite(segment.get('start')),finite(segment.get('end'))
            text=str(segment.get('text') or '').strip()
            if a is not None and b is not None and b>a and text:
                valid=[dict(word=text,start=a,end=b,aligned=False)]
        raw.extend(valid)
    words=[]
    for w in sorted(raw,key=lambda w:(w['start'],w['end'])):
        if w['end']<=start or w['start']>=end: continue
        a=max(0,w['start']-start+offset)
        b=min(end-start,w['end']-start+offset)
        if b<=a: continue
        if words and a<words[-1]['end']:
            if a<=words[-1]['start']:
                # Equal-start overlaps cannot support separate highlights.
                words[-1]['word']+=' '+w['word'].strip()
                words[-1]['end']=max(words[-1]['end'],b)
                words[-1]['aligned']=False
                continue
            words[-1]['end']=round(a,4)
        words.append(dict(word=' '.join(w['word'].split()),start=round(a,4),end=round(b,4),aligned=w['aligned'],**({'emphasis':True} if w.get('emphasis') else {})))
    return words


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def phrases(words,max_chars=30,max_duration=2.5,max_words=6,min_duration=0):
    blocks=[];current=[]
    for word in words:
        text=' '.join(w['word'] for w in current)
        if current and (word['start']-current[-1]['end']>.45 or
                (re.search(r'[.!?。！？][\"\'”’)]*$',current[-1]['word']) and current[-1]['end']-current[0]['start']>=min_duration) or
                display_width(text+' '+word['word'])>max_chars or len(current)>=max_words or
                word['end']-current[0]['start']>max_duration):
            blocks.append(current);current=[]
        current.append(word)
    if current: blocks.append(current)
    return blocks


def caption_position(t,position='bottom',splits=(),editorials=(),faces=(),max_lines=2,font_ratio=.03,end=None,line_spacing=1.25,safe_top=.12,safe_bottom=.20,blurs=()):
    """Normalized center coordinates; faces are output-space normalized boxes.

    Choose once per phrase to avoid text moving on every spoken word. Detection
    regions must describe the delivered frame, never untransformed source boxes.
    """
    half=min(.20,max_lines*font_ratio*line_spacing/2+.015)
    low,high=safe_top+half,1-safe_bottom-half
    bottom=max([row[2] for row in blurs if row[0]<=t<row[1]]+[0])
    if 0 < bottom < 1-safe_bottom-.04:
        # Only lower-band candidates: foreground faces cannot push text over video.
        low=max(low,bottom+.015+half)
        return .48,max(low,high)
    preferred=.5 if any(a<=t<b for a,b in splits) else .60 if any(a<=t<b for a,b in editorials) else {
        'top':low,'middle':.46,'bottom':high}.get(position,high)
    candidates=[max(low,min(high,y)) for y in (preferred,high,low,.46)]
    active=[f for f in faces if finite(f.get('start'),0)<(end if end is not None else t+1e-6) and finite(f.get('end'),1e12)>t]
    def collision(y):
        return sum(max(0,min(y+half,finite(f.get('y'),0)+finite(f.get('height'),0))-
                       max(y-half,finite(f.get('y'),0))) for f in active
                   if finite(f.get('x'),0)<.88 and finite(f.get('x'),0)+finite(f.get('width'),0)>.08)
    return .48,min(candidates,key=lambda y:(collision(y),abs(y-preferred)))
