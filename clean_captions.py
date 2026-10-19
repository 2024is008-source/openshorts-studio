"""Resolution-aware phrase captions with selective keyword emphasis."""
import re
from pathlib import Path
from framing_geometry import caption_safe_ratio
from subtitles import _ass_time, _escape_ass_text, _collect_word_blocks

STOP = set('a an the and or but is are was were be been i you he she it we they my your our to of in on at for with that this these those have has had do did all so as if its im'.split())


def generate(transcript, start, end, path, width=1080, height=1920,
             splits=None, editorials=None):
    # Four-word phrases, punctuation/gaps also close a phrase. No animation that
    # changes line geometry every time the active word changes.
    raw = _collect_word_blocks(transcript, start, end, max_chars=30, max_duration=1.8)
    blocks = []
    for block in raw:
        group = []
        for word in block:
            if group and (len(group)>=4 or word['start']-group[-1]['end']>.35 or
                          re.search(r'[.!?]$',group[-1]['word'])):
                blocks.append(group); group=[]
            group.append(word)
        if group: blocks.append(group)
    if not blocks: return False
    # Typical portrait size is 64px; scale by width, cap for landscape outputs.
    size = round(min(width*.059, height*.055))
    margin = round(height * caption_safe_ratio())
    outline = max(2, round(size*.055))
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,{round(width*.09)},{round(width*.09)},{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    for block in blocks:
        candidates=[i for i,w in enumerate(block) if re.sub(r'[^\w]','',w['word']).lower() not in STOP]
        keyword=max(candidates,key=lambda i: (any(c.isdigit() for c in block[i]['word']),len(block[i]['word']))) if candidates else -1
        # Balanced explicit two-line break when the phrase is long.
        lengths=[len(w['word']) for w in block]
        split=min(range(1,len(block)),key=lambda i:abs(sum(lengths[:i])-sum(lengths[i:]))) if len(block)>1 and sum(lengths)>19 else -1
        for i,w in enumerate(block):
            a=w['start']; b=min(block[i+1]['start'],w['end']+.25) if i+1<len(block) else w['end']+.10
            b=min(b,end-start)
            if b<=a: continue
            parts=[]
            for j,other in enumerate(block):
                text=_escape_ass_text(other['word']).upper()
                if j==keyword and i>=j: text='{\\c&H00FF49&}'+text+'{\\r}'
                parts.append(('\\N' if j==split else ' ' if j else '')+text)
            seam = ('{\\an5\\pos('+str(width//2)+','+str(height//2)+')}'
                    if any(x<=a<y for x,y in (splits or [])) else
                    '{\\an5\\pos('+str(width//2)+','+str(round(height*.60))+')}'
                    if any(x<=a<y for x,y in (editorials or [])) else '')
            events.append(f'Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{seam}{"".join(parts)}')
    Path(path).write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    return bool(events)
