"""Validated edit decisions and dependency keys; no AI or source-path inputs."""
import copy
import hashlib
import json
import math
import re
from pathlib import Path

import caption_timing
import recut

VERSION = 1
ACTIVE = {'queued', 'rendering'}


def workspace_state(value):
    allowed={'title','assets_visible','inspector_visible','preview_ratio','playhead','segment_index','caption_id','assets_width','inspector_width','timeline_height'}
    if not isinstance(value,dict) or set(value)-allowed:raise ValueError('Invalid editor workspace state.')
    for name in ('assets_visible','inspector_visible'):
        if name in value and type(value[name]) is not bool:raise ValueError('Panel visibility must be Boolean.')
    for name,limit in (('title',200),('caption_id',64)):
        if name in value and (not isinstance(value[name],str) or len(value[name])>limit or any(ord(c)<32 for c in value[name])):raise ValueError('Invalid workspace text.')
    if 'preview_ratio' in value and value['preview_ratio'] not in ('9:16','1:1','16:9','Source'):raise ValueError('Invalid preview aspect ratio.')
    if 'playhead' in value:number(value['playhead'],0,864000)
    for field in ('assets_width','inspector_width','timeline_height'):
        if field in value:number(value[field],200,800)
    if 'segment_index' in value and (type(value['segment_index']) is not int or not 0<=value['segment_index']<1000):raise ValueError('Invalid selected segment.')
    return copy.deepcopy(value)


def export_options(value):
    if value is None:return {}
    if not isinstance(value,dict) or set(value)-{'size','fps','encoder','quality'}:raise ValueError('Invalid export options.')
    size=value.get('size')
    if size is not None and size not in ([1080,1920],[1080,1080],[1920,1080],[720,1280],[1280,720]):raise ValueError('Unsupported export resolution.')
    fps=value.get('fps')
    if fps is not None and (type(fps) not in (int,float) or fps not in (24,25,30,50,60)):raise ValueError('Unsupported export frame rate.')
    if value.get('encoder','auto') not in ('auto','x264','nvenc'):raise ValueError('Unsupported export encoder.')
    if value.get('quality','balanced') not in ('fast','balanced','high'):raise ValueError('Unsupported export quality.')
    return copy.deepcopy(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()[:24]


def identity(path):
    if not path or not Path(path).is_file(): return None
    stat = Path(path).stat()
    return [Path(path).name, stat.st_size, stat.st_mtime_ns]


def origin(clip):
    return digest({key: clip.get(key) for key in
                   ('video_url', 'start', 'end', 'recipe', 'crop_overrides')})


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Edit values must be finite numbers.')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Edit value must be between {low:g} and {high:g}.')
    return round(value, 4)


def captions(transcript):
    """Stable phrase IDs in source time; retain real word timing when available."""
    segments = (transcript or {}).get('segments') or []
    end = max([caption_timing.finite(s.get('end'), 0) for s in segments
               if isinstance(s, dict)] + [0])
    blocks = caption_timing.phrases(caption_timing.relative_words(transcript, 0, end), 38, 3, 6)
    return [dict(id=str(i), start=b[0]['start'], end=b[-1]['end'],
                 text=' '.join(w['word'] for w in b), words=b) for i, b in enumerate(blocks)]


