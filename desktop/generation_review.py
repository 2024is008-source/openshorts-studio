"""Native generation presentation adapter. No AI calls or alternate renderer.

Only allowlisted fields cross the bridge; raw provider logs never reach this UI.
Review preferences use their own atomic, revision-protected document.
"""
import asyncio
import json
import math
import re
import time
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from desktop.home import delivered, thumbnail

STAGES = (
    ('prepare', 'Preparing source', r'Job started by worker|[Pp]reparing|[Dd]ownloading'),
    ('transcribe', 'Transcribing audio', r'[Tt]ranscrib|Reusing (?:precomputed transcript|the transcript from)'),
    ('analyze', 'Analyzing content with Gemini', r'Analyzing with (?:Gemini|local LLM)|Gemini vision|Video analysis: chapter'),
    ('select', 'Selecting clip candidates', r'Found \d+ clips|Saved metadata|Analyzing with (?:Gemini|local LLM).*2-pass'),
    ('render', 'Rendering selected clips', r'Processing Clip|Detecting scenes|Step \d+:'),
    ('validate', 'Validating generated outputs', r'export checks finished'),
)
ADAPTIVE_STAGES=(STAGES[0],STAGES[1],
    ('detect_scenes','Detecting scenes',r'(?!)'),
    ('category','Detecting video category',r'(?!)'),
    ('story','Understanding story',r'(?!)'),
    ('visual_candidates','Finding visual candidates',r'(?!)'),
    ('merge','Merging highlights',r'(?!)'),
    ('verify','Verifying important moments',r'(?!)'),
    ('rank','Ranking clips',r'(?!)'),
    ('plan_edits','Planning AI edits',r'(?!)'),STAGES[4],STAGES[5])
ERRORS = (
    (r'quota|\b429\s+(?:RESOURCE_EXHAUSTED|Too Many Requests)\b|rate.limit|resource.exhausted', 'Gemini quota or rate limit reached. Check your provider allowance before retrying.'),
    (r'api[_ .-]?key[^\n]*(?:invalid|expired|rejected|missing)|(?:invalid|expired|missing)[^\n]*api[_ .-]?key|\bunauthenticated\b|\bunauthorized\b|\b(?:401|403)\s+(?:UNAUTHENTICATED|UNAUTHORIZED|FORBIDDEN|PERMISSION_DENIED)\b|permission.denied', 'Gemini authentication failed. Check the protected key in Settings.'),
    (r'no space|disk full|errno 28|insufficient.*space', 'There is insufficient storage. Free space or choose another library drive.'),
    (r'(?:audio )?transcription (?:has )?failed|failed to transcribe|whisper[^\n]*error', 'Audio transcription failed. Check the source audio and transcription setup.'),
    (r'invalid.*json|invalid.*response|jsondecode|no metadata', 'The AI response could not produce a valid selection. Review settings before retrying.'),
    (r'nvenc|cuda.*error|gpu.*fail', 'GPU processing failed. Select the CPU encoder and retry the affected operation.'),
    (r'ffmpeg|no clips could be rendered', 'Video rendering or output validation failed. Completed files were kept.'),
    (r'file.*not found|no such file|source.*missing', 'The source media is unavailable. Reimport it before retrying.'),
)

def number(value, default=0):
    try:
        value=float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def text(value, limit=500):
    if not isinstance(value, str): return ''
    # Metadata is user/provider controlled. Omit credentials and local paths too.
    if re.search(r'AIza[\w-]+|AQ\.[\w-]+|api[_ -]?key|[A-Za-z]:[\\/]|Bearer\s|https?://', value, re.I): return ''
    return ''.join(c for c in value if c.isprintable())[:limit]


def folder_for(engine, identity):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity) or identity not in engine.jobs:
        raise HTTPException(404, 'Project not found')
    root=Path(engine.OUTPUT_DIR).resolve()
    raw=root / identity
    folder=raw.resolve()
    if not folder.is_relative_to(root) or raw.is_symlink(): raise HTTPException(400, 'Invalid project')
    return folder


def read_json(path, default):
    try:
        if path.is_symlink() or path.stat().st_size>4*1024**2: return default
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError): return default


def metadata(folder):
    for path in sorted(folder.glob('*_metadata.json')):
        data=read_json(path,{})
        if isinstance(data,dict): return data
    return {}


