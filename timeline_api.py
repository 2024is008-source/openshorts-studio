"""Saved editor projects integrated with the existing app's ownership and exports."""
import asyncio
from contextlib import asynccontextmanager
import copy
import json
import math
import os
import subprocess
import re
import shutil
import time
from pathlib import Path
import threading
import render_runtime
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import export_quality as quality
import recut
import timeline_project as model
import timeline_render as renderer
from story_director import atomic_json
from desktop.editor_state import publish as publish_project

_active = {}
_workers = asyncio.Semaphore(2)


class Save(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    edits: dict
    ui: dict | None = None


class Run(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    mode: str = 'preview'
    output: dict | None = None


class RegenerateEffects(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision: int=Field(ge=0)
    settings: dict


class CustomTemplate(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    template: dict


class BatchTemplate(CustomTemplate):
    clips: dict[str,int] = Field(min_length=1,max_length=12)


def router(host):
    def retained_plan(directory,clip):
        import editing_director
        name=clip.get('edit_decision_file')
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.edit.json'):return None
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()):return None
        try:return editing_director.EditPlan.model_validate(json.loads(path.read_text(encoding='utf-8'))).model_dump(mode='json')
        except (OSError,ValueError):return None
    @asynccontextmanager
    async def lifespan(_app):
        try: yield
        finally:
            tasks=[]
            for entry in list(_active.values()):
                entry['cancel'].set();tasks.append(entry['task'])
            if tasks:
                _,pending=await asyncio.wait(tasks,timeout=5)
                for task in pending:task.cancel()
                await asyncio.gather(*pending,return_exceptions=True)
    routes=APIRouter(prefix='/api/clip/{job_id}/{clip_index}/editor',lifespan=lifespan)

    async def context(job_id, clip_index, request):
        if os.getenv('EDITOR_TIMELINE_ENABLED','1')=='0':
            raise HTTPException(404,'Saved timeline editor is disabled.')
        job,meta,data,clip,filename=await host._quality_context(job_id,clip_index,request)
        directory=Path(meta).parent
        path=directory/f'editor_project_{clip_index}.json'
        try:
            segments,canonical_range=host._clip_recipe_parts(clip)
            for value in (canonical_range['start'],canonical_range['end']):
                if not math.isfinite(float(value)):raise ValueError('Invalid canonical range.')
            if canonical_range['start']<0 or canonical_range['end']<=canonical_range['start']:
                raise ValueError('Invalid canonical range.')
        except (ValueError,TypeError,KeyError,AttributeError):
            raise HTTPException(409,'The saved clip recipe is malformed; restore its metadata before editing.')
        # Derive the clean canonical basename exactly as the existing recut route.
        canonical=host._safe_under(str(directory),Path(meta).name.replace('_metadata.json','')+f'_clip_{clip_index+1}.mp4')
        if not canonical or not Path(canonical).is_file() or (clip.get('recipe') or {}).get('source_montage'):
            canonical=None
        canonical_segments=[canonical_range]
        editor_clean=clip.get('editor_clean_file')
        if not isinstance(editor_clean,str) or not filename.endswith(editor_clean):editor_clean=None
        current_clean=editor_clean or re.sub(r'^subtitled_\d+_','',filename)
        candidate=host._safe_under(str(directory),current_clean) if isinstance(current_clean,str) and Path(current_clean).name==current_clean else None
        if candidate and Path(candidate).is_file() and (editor_clean or Path(candidate).name.startswith('recut_')):
            canonical=candidate;canonical_segments=segments
        source=host._locate_source(job_id)
        if source:
            resolved=Path(source).resolve()
            allowed=(resolved.is_relative_to(directory.resolve()) or
                     (resolved.is_relative_to(Path(host.UPLOAD_DIR).resolve()) and resolved.name.startswith(job_id+'_')))
            if not allowed or not resolved.is_file(): raise HTTPException(400,'Invalid retained source path.')
            source=str(resolved)
        duration=await asyncio.to_thread(host._source_duration_seconds,source) if source else None
        try:
            duration=duration or max([s['end'] for s in segments]+[canonical_range['end']])
            if not math.isfinite(duration):raise ValueError('Invalid source duration.')
            segments=recut.normalize_segments(segments,duration)
        except (ValueError,TypeError,KeyError):raise HTTPException(409,'Invalid saved clip segment boundaries.')
        rows=model.captions(data.get('transcript') or {})
        stamp=model.digest([model.origin(clip),model.identity(source),model.identity(canonical),
                            model.digest(data.get('transcript') or {})])
        try:initial=model.initial(clip,segments,Path(source).name if source else None)
        except (ValueError,TypeError):raise HTTPException(409,'Saved clip template is malformed; restore its configuration before editing.')
        initial['origin']=stamp
        plan=retained_plan(directory,clip)
        if plan and plan.get('auto_edit'):
            import auto_edit
            mapped=auto_edit.remap_plan(plan,segments)
            initial['edits']['auto_edit']=auto_edit.generate(mapped,auto_edit.observations(plan),plan['auto_edit'])
        try:
            saved=json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(saved,dict) or saved.get('version')!=model.VERSION
                    or type(saved.get('revision')) is not int or saved['revision']<0
                    or saved.get('status') not in model.ACTIVE|{'draft','preview_ready','completed','cancelled','failed','interrupted'}):
                raise ValueError('Unsupported saved project.')
            saved['edits']=model.normalize(saved.get('edits'),duration,rows)
            if 'ui' in saved:saved['ui']=model.workspace_state(saved['ui'])
        except FileNotFoundError: saved=initial
        except (ValueError,TypeError,KeyError,AttributeError,recut.RecutError):
            raise HTTPException(409,'Saved project is malformed; restore its backup or remove this project draft locally.')
        if saved.get('status') in model.ACTIVE and (job_id,clip_index) not in _active:
            saved.update(status='interrupted',error='Processing was interrupted. Valid cached stages can be reused.',run_id=None)
            atomic_json(path,saved)
        return dict(job=job,meta=meta,data=data,clip=clip,filename=filename,directory=directory,path=path,
                    project=saved,initial=initial,origin=stamp,source=source,canonical=canonical,
                    canonical_range=canonical_range,canonical_segments=canonical_segments,duration=duration,rows=rows)

    def response(ctx):
        return dict(project=ctx['project'],captions=ctx['rows'],source_available=bool(ctx['source']),
                    stale=ctx['project']['origin']!=ctx['origin'],source_duration=ctx['duration'])

    def editable(ctx, revision):
        if ctx['project']['revision']!=revision: raise HTTPException(409,'Draft changed in another editor. Reopen it before saving.')
        if ctx['project'].get('status') in model.ACTIVE: raise HTTPException(409,'Cancel or finish the active editor job first.')
        if ctx['job'].get('status') in ('processing','queued'): raise HTTPException(409,'Wait for clip generation to finish.')

    @routes.get('')
    async def get(job_id: str,clip_index: int,request: Request):
        return response(await context(job_id,clip_index,request))

    @routes.post('/auto-edit')
    async def regenerate_effects(job_id: str,clip_index: int,req: RegenerateEffects,request: Request):
        import auto_edit
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            ctx=await context(job_id,clip_index,request);editable(ctx,req.revision)
            try:
                settings=auto_edit.normalize(req.settings,recut.total_duration(ctx['project']['edits']['segments']))
                plan=retained_plan(ctx['directory'],ctx['clip'])
                if plan:
                    # Cached cues live with scenes, so regeneration does not call Gemini.
                    mapped=auto_edit.remap_plan(plan,ctx['project']['edits']['segments'])
                    value=auto_edit.generate(mapped,auto_edit.observations(plan),settings)
                else:
                    value=settings
                    value['effects']=[e for e in value['effects'] if e['origin']=='manual']
                    value['skipped']=[dict(type='analysis',reason='No retained visual scene plan. Keep the existing composition; generate new clips to collect scene evidence.')]
                return dict(auto_edit=value,provider_calls=0,transcription_runs=0)
            except (ValueError,TypeError,KeyError) as exc:raise HTTPException(400,str(exc))

    @routes.get('/templates')
    async def templates(job_id: str,clip_index: int,request: Request):
        import video_templates
        ctx=await context(job_id,clip_index,request)
        try:return dict(templates=video_templates.catalog(ctx['directory']))
        except (OSError,ValueError):raise HTTPException(409,'The saved template library is invalid; restore its JSON backup.')

    @routes.post('/templates')
    async def save_template(job_id: str,clip_index: int,req: CustomTemplate,request: Request):
        import video_templates
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            ctx=await context(job_id,clip_index,request)
            try:
                value=video_templates.normalize(req.template)
                library=video_templates.catalog(ctx['directory'])
                builtin={t['id'] for t in video_templates.catalog()}
                custom=[t for t in library if t['id'] not in builtin]
                if len(custom)>=50:raise ValueError('At most 50 custom templates per project')
                value['id']='custom-'+uuid.uuid4().hex[:16]
                custom.append(value)
                atomic_json(ctx['directory']/'custom_video_templates.json',custom)
                return dict(template=value,templates=video_templates.catalog(ctx['directory']))
            except (OSError,ValueError) as exc:raise HTTPException(400,str(exc))

    @routes.post('/template-batch')
    async def template_batch(job_id: str,clip_index: int,req: BatchTemplate,request: Request):
        """Preflight all owned draft revisions before applying; renders use /run."""
        import video_templates
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            await context(job_id,clip_index,request)
            try: template=video_templates.normalize(req.template)
            except ValueError as exc:raise HTTPException(400,str(exc))
            contexts=[]
            for key,revision in req.clips.items():
                if not key.isdigit() or str(int(key))!=key:raise HTTPException(400,'Clip indices must be canonical nonnegative integers')
                ctx=await context(job_id,int(key),request);editable(ctx,revision)
                if ctx['project']['origin']!=ctx['origin']:raise HTTPException(409,'A selected draft is stale; reset it before batch application')
                edits=copy.deepcopy(ctx['project']['edits']);edits['template']=template
                mapped=model.transcript(ctx['rows'],edits)
                edits['template_content']=video_templates.initial_content(template,mapped,recut.total_duration(edits['segments']))
                try:edits=model.normalize(edits,ctx['duration'],ctx['rows'])
                except ValueError as exc:raise HTTPException(400,str(exc))
                contexts.append((key,ctx,edits))
            backups={ctx['path']:ctx['path'].read_bytes() if ctx['path'].exists() else None for _,ctx,_ in contexts}
            try:
                for _,ctx,edits in contexts:
                    ctx['project'].update(edits=edits,revision=ctx['project']['revision']+1,status='draft',progress=0,error=None)
                    publish_project(ctx['path'],ctx['project'])
            except OSError:
                for path,old in backups.items():
                    if old is None:path.unlink(missing_ok=True)
                    else:atomic_json(path,json.loads(old))
                raise HTTPException(503,'Batch drafts could not be saved; retry after checking disk access')
            return dict(clips={key:ctx['project'] for key,ctx,_ in contexts})

    async def directed(job_id,clip_index,request):
        import editing_director
        job,meta,data,clip,filename=await host._quality_context(job_id,clip_index,request)
        name=clip.get('edit_decision_file')
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.mp4.edit.json'):
            raise HTTPException(404,'No directed edit plan was saved for this clip.')
        path=host._safe_under(str(Path(meta).parent),name)
        if not path or not Path(path).is_file():raise HTTPException(404,'Saved edit plan is unavailable.')
        if filename!=clip.get('director_delivery_file'):
            raise HTTPException(409,'The clip was edited after direction; this plan is stale.')
        try:plan=editing_director.load(path[:-10])
        except (ValueError,OSError):raise HTTPException(409,'The stored edit plan is invalid; regenerate this clip.')
        return job,Path(meta).parent,clip,plan

    @routes.get('/director')
    async def director_plan(job_id: str,clip_index: int,request: Request):
        _,_,_,plan=await directed(job_id,clip_index,request)
        return dict(plan=plan,preview_available=bool(host._locate_source(job_id)))

    @routes.post('/director-preview')
    async def director_preview(job_id: str,clip_index: int,request: Request):
        """Replay the saved final decisions; never run AI or detection a second time."""
        import editing_director
        import reframe_v2
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            job,directory,clip,plan=await directed(job_id,clip_index,request)
            await host.require_managed_entitlement(request)
            if plan['duration']>180:raise HTTPException(400,'Director preview supports clips up to 180 seconds.')
            source=host._locate_source(job_id)
            if not source:raise HTTPException(409,'Retained source is required to replay the generated edit plan.')
            resolved=Path(source).resolve()
            if not (resolved.is_relative_to(directory.resolve()) or
                    resolved.is_relative_to(Path(host.UPLOAD_DIR).resolve()) and resolved.name.startswith(job_id+'_')):
                raise HTTPException(400,'Invalid source location.')
            if resolved.name!=plan['source_ref'] or editing_director.identity(resolved)!=plan['source_identity']:
                raise HTTPException(409,'Retained source changed; regenerate the clip plan.')
            token=model.digest([plan,bool(job.get('watermark'))]);target=directory/f'director_preview_{token}.mp4'
            width,height=plan['output_width'],plan['output_height'];scale=min(1,360/width,640/height)
            size=(max(2,int(width*scale)//2*2),max(2,int(height*scale)//2*2))
            def create():
                if renderer.cached(target) and (quality.read_report(target) or {}).get('accepted'):return
                import tempfile
                with tempfile.TemporaryDirectory(prefix='temp_director_',dir=directory) as work:
                    cut=Path(work)/'source.mp4';clean=Path(work)/'clean.mp4';final=Path(work)/'final.mp4'
                    deadline=time.monotonic()+300;cancel=threading.Event()
                    def execute(command):return renderer.run(command,cancel,min(120,max(.1,deadline-time.monotonic())))
                    recut.run_cut_concat(str(resolved),[dict(start=s['source_start'],end=s['source_end']) for s in plan['segments']],
                                         str(cut),work,runner=execute,video_args=reframe_v2.director_encoder(plan['width'],plan['height']),
                                         continuous_audio=plan.get('audio',{}).get('continuous_source_audio',False))
                    reframe_v2.render_decisions(str(cut),str(clean),plan,size=size,runner=execute)
                    if job.get('watermark'):
                        import main
                        if not main.apply_watermark(str(clean),runner=execute):raise RuntimeError('Watermark unavailable.')
                    editing_director.render_layers(str(clean),str(final),plan,size=size,runner=execute)
                    expected=quality.expectations(quality.probe(cut),duration=plan['duration'],size=size)
                    import audio_mastering
                    report=quality.enforce(final,f'clip_{clip_index+1}',expected,master_audio=True,
                        audio_config=audio_mastering.export_settings(directory/'preview.mp4'))
                    os.replace(final,target);report.update(file=target.name,fingerprint=quality.fingerprint(target))
                    quality.save_report(target,report);renderer.receipt(target)
            try:await host._run_quality(create)
            except (OSError,ValueError,RuntimeError,TimeoutError,subprocess.SubprocessError):
                raise HTTPException(503,'Director preview failed. Check source media, FFmpeg and the stored plan.')
            return dict(new_video_url=f'/videos/{job_id}/{target.name}',mode='preview',
                        duration=plan['duration'],quality_report=quality.read_report(target),
                        decision_version=plan['version'],decision_digest=token)

    @routes.post('/duplicate')
    async def duplicate(job_id: str,clip_index: int,req: Run,request: Request):
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            ctx=await context(job_id,clip_index,request);editable(ctx,req.revision)
            if ctx['project']['origin']!=ctx['origin']: raise HTTPException(409,'Reload the changed source before duplicating.')
            if not ctx['source'] and not ctx['canonical']: raise HTTPException(409,'The retained source or clean clip is required to duplicate this timeline.')
            data=copy.deepcopy(ctx['data']);index=len(data['shorts'])
            if index>=1000: raise HTTPException(409,'This project has reached its clip limit.')
            clip=copy.deepcopy(ctx['clip']);clip['clip_index']=index
            clip['title']=str(clip.get('title') or clip.get('video_title_for_youtube_short') or f'Clip {clip_index+1}')[:220]+' (copy)'
            if not ctx['source']:
                clean=Path(ctx['canonical']).name
                if not ctx['filename'].endswith(clean): raise HTTPException(409,'The retained source is required to duplicate this delivered media layout.')
                clip['editor_clean_file']=clean
            data['shorts'].append(clip)
            saved=copy.deepcopy(ctx['project']);saved.update(revision=0,status='draft',progress=0,run_id=None,result=None,error=None)
            # Both configurations reference the same retained source/delivered media.
            # The canonical artifact can differ for the new index, so recompute its origin lazily on first open.
            clone_path=ctx['directory']/f'editor_project_{index}.json'
            if clone_path.exists(): raise HTTPException(409,'A draft already exists at the new clip index.')
            atomic_json(ctx['meta'],data)
            try:
                clone=await context(job_id,index,request)
                saved['origin']=clone['origin']
                atomic_json(clone_path,saved)
            except Exception:
                atomic_json(ctx['meta'],ctx['data']);raise
            result=copy.deepcopy(ctx['job'].get('result') or {});result.setdefault('clips',[]).append(clip)
            ctx['job']['result']=result
            return dict(clip_index=index,title=clip['title'],revision=0)

    @routes.put('')
    async def save(job_id: str,clip_index: int,req: Save,request: Request):
        editable(await context(job_id,clip_index,request),req.revision)
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            ctx=await context(job_id,clip_index,request);saved=ctx['project']
            editable(ctx,req.revision)
            if saved['origin']!=ctx['origin']: raise HTTPException(409,'Source or clip changed. Reset the saved draft to the latest clip.')
            try: edits=model.normalize(req.edits,ctx['duration'],ctx['rows'])
            except ValueError as exc: raise HTTPException(400,str(exc))
            if not ctx['source'] and (edits['crop']['mode']!='preserve' or not ctx['canonical'] or not all(
                    model.mapped_bounds(s,ctx['canonical_segments']) for s in edits['segments'])):
                raise HTTPException(409,'The retained source is required for these edits.')
            if req.ui is not None:
                try:saved['ui']=model.workspace_state(req.ui)
                except ValueError as exc:raise HTTPException(400,str(exc))
            saved.update(edits=edits,revision=saved['revision']+1,status='draft',error=None,progress=0)
            publish_project(ctx['path'],saved)
            return response(ctx)

    @routes.post('/reset')
    async def reset(job_id: str,clip_index: int,req: Run,request: Request):
        editable(await context(job_id,clip_index,request),req.revision)
        async with host._rerender_locks.setdefault(job_id,asyncio.Lock()):
            ctx=await context(job_id,clip_index,request);editable(ctx,req.revision)
            ctx['initial']['revision']=ctx['project']['revision']+1
            publish_project(ctx['path'],ctx['initial']);ctx['project']=ctx['initial']
            return response(ctx)

    @routes.post('/cancel')
    async def cancel(job_id: str,clip_index: int,request: Request):
        ctx=await context(job_id,clip_index,request)
        active=_active.get((job_id,clip_index))
        if active: active['cancel'].set()
        return dict(status='cancelling' if active else ctx['project']['status'])

    @routes.post('/features')
    async def features(job_id: str,clip_index: int,req: Run,request: Request):
        await host.require_managed_entitlement(request)
        ctx=await context(job_id,clip_index,request)
        if req.revision!=ctx['project']['revision'] or ctx['project']['origin']!=ctx['origin']:
            raise HTTPException(409,'Save or reload the latest draft first.')
        if ctx['project'].get('status') in model.ACTIVE: raise HTTPException(409,'Wait for the editor render to finish.')
        try:
            return await host._run_quality(lambda:renderer.features(segments=ctx['project']['edits']['segments'],
                source=ctx['source'],canonical=ctx['canonical'],canonical_range=ctx['canonical_range'],
                canonical_segments=ctx['canonical_segments'],directory=ctx['directory'],cancel=threading.Event()))
        except (OSError,ValueError,TimeoutError,RuntimeError):
            raise HTTPException(503,'Waveform/scene sampling is unavailable. Video editing remains available.')

    @routes.post('/run')
    async def start(job_id: str,clip_index: int,req: Run,request: Request):
        await host.require_managed_entitlement(request)
        if req.mode not in ('preview','final'): raise HTTPException(400,'Render mode must be preview or final.')
        editable(await context(job_id,clip_index,request),req.revision)
        lock=host._rerender_locks.setdefault(job_id,asyncio.Lock())
        async with lock:
            ctx=await context(job_id,clip_index,request);saved=ctx['project'];editable(ctx,req.revision)
            if saved['origin']!=ctx['origin']: raise HTTPException(409,'Source or clip changed. Reset the draft first.')
            try:
                info=await asyncio.to_thread(quality.probe,str(ctx['directory']/ctx['filename']))
                expected=quality.expectations(info,duration=recut.total_duration(saved['edits']['segments']))
            except (OSError,ValueError,subprocess.SubprocessError):
                raise HTTPException(503,'Cannot probe the current clip. Check FFprobe and the retained media.')
            try:output=model.export_options(req.output)
            except ValueError as exc:raise HTTPException(400,str(exc))
            if output.get('fps'):expected['fps']=output['fps']
            width,height=output.get('size') or (expected['width'],expected['height'])
            if req.mode=='preview':
                factor=min(1,360/width,640/height)
                width,height=max(2,int(width*factor)//2*2),max(2,int(height*factor)//2*2)
            if not width or not height or width>8192 or height>8192: raise HTTPException(400,'Invalid export size.')
            expected.update(width=width,height=height,aspect=width/height)
            cancel=threading.Event();key=(job_id,clip_index);run_id=uuid.uuid4().hex
            saved.update(status='queued',progress=0,run_id=run_id,error=None,quality_report=None,export_options=output)
            publish_project(ctx['path'],saved)
            reservation=None
            if req.mode=='final':
                try:
                    reservation=await host.reserve_managed_action(request,
                        max(1,math.ceil(expected['duration']/60)) if host.BILLING_ENABLED else 0,job_id,'rerender')
                except Exception:
                    saved.update(status='draft',run_id=None);publish_project(ctx['path'],saved);raise
            async def work():
                try:
                    async with _workers,lock:
                        fresh=await context(job_id,clip_index,request)
                        if fresh['origin']!=ctx['origin']: raise ValueError('Clip changed before rendering began. Reset the draft.')
                        renderer.check(cancel)
                        def progress(value,label):
                            renderer.check(cancel)
                            saved.update(status='rendering',progress=value,stage=label);publish_project(ctx['path'],saved)
                        watermark=None
                        if ctx['job'].get('watermark'):
                            def watermark(path,execute):
                                import main
                                if not main.apply_watermark(path,runner=execute): raise RuntimeError('Could not apply required watermark.')
                        path,cache=await asyncio.to_thread(renderer.render,edits=copy.deepcopy(saved['edits']),
                            rows=ctx['rows'],source=ctx['source'],canonical=ctx['canonical'],
                            canonical_range=ctx['canonical_range'],canonical_segments=ctx['canonical_segments'],
                            previous=ctx['clip'].get('editor_render') if ctx['canonical'] and
                                Path(ctx['canonical']).name==ctx['clip'].get('editor_clean_file') else None,
                            size=(width,height),fps=expected['fps'] or 30,
                            audio=expected['audio_expected'],directory=ctx['directory'],cancel=cancel,
                            progress=progress,watermark=watermark,
                            continuous_audio=bool((ctx['clip'].get('recipe') or {}).get('pacing_audio_continuity')),
                            **({'encoding':output} if output else {}))
                        renderer.check(cancel)
                        template=saved['edits'].get('template')
                        import video_templates
                        audio_edits=saved['edits'].get('audio')
                        if audio_edits:
                            if not expected['audio_expected']:raise ValueError('Timeline audio controls require source audio.')
                            path=await asyncio.to_thread(renderer.mix_audio,path,audio_edits,expected['duration'],ctx['directory'],cancel,progress)
                            if audio_edits['mute']:expected['speech_expected']=False
                        report=await host._validate_clip_export(job_id,clip_index,Path(path).name,
                            expected=expected,publish=False,master_audio=not bool(audio_edits),
                            **({'audio_config':video_templates.audio_settings(template)} if template else {}))
                        renderer.receipt(path)  # Mastering may atomically replace AAC bytes.
                        renderer.check(cancel)
                        result=dict(new_video_url=f'/videos/{job_id}/{Path(path).name}',duration=expected['duration'],
                            start=min(s['start'] for s in saved['edits']['segments']),
                            end=max(s['end'] for s in saved['edits']['segments']),
                            recipe=dict(v=1,segments=saved['edits']['segments'],canonical_range=ctx['canonical_range'],
                                        source_montage=bool((ctx['clip'].get('recipe') or {}).get('source_montage'))),
                            framing='auto',quality_report=report,cache=cache,mode=req.mode,revision=saved['revision'])
                        if (ctx['clip'].get('recipe') or {}).get('pacing_audio_continuity'):
                            result['recipe']['pacing_audio_continuity']=True
                        if req.mode=='final':
                            # Preserve clean/derived naming for later caption restyles and recovery.
                            token=f'{int(time.time())}_{uuid.uuid4().hex[:8]}'
                            clean_name=f'recut_{token}_{Path(ctx["meta"]).name.replace("_metadata.json","")}_clip_{clip_index+1}.mp4'
                            clean_cache=ctx['directory']/f'editor_clean_{cache["clean_key"]}.mp4'
                            clean_alias=ctx['directory']/clean_name
                            served_name=f'subtitled_{int(time.time())}_{clean_name}' if cache['captions_applied'] or cache.get('template_applied') or cache.get('effects_applied') or audio_edits else clean_name
                            served_alias=ctx['directory']/served_name
                            def link(src,dst):
                                if Path(src)==Path(dst):return
                                try:os.link(src,dst)
                                except OSError:shutil.copy2(src,dst)
                            link(clean_cache,clean_alias)
                            if served_alias!=clean_alias:link(path,served_alias)
                            else:
                                # With captions disabled, the clean assembly is the deliverable.
                                path=str(clean_alias)
                            import layout_ranges
                            ranges=layout_ranges.read(str(clean_cache))
                            for alias in {clean_alias,served_alias}:
                                layout_ranges.write(str(alias),[(r['start'],r['end'],r['layout']) for r in ranges])
                            report=copy.deepcopy(report)
                            report.update(file=served_name,fingerprint=quality.fingerprint(served_alias))
                            quality.save_report(served_alias,report)
                            result.update(new_video_url=f'/videos/{job_id}/{served_name}',quality_report=report)
                            # Re-read metadata under the same shared edit lock; preserve unrelated fields.
                            data=json.loads(Path(ctx['meta']).read_text(encoding='utf-8'));clip=data['shorts'][clip_index]
                            updates=dict(video_url=result['new_video_url'],recipe=result['recipe'],
                                video_template=copy.deepcopy(template),template_content=copy.deepcopy(saved['edits'].get('template_content')),
                                template_captions_enabled=saved['edits']['style']['enabled'],
                                start=min(s['start'] for s in saved['edits']['segments']),
                                end=max(s['end'] for s in saved['edits']['segments']),crop_overrides=None,
                                quality_required=True,quality_report=report,quality_expected=expected,
                                editor_revision=saved['revision'],editor_clean_file=clean_name,
                                editor_caption_overrides=copy.deepcopy(saved['edits']['caption_overrides']),
                                editor_caption_source_digest=model.digest(data.get('transcript') or {}),
                                editor_render=dict(segments=copy.deepcopy(saved['edits']['segments']),
                                    encoder_signature=render_runtime.encoder_signature(),
                                    crop=copy.deepcopy(saved['edits']['crop']),size=[width,height],
                                    fps=expected['fps'] or 30,audio=expected['audio_expected'],
                                    watermark=bool(ctx['job'].get('watermark')),
                                    segment_keys=cache['segment_keys'],source_identity=model.identity(ctx['source'])),
                                layout_ranges=ranges)
                            previous_crop=(clip.get('editor_render') or {}).get('crop',dict(mode='preserve',x=.5,y=.5))
                            if (host._clip_recipe_parts(clip)[0]!=saved['edits']['segments'] or previous_crop!=saved['edits']['crop']):
                                updates['ranking_stale']=True
                            clip.update(updates);atomic_json(ctx['meta'],data)
                            result.update(ranking_stale=clip.get('ranking_stale',False),layout_ranges=ranges)
                            if host._has_memory_clip(ctx['job'],clip_index):host._memory_clip(ctx['job'],clip_index).update(updates)
                            ctx['job'].setdefault('ready_files',{})[clip_index]=served_name
                            saved['origin']=model.digest([model.origin(clip),model.identity(ctx['source']),
                                model.identity(clean_alias),model.digest(data.get('transcript') or {})])
                            host._archive_clip_edit_bg(job_id,clip_index,served_name)
                            if reservation: await host._metering.commit_reservation(reservation)
                        saved.update(status='completed' if req.mode=='final' else 'preview_ready',progress=100,
                                     result=result,run_id=None,error=None)
                        publish_project(ctx['path'],saved)
                except (Exception,asyncio.CancelledError) as exc:
                    from desktop.render_diagnostics import record
                    diagnostic=record(ctx['directory'],exc,saved.get('stage',''),run_id)
                    requested=cancel.is_set();interrupted=isinstance(exc,asyncio.CancelledError)
                    cancel.set()
                    if reservation: await host._metering.release_reservation(reservation)
                    saved.update(status='interrupted' if interrupted else 'cancelled' if requested else 'failed',run_id=None,
                                 error='Editor processing interrupted; retry to reuse valid caches.' if interrupted else
                                 'Editor render cancelled.' if requested else
                                 (str(exc) if isinstance(exc,(ValueError,TimeoutError)) else
                                  'Editor processing failed. Check FFmpeg/source availability and retry.'))
                    if isinstance(exc,HTTPException) and isinstance(exc.detail,dict):
                        saved.update(quality_report=exc.detail,error='Export failed technical validation. Review the quality report and retry after correcting the timeline/source.')
                    saved['diagnostic']=diagnostic
                    publish_project(ctx['path'],saved)
                finally: _active.pop(key,None)
            task=asyncio.create_task(work())
            _active[key]=dict(cancel=cancel,task=task)
            return dict(project=saved)

    return routes