def normalize(edits, duration, rows):
    if not isinstance(edits, dict) or set(edits) - {'segments', 'caption_overrides', 'crop', 'style','template','template_content','audio','auto_edit'}:
        raise ValueError('Invalid timeline edit fields.')
    raw = edits.get('segments')
    if not isinstance(raw, list): raise ValueError('Video segments are required.')
    for row in raw:
        if not isinstance(row, dict) or set(row) != {'start', 'end'}:
            raise ValueError('Each segment needs start and end only.')
        number(row['start'], 0, duration); number(row['end'], 0, duration)
    segments = recut.normalize_segments(raw, duration)
    crop = edits.get('crop') or {'mode': 'preserve', 'x': .5, 'y': .5}
    if not isinstance(crop, dict) or set(crop) != {'mode', 'x', 'y'}:
        raise ValueError('Invalid crop fields.')
    if crop['mode'] not in ('preserve', 'crop', 'contain'):
        raise ValueError('Crop mode must preserve, crop, or contain.')
    crop = dict(mode=crop['mode'], x=number(crop['x'], 0, 1), y=number(crop['y'], 0, 1))
    style = edits.get('style') or {}
    if not isinstance(style, dict) or not {'enabled', 'preset', 'position'} <= set(style) or set(style)-{'enabled','preset','position','appearance'}:
        raise ValueError('Invalid caption style fields.')
    if type(style['enabled']) is not bool: raise ValueError('Caption enabled must be Boolean.')
    if style['preset'] not in ('clean-minimal', 'bold-creator', 'dynamic-highlight', 'podcast', 'cinematic', 'openshorts-dynamic', 'creator-bold', 'clean-podcast', 'minimal', 'green-pop', 'teal-reveal', 'paper-focus'):
        raise ValueError('Invalid caption preset.')
    if style['position'] not in ('top', 'middle', 'bottom'): raise ValueError('Invalid caption position.')
    if 'appearance' in style:
        import caption_renderer
        appearance=style['appearance']
        allowed={'font_name','font_size','font_color','highlight_color','border_color','border_width','shadow','effect',
                 'bg_color','bg_opacity','max_lines','max_words','sync_offset','min_phrase_duration','line_spacing','base_opacity','uppercase'}
        if not isinstance(appearance,dict) or set(appearance)-allowed: raise ValueError('Invalid caption appearance fields.')
        for key,value in appearance.items():
            if key=='font_name' and (not isinstance(value,str) or value not in caption_renderer.FONTS): raise ValueError('Unsupported caption font.')
            if key=='effect' and value not in ('none','fade','pop','glow','box','scale','reveal','bounce'): raise ValueError('Unsupported caption animation.')
            if key.endswith('color') and (not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value)): raise ValueError('Use #RRGGBB caption colors.')
            if key in ('font_size','border_width','shadow'):
                number(value,24 if key=='font_size' else 0,{'font_size':240,'border_width':20,'shadow':8}[key])
            bounds={'bg_opacity':(0,1),'max_lines':(1,3),'max_words':(1,12),'sync_offset':(-1,1),
                    'min_phrase_duration':(.15,1),'line_spacing':(1,1.6),'base_opacity':(.05,1)}
            if key in bounds:number(value,*bounds[key])
            if key in ('max_lines','max_words') and type(value) is not int:raise ValueError('Caption line/word limits must be integers.')
            if key=='uppercase' and type(value) is not bool:raise ValueError('Caption uppercase must be Boolean.')
    overrides = edits.get('caption_overrides') or {}
    if not isinstance(overrides, dict) or len(overrides) > 1000:
        raise ValueError('At most 1000 caption overrides are allowed.')
    ids = {row['id'] for row in rows}; normalized = {}
    for key, value in overrides.items():
        if key not in ids or not isinstance(value, dict) or not {'start','end','text'} <= set(value) or set(value)-{'start','end','text','words'}:
            raise ValueError('Unknown caption or invalid override.')
        a, b = number(value['start'], 0, duration), number(value['end'], 0, duration)
        text = value['text']
        if b <= a or b-a > 30 or not isinstance(text, str) or len(text) > 400 or any(ord(c)<32 and c!='\n' for c in text):
            raise ValueError('Caption text/timing is invalid (maximum 400 characters and 30 seconds).')
        normalized[key] = dict(start=a, end=b, text=text)
        if 'words' in value:
            original=next(row for row in rows if row['id']==key)['words']
            words=value['words']
            if not isinstance(words,list) or not original or not all(w.get('aligned') for w in original) or len(words)!=len(original):
                raise ValueError('Word timing requires existing aligned words.')
            previous=a; checked=[]
            for word,source_word in zip(words,original):
                if not isinstance(word,dict) or set(word)!={'word','start','end','emphasis'} or word['word']!=source_word['word'] or type(word['emphasis']) is not bool:
                    raise ValueError('Word text must match the aligned transcript; edit phrase text separately.')
                start,end=number(word['start'],a,b),number(word['end'],a,b)
                if start<previous or end<=start: raise ValueError('Word timings must be ordered and inside the phrase.')
                previous=end; checked.append(dict(word=word['word'],start=start,end=end,emphasis=word['emphasis']))
            if text!=' '.join(w['word'] for w in original): raise ValueError('Word timing cannot accompany rewritten phrase text.')
            normalized[key]['words']=checked
    result=dict(segments=segments, crop=crop, style=copy.deepcopy(style), caption_overrides=normalized)
    if edits.get('auto_edit') is not None:
        import auto_edit
        result['auto_edit']=auto_edit.normalize(auto_edit.retime(edits['auto_edit'],segments),recut.total_duration(segments))
    if 'audio' in edits:
        audio=edits['audio']
        if not isinstance(audio,dict) or set(audio)!={'volume','mute','fade','normalize','target','ceiling','music'}:raise ValueError('Invalid timeline audio settings.')
        for key,low,high in (('volume',0,2),('fade',0,2),('target',-30,-9),('ceiling',-9,-1)):number(audio[key],low,high)
        if type(audio['mute']) is not bool or type(audio['normalize']) is not bool:raise ValueError('Audio switches must be Boolean.')
        music=audio['music']
        if music is not None and (not isinstance(music,str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,180}',music) or Path(music).name!=music or Path(music).suffix.lower() not in ('.mp3','.wav','.m4a','.aac')):raise ValueError('Choose imported project audio for the music stem.')
        if music and not audio['normalize']:raise ValueError('Music mixing requires audio normalization.')
        result['audio']=copy.deepcopy(audio)
    if edits.get('template') is not None:
        import video_templates
        result['template']=video_templates.normalize(edits['template'])
        result['template_content']=video_templates.content(edits.get('template_content'),transcript(rows,result),recut.total_duration(segments))
    elif edits.get('template_content'):
        raise ValueError('Template content requires a template')
    return result


def initial(clip, segments, source_name):
    result=dict(version=VERSION, revision=0, source_ref=source_name, origin=origin(clip),
                status='draft', progress=0, run_id=None, result=None, error=None,
                edits=dict(segments=segments, caption_overrides={},
                           crop=dict(mode='preserve', x=.5, y=.5),
                           style=dict(enabled=True, preset='clean-minimal', position='bottom')))
    if clip.get('video_template'):
        import video_templates
        result['edits']['template']=video_templates.normalize(clip['video_template'])
        result['edits']['template_content']=copy.deepcopy(clip.get('template_content') or {})
        result['edits']['style']['enabled']=clip.get('template_captions_enabled',True)
    return result


def patched_source(rows, overrides):
    output = []
    for row in rows:
        override = overrides.get(row['id'])
        if override:
            # Corrected phrases do not claim new per-word alignment.
            words = [dict(w,word=' '+w['word'],aligned=True) for w in override['words']] if 'words' in override else [dict(word=' '+override['text'], start=override['start'],
                          end=override['end'], aligned=False)] if override['text'].strip() else []
            output.append(dict(start=override['start'],end=override['end'],text=override['text'], words=words))
        else:
            output.append(dict(start=row['start'], end=row['end'], text=row['text'],
                               words=[dict(w, word=' '+w['word']) for w in row['words']]))
    return {'segments': output}


def transcript(rows, edits):
    return recut.virtual_transcript(patched_source(rows,edits['caption_overrides']), edits['segments'])


def caption_source(clip, source):
    """Preserve saved timeline corrections through the existing subtitle modal."""
    overrides=clip.get('editor_caption_overrides')
    if not isinstance(overrides,dict) or not overrides:return source
    try:
        if clip.get('editor_caption_source_digest')!=digest(source):return source
        rows=captions(source)
        duration=max([row['end'] for row in rows]+[clip.get('end',0)])
        edits=initial({},[{'start':0,'end':min(1,duration)}],None)['edits']
        edits['caption_overrides']=overrides
        normalized=normalize(edits,duration,rows)
        return dict(source,**patched_source(rows,normalized['caption_overrides']))
    except (ValueError,KeyError,TypeError):return source


def segment_key(path, segment, crop, size, fps, audio):
    return digest([VERSION, identity(path), segment, crop, size, fps, audio])


def mapped_bounds(segment, canonical_segments):
    offset=0
    for row in canonical_segments:
        if row['start']<=segment['start'] and row['end']>=segment['end']:
            return dict(start=round(offset+segment['start']-row['start'],3),
                        end=round(offset+segment['end']-row['start'],3))
        offset+=row['end']-row['start']
    return None


def assembly_key(keys):
    return digest([VERSION, 'assembly', keys])


def caption_key(clean_key, mapped_transcript, style):
    return digest([VERSION, clean_key, mapped_transcript, style])


def local_markers(segments, source_times):
    output = []; offset = 0
    for segment in segments:
        for t in source_times:
            if segment['start'] < t < segment['end']:
                output.append(round(offset+t-segment['start'], 3))
        offset += segment['end']-segment['start']
    return sorted(set(output))