def analysis_presentation(meta):
    """Expose missing scene understanding without leaking provider errors."""
    options=meta.get('job_options') if isinstance(meta.get('job_options'),dict) else {}
    state=meta.get('analysis_status') if isinstance(meta.get('analysis_status'),dict) else {}
    adaptive=str(options.get('ANALYSIS_MODE','')).startswith('adaptive-')
    requested=adaptive or options.get('ANALYSIS_MODE')=='hybrid' or meta.get('generation_mode')=='highlights'
    observed=meta.get('story_analysis') if isinstance(meta.get('story_analysis'),dict) else {}
    available=state.get('visual_available') is True or (any(r.get('verification_status')=='model_observed' for r in observed.get('moments',[]) if isinstance(r,dict)) if adaptive else bool(observed.get('moments')))
    warning=''
    if adaptive and not available:
        warning='Adaptive analysis: no verified visual moments are available. Unsupported visual claims and effects are withheld.'
    elif not available and (state.get('status')=='fallback' or requested):
        warning='Visual scene analysis did not complete. These clips use transcript fallback; AI effects and split decisions may be unavailable.'
    elif not available and options.get('ANALYSIS_MODE')=='transcript':
        warning='Transcript-only analysis: visual scene cues for automatic effects and splits were not requested.'
    status=state.get('status')
    if status not in ('completed','adaptive_completed','requested','fallback','not_requested'):status='unavailable' if requested else 'not_requested'
    return dict(visual_available=available,status='completed' if available else status,warning=warning)


