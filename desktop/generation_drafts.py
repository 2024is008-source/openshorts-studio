"""Versioned generation drafts for validated imports, on the authenticated local API."""
import asyncio
import json
import math
from pathlib import Path
import re
import threading
from fastapi import HTTPException, Request
from story_director import atomic_json
from generation_options import normalize_options, clip_target_options


def validate_settings(settings, duration):
    allowed = {'SourceHasCaptions','AutoDuration','AutoCount','MinimumSeconds','MaximumSeconds','HighlightStrategy','OutputFormat','Mode','Analysis','AnalysisCategory','AnalysisPrompt','SummarySeconds','TargetClips','TargetSeconds','CaptionPreset','Captions','Quality','Framing','Pacing','TrimSilence','AudioPreset','AudioTarget','AudioPeak','AudioFade','AudioNoise','AutoHook'}
    if not isinstance(settings,dict) or set(settings)-allowed:
        raise ValueError('Unsupported settings field')
    for key in ('SourceHasCaptions','AutoDuration','AutoCount','Captions','TrimSilence','AudioNoise','AutoHook'):
        if key in settings and type(settings[key]) is not bool: raise ValueError('Invalid boolean setting')
    if settings.get('SourceHasCaptions') and settings.get('Captions'):raise ValueError('Disable new captions when source captions are already present')
    if settings.get('HighlightStrategy','auto') != 'auto': raise ValueError('This generation API supports automatic selection; manual source ranges and key-moment strategy are unavailable')
    if settings.get('OutputFormat','vertical') not in ('vertical','square','horizontal'): raise ValueError('Unsupported aspect ratio')
    normalize_options(settings.get('Mode'),settings.get('Analysis'),settings.get('SummarySeconds'),settings.get('CaptionPreset'),settings.get('Quality'),settings.get('Framing'),settings.get('Pacing'),settings.get('TrimSilence'),settings.get('AudioPreset'),settings.get('AudioTarget'),settings.get('AudioPeak'),settings.get('AudioFade'),settings.get('AudioNoise'))
    from adaptive_analysis.runtime import CATEGORIES
    if settings.get('AnalysisCategory','auto') not in CATEGORIES:raise ValueError('Unsupported analysis category')
    if not isinstance(settings.get('AnalysisPrompt',''),str) or len(settings.get('AnalysisPrompt',''))>500:raise ValueError('Invalid analysis prompt')
    count=settings.get('TargetClips',5)
    if type(count) is not int or not 1<=count<=12: raise ValueError('Clip count must be between 1 and 12')
    minimum,maximum=settings.get('MinimumSeconds'),settings.get('MaximumSeconds')
    def finite(value,low,high):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high: raise ValueError('Invalid duration setting')
    if minimum is not None: finite(minimum,5,min(175,duration))
    if maximum is not None: finite(maximum,10,180)
    if minimum is not None and maximum is not None and maximum<minimum+5: raise ValueError('Maximum duration must be at least five seconds above minimum')
    if settings.get('AutoDuration') and settings.get('Mode')=='highlights': raise ValueError('Highlight summaries require a target duration')
    if not settings.get('AutoDuration'): clip_target_options(settings.get('TargetSeconds',30),minimum,maximum)


def register(engine):
    @engine.app.get('/api/desktop/caption-presets')
    async def caption_presets():
        from caption_renderer import PRESETS,options
        return {'presets':{name:options(name) for name in PRESETS}}
    lock=threading.Lock()
    def source(identity):
        if not re.fullmatch(r'[0-9a-f]{32}',identity): raise HTTPException(404,'Imported source not found')
        root=Path(engine.UPLOAD_DIR).resolve()/'native-imports'
        folder=root/identity
        if root.is_symlink() or folder.is_symlink(): raise HTTPException(400,'Linked import storage is unsupported')
        try: media=json.loads((folder/'manifest.json').read_text('utf-8'))
        except (OSError,ValueError): raise HTTPException(404,'A validated import is required')
        return folder,media
    def read(identity):
        folder,_=source(identity);path=folder/'generation-draft.json'
        if not path.exists(): return {'draft':None}
        try: return {'draft':json.loads(path.read_text('utf-8'))}
        except (OSError,ValueError): raise HTTPException(409,'Saved settings could not be read; the existing draft was preserved')
    def save(identity,body):
        with lock:
            folder,media=source(identity)
            if not isinstance(body,dict) or set(body)-{'Version','Revision','SourceId','Settings','Encoder','OutputLocation','TemplateId'}: raise ValueError('Unsupported draft fields')
            if type(body.get('Version')) is not int or body.get('Version')!=1 or body.get('SourceId')!=identity: raise ValueError('Unsupported draft version or source')
            path=Path(media['path'])
            if not path.is_file() or path.stat().st_size!=media['size'] or path.stat().st_mtime_ns!=media['mtime_ns']: raise ValueError('The source was removed or changed. Import it again')
            validate_settings(body.get('Settings'),media['duration'])
            if body.get('Encoder') not in ('auto','x264','nvenc'): raise ValueError('Unsupported encoder')
            if Path(body.get('OutputLocation','')).resolve()!=Path(engine.OUTPUT_DIR).resolve(): raise ValueError('Use the current project output location')
            if not isinstance(body.get('TemplateId'),str):raise ValueError('Invalid template selection')
            from video_templates import selected
            if body.get('TemplateId'): selected(body['TemplateId'])
            existing=read(identity)['draft']
            if existing and existing.get('Version')!=1: raise HTTPException(409,'This draft requires a newer application version')
            revision=(existing or {}).get('Revision',0)
            if type(body.get('Revision')) is not int or body['Revision']!=revision: raise HTTPException(409,'Settings changed in another window. Reopen settings before saving')
            body['Revision']=revision+1
            atomic_json(str(folder/'generation-draft.json'),body)
            if body['Settings'].get('AnalysisCategory','auto')!='auto':
                try:
                    from category_intelligence import record_correction
                    record=json.loads((folder/'category-result.json').read_text('utf-8'))
                    record_correction(record['source_identity']['sha256'],record['result'],body['Settings']['AnalysisCategory'])
                except (OSError,ValueError,KeyError,TypeError):pass
            return {'draft':body}
    @engine.app.get('/api/desktop/imports/{identity}/settings')
    async def get(identity:str):return await asyncio.to_thread(read,identity)
    @engine.app.post('/api/desktop/imports/{identity}/category')
    async def detect_category(identity:str):
        folder,media=source(identity)
        path=Path(media['path'])
        if not path.is_file() or path.stat().st_size!=media['size'] or path.stat().st_mtime_ns!=media['mtime_ns']:
            raise HTTPException(409,'Imported source changed; import it again')
        from desktop.category_analysis import analyze
        return await asyncio.to_thread(analyze,path,media['duration'],folder)
    @engine.app.put('/api/desktop/imports/{identity}/settings')
    async def put(identity:str,request:Request):
        raw=await request.body()
        if len(raw)>32768:raise HTTPException(413,'Settings draft is too large')
        try:return await asyncio.to_thread(save,identity,json.loads(raw))
        except (ValueError,OSError,TypeError) as error:raise HTTPException(400,str(error)[:200])