def progress(engine, identity):
    folder=folder_for(engine,identity); job=engine.jobs[identity]
    raw=job.get('status','idle')
    state={'queued':'preparing','processing':'running','cancelled':'cancelled','completed':'completed','failed':'failed'}.get(raw,'idle')
    if job.get('cancel_requested') and state in ('running','preparing'): state='cancel_requested'
    logs='\n'.join(str(x) for x in job.get('logs',[]))
    adaptive_events={}
    for match in re.finditer(r'AMCE_PROGRESS (\{[^\r\n]*\})',logs):
        try:
            value=json.loads(match[1]);key=value.get('stage')
            if key in {s[0] for s in ADAPTIVE_STAGES}:adaptive_events[key]=(match.start(),value)
        except (ValueError,AttributeError):pass
    stage_specs=ADAPTIVE_STAGES if adaptive_events else STAGES
    observed=[]
    for key,label,pattern in stage_specs:
        matches=list(re.finditer(pattern,logs))
        if matches: observed.append((matches[-1].start(),key,label))
        if key in adaptive_events:observed.append((adaptive_events[key][0],key,label))
    observed.sort()
    current=observed[-1][1] if observed else 'prepare'
    # Completion follows observed sequential transitions, never an elapsed-time guess.
    seen={o[1] for o in observed}
    current_index=next(i for i,s in enumerate(stage_specs) if s[0]==current)
    stages=[]
    transcription=re.findall(r'Transcribing[\s…:.]*(\d{1,3})%',logs,re.I)
    transcript_percent=number(transcription[-1],None) if transcription else None
    if transcript_percent is not None and not 0<=transcript_percent<=100: transcript_percent=None
    if re.search(r'Reusing (?:precomputed transcript|the transcript from)',logs):transcript_percent=100
    chapters=re.findall(r'Video analysis(?: completed)?: chapter (\d+)/(\d+)',logs)
    chapter_percent=None
    completed_chapters=0
    if chapters:
        total_chapters=int(chapters[-1][1]);cache=read_json(folder/'story_analysis.json',{})
        completed_chapters=len(cache.get('chapters',[])) if isinstance(cache,dict) and isinstance(cache.get('chapters'),list) else 0
        if isinstance(cache,dict) and isinstance(cache.get('completed'),dict):completed_chapters+=len(cache['completed'])
        done=re.findall(r'Video analysis completed: chapter (\d+)/(\d+)',logs)
        if done:completed_chapters=max(completed_chapters,len({int(n) for n,total in done if total==chapters[-1][1]}))
        if total_chapters>0:chapter_percent=min(99,100*completed_chapters/total_chapters)
    ready={int(n) for n in re.findall(r'Clip (\d+) ready:',logs)}
    total=len(metadata(folder).get('shorts',[])) if ready else 0
    for i,(key,label,_) in enumerate(stage_specs):
        completed=key in seen and (i<current_index or state=='completed' or key=='transcribe' and transcript_percent==100)
        percent=100 if completed else transcript_percent if key=='transcribe' else chapter_percent if key=='analyze' else min(100,len(ready)/total*100) if key=='render' and total else None
        status='completed' if completed else 'active' if key==current and state in ('running','preparing','cancel_requested') else 'reported' if key in seen else 'not_reported'
        details={}
        if key in adaptive_events:
            event=adaptive_events[key][1];count=number(event.get('completed'),0);count_total=number(event.get('total'),None)
            if count_total is not None and 0<count_total<=1000000 and 0<=count<=count_total:percent=100*count/count_total
            else:percent=None
            if completed:percent=100
            details=dict(completed_count=int(count) if 0<=count<=1000000 else 0,total_count=count_total,
                elapsed_seconds=max(0,number(event.get('elapsed_seconds'),0)),cache_reuse=event.get('cache_reuse') is True,retry=event.get('retry') is True)
        if state=='failed' and key==current:status='failed'
        stages.append(dict(id=key,title=label,state=status,percent=percent,**details))
    timing=read_json(folder/'desktop-generation-time.json',{})
    start=job.get('native_started_at') or timing.get('started_at')
    finish=job.get('native_finished_at') or timing.get('finished_at')
    elapsed=max(0,number(finish or time.time())-number(start)) if start and (finish or state in ('running','preparing','cancel_requested')) else None
    error=None
    failure=read_json(folder/'analysis_failure.json',{})
    failure=failure if isinstance(failure,dict) else {}
    failure_diagnostics=[]
    if state=='failed':
        if failure or 'Hybrid visual analysis failed' in logs:
            chapter=number(failure.get('chapter'),None);total_chapters=number(failure.get('total_chapters'),None)
            location=f' at chapter {int(chapter)}/{int(total_chapters)}' if chapter and total_chapters else ''
            error=f'Visual scene analysis failed{location}. Completed analysis checkpoints were kept. No transcript-only clips were generated.'
            kind=failure.get('error_type','');code=failure.get('status_code')
            reason=('Gemini quota/rate limit reached.' if code==429 else
                'Gemini rejected authentication or authorization.' if code in (401,403) else
                'Gemini returned a server error.' if kind=='ServerError' else
                'The Gemini request timed out.' if isinstance(kind,str) and kind.endswith('Timeout') else '')
            if reason:error=f'Visual scene analysis failed{location}. {reason} Completed analysis checkpoints were kept. No transcript-only clips were generated.'
            if failure.get('adaptive') is True:
                error=f'Adaptive analysis did not produce usable grounded clips. {reason} Validated checkpoints were kept; unsupported visual claims were withheld.'.replace('  ',' ')
            failure_diagnostics.append(error)
            code=failure.get('status_code');kind=failure.get('error_type','')
            if type(code) is int and 100<=code<=599:failure_diagnostics.append(f'Provider HTTP status: {code}')
            if isinstance(kind,str) and re.fullmatch(r'[A-Za-z]{1,60}',kind):failure_diagnostics.append(f'Failure type: {kind}')
            for issue in (failure.get('issues') or [])[:8]:
                if not isinstance(issue,dict):continue
                field=issue.get('field','');kind=issue.get('type','')
                if isinstance(field,str) and isinstance(kind,str) and re.fullmatch(r'[a-z0-9_.?]{1,180}',field) and re.fullmatch(r'[a-z_]{1,60}',kind):
                    failure_diagnostics.append(f'Rejected field: {field} ({kind})')
            for row in stages:
                if row['id']=='analyze':row['state']='failed'
        else:
            error=next((message for pattern,message in ERRORS if re.search(pattern,logs,re.I)), 'The processing worker stopped before completion. Completed project files were kept.')
    return dict(state=state, overall=100 if state=='completed' else None,
        category=category_presentation(folder),
        analysis=analysis_presentation(metadata(folder)),
        stage=('Transcription complete · preparing next step' if current=='transcribe' and transcript_percent==100 else next((label for _,key,label in reversed(observed) if key==current),'Preparing source')),
        elapsed_seconds=elapsed, remaining_seconds=None, stages=stages, error=error,
        analysis_chapter=dict(current=int(chapters[-1][0]),total=int(chapters[-1][1]),completed=completed_chapters) if chapters else None,
        diagnostics=[f"Job state: {state}"]+[f"Reported: {o[2]}" for o in observed]+[line.strip() for line in logs.splitlines() if re.fullmatch(r'\s*Gemini chapter: (?:key slot \d{1,2}/\d{1,2} from (?:env|protected_pool|configured)|uploading video proxy|using bounded inline video proxy|waiting for video processing|inline transfer failed; switching to uploaded file reference|long request timed out; recovering with shorter video sections|retrying temporary media transport failure|temporary [A-Za-z]+; retrying same video \([2-3]/3\)|requesting analysis \(attempt [1-3]/3\))',line)][-6:]+failure_diagnostics,
        can_cancel=raw in ('queued','processing') and not job.get('cancel_requested'))


def category_presentation(folder):
    """Allowlisted metadata only, never raw classifier text or source dialogue."""
    record=read_json(folder/'category-result.json',{})
    try:
        import category_intelligence as ci
        chosen=record['selection'];cat,sub=ci.resolve(chosen['primary_category'],chosen['subcategory'])
        detection=record.get('detection') or {}
        return dict(primary_category=cat,subcategory=sub,source=chosen.get('source') if chosen.get('source') in ('automatic','manual','conservative_fallback') else 'unavailable',
            classification_method=detection.get('classification_method') if detection.get('classification_method') in ('text','frames','video','local','manual') else 'unavailable',
            review_required=detection.get('review_required') is True,active_editing_profile=ci.engine_id(cat,sub),
            confidence_kind='model_estimated_not_calibrated')
    except (KeyError,ValueError,TypeError):return None


def review(engine, identity):
    folder=folder_for(engine,identity); job=engine.jobs[identity]; meta=metadata(folder)
    actual={c.get('clip_index',i):c for i,c in enumerate((job.get('result') or {}).get('clips',[])) if isinstance(c,dict)}
    candidates={i:c for i,c in enumerate(meta.get('shorts',[])) if isinstance(c,dict)}
    candidates.update({i:c for i,c in actual.items() if isinstance(i,int) and i>=0})
    rows=[]
    for index,c in sorted(candidates.items()):
        path=delivered(engine,identity,c) if index in actual else None
        report=c.get('ranking_report') if isinstance(c.get('ranking_report'),dict) else {}
        score=number(report.get('overall',c.get('selection_score')),None)
        if c.get('ranking_stale') or score is not None and not 0<=score<=100: score=None
        reasons=report.get('reasons') or []
        if isinstance(reasons,dict): reasons=list(reasons.values())
        if not isinstance(reasons,list): reasons=[]
        tags=c.get('tags') or []
        if not isinstance(tags,list): tags=[]
        start=number(c.get('start')); end=max(start,number(c.get('end')))
        from export_quality import read_report
        quality=(read_report(str(path)) or {}) if path else {}
        measured=quality.get('measurements') or {}
        saved=read_json(folder/f'editor_project_{index}.json',{})
        edits=saved.get('edits',{}) if isinstance(saved,dict) else {}
        style=edits.get('style') or {}
        options=meta.get('pipeline_options') or {}
        metrics=report.get('metrics') if isinstance(report.get('metrics'),dict) else {}
        hook=c.get('hook_text') or c.get('viral_hook_text')
        assembly=c.get('assembly_report')
        stored=meta.get('shorts',[])
        if not assembly and isinstance(stored,list) and index<len(stored) and isinstance(stored[index],dict):
            assembly=stored[index].get('assembly_report')
        assembly_reason=''
        if isinstance(assembly,dict):
            removed=[o for o in assembly.get('operations',[]) if isinstance(o,dict) and o.get('type')=='remove']
            if removed:
                seconds=sum(max(0,number(o.get('source_end'))-number(o.get('source_start'))) for o in removed)
                labels={'opening_silence':'opening silence','irrelevant_pause':'long pauses','trailing_silence':'trailing silence',
                    'duplicate_explanation':'repeated explanations','off_topic':'off-topic material','redundant_visual':'redundant footage',
                    'empty':'empty footage','redundant_attempt':'redundant attempts'}
                reasons=', '.join(dict.fromkeys(labels[o['reason']] for o in removed if o.get('reason') in labels)) or 'optional material'
                assembly_reason=f'Smart Split kept {len(assembly.get("segments",[]))} source sections and removed {seconds:.1f}s ({reasons}); source order preserved.'
        for field in ('auto_hook','hook'):
            if not hook and isinstance(c.get(field),dict): hook=c[field].get('text')
        rows.append(dict(index=index,title=text(c.get('title') or c.get('video_title_for_youtube_short')) or f'Clip {index+1}',
            start=start,end=end,duration=number(measured.get('duration'),end-start),score=score,
            explanation=' · '.join(filter(None,[text(c.get('reason') or c.get('explanation') or report.get('summary')) or ' · '.join(filter(None,(text(r,200) for r in reasons[:4]))),assembly_reason])),
            tags=list(dict.fromkeys(filter(None,(text(t,50) for t in tags[:12])))),
            hook=text(hook),metrics={text(k,60):number(v,None) for k,v in metrics.items() if isinstance(v,(int,float))},
            status='ready' if path else ('unavailable' if index in actual else 'not_rendered'),
            video_url=c.get('video_url','') if path else '',size=path.stat().st_size if path else None,
            resolution=f"{int(number(measured.get('width')))} × {int(number(measured.get('height')))}" if measured.get('width') and measured.get('height') else 'Not recorded',
            format=path.suffix.lstrip('.').upper() if path else 'Source segment',
            caption_preset=('Disabled' if style.get('enabled') is False else text(style.get('preset') or c.get('caption_preset') or options.get('caption_preset')) or 'Saved timeline'),
            framing=text((edits.get('crop') or {}).get('mode') or c.get('framing') or options.get('framing_preset')) or 'Saved timeline',
            audio=('Normalized' if (edits.get('audio') or {}).get('normalize') else text(c.get('audio_preset') or options.get('audio_preset')) or 'Saved timeline')))
    state=read_review_state(folder)
    return dict(job_id=identity,state=job.get('status'),clips=rows,preferences=state,
        source_title=text(meta.get('title') or meta.get('video_title')) or 'Imported video',progress=progress(engine,identity))


def read_review_state(folder):
    path=folder/'desktop-review.json'
    if not path.exists(): return dict(version=1,revision=0,selected=[],active=None,sort='Score',tag='All tags',history=[])
    state=read_json(path,None)
    if not isinstance(state,dict) or type(state.get('revision')) is not int or state['revision']<0 or not isinstance(state.get('selected'),list) or not isinstance(state.get('history'),list):
        raise HTTPException(409,'Saved review preferences are damaged. Preserve and repair the saved review document before saving changes.')
    return state


class ReviewState(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    selected:list[int]=Field(default_factory=list,max_length=2000)
    active:int|None=Field(default=None,ge=0)
    sort:str=Field(default='Score',pattern='^(Score|Shortest|Longest|Source position)$')
    tag:str=Field(default='All tags',max_length=50)
    history:list[dict]=Field(default_factory=list,max_length=500)


def register(engine):
    lock=asyncio.Lock()
    thumbs=asyncio.Semaphore(1)
    @engine.app.get('/api/desktop/jobs/{job_id}/progress')
    async def job_progress(job_id:str): return progress(engine,job_id)
    @engine.app.get('/api/desktop/jobs/{job_id}/review')
    async def job_review(job_id:str): return await asyncio.to_thread(review,engine,job_id)
    @engine.app.put('/api/desktop/jobs/{job_id}/review')
    async def save_review(job_id:str, req:ReviewState):
        async with lock:
            folder=folder_for(engine,job_id); path=folder/'desktop-review.json'
            old=read_review_state(folder)
            if req.revision!=old.get('revision'): raise HTTPException(409,'Review changed. Reload before saving selection.')
            valid={r['index'] for r in review(engine,job_id)['clips']}
            if req.active is not None and req.active not in valid: raise HTTPException(400,'Unknown focused clip')
            if any(i not in valid for i in req.selected): raise HTTPException(400,'Unknown clip selection')
            history=[]
            for item in req.history:
                if item.get('index') not in valid or item.get('status') not in ('completed','failed'): raise HTTPException(400,'Invalid export history')
                history.append(dict(index=item['index'],status=item['status'],name=text(item.get('name'),200),at=text(item.get('at'),60)))
            data=dict(version=1,revision=req.revision+1,selected=list(dict.fromkeys(req.selected)),active=req.active,sort=req.sort,tag=text(req.tag,50),history=history)
            from story_director import atomic_json
            await asyncio.to_thread(atomic_json,path,data)
            return data
    @engine.app.get('/api/desktop/jobs/{job_id}/clips/{clip_index}/thumbnail')
    async def clip_thumbnail(job_id:str,clip_index:int):
        folder_for(engine,job_id)
        clips=(engine.jobs[job_id].get('result') or {}).get('clips',[])
        clip=next((c for i,c in enumerate(clips) if c.get('clip_index',i)==clip_index),{})
        path=delivered(engine,job_id,clip)
        if not path: raise HTTPException(404,'Rendered thumbnail is unavailable')
        async with thumbs: return {'path':await asyncio.to_thread(thumbnail,path)}
