"""Additive routes on the existing secured local backend, no second server."""
import asyncio
import json
from pathlib import Path
import threading
import uuid
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from learning.database import Store
from learning import service,datasets,models


class Feedback(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event:str=Field(min_length=8,max_length=128)
    candidate:str
    action:str
    before:dict=Field(default_factory=dict)
    after:dict=Field(default_factory=dict)
    rating:float|None=None


class Privacy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    collect:bool=True
    retrieval:bool=True
    inference:bool=False
    retention_days:int=Field(default=365,ge=1,le=3650)
    upload:bool=False


class Training(BaseModel):
    model_config=ConfigDict(extra='forbid')
    epochs:int=Field(default=100,ge=1,le=500)
    task:str='effects'

class ClipFeedback(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:str
    rating:float|None=None
    start:float|None=None
    end:float|None=None
    alternative:str|None=None
    category:str|None=None
    subcategory:str='auto'
    preset:str|None=None
    negative_reason:str|None=None


def status(store):
    from learning import highlight_ranking
    dataset=datasets.build(store,persist=False)
    registry=[r for r in store.rows('model_registry') if r['data'].get('task','effects')=='effects']
    active=next((r['id'][:12] for r in reversed(registry) if r['status']=='active'),'None · collection only')
    return dict(database='healthy' if store.integrity() else 'unhealthy',schema=1,feature_schema=1,
        reviewed_examples=len(dataset['rows']),learning_data='reviewed' if dataset['rows'] else 'No reviewed examples',
        training=models.readiness(dataset),active_model=active,last_evaluation=store.rows('model_evaluations')[-1:],
        privacy=store.preferences(),highlight_ranking=highlight_ranking.status(store),gemini='Direct Gemini · existing key pool; learning makes no provider requests')


def register(host):
    running={'task':None,'cancel':None,'result':None}
    def store():return Store()
    async def clip_context(job_id,index,request):
        from fastapi import Request
        job,meta,data,clip,filename=await host._quality_context(job_id,index,request)
        directory=Path(meta).parent;name=clip.get('edit_decision_file')
        if not isinstance(name,str) or Path(name).name!=name:raise HTTPException(409,'Retained scene plan missing')
        import editing_director
        try:plan=editing_director.EditPlan.model_validate(json.loads((directory/name).read_text(encoding='utf-8'))).model_dump(mode='json')
        except (ValueError,OSError):raise HTTPException(409,'Retained scene plan unavailable')
        # Use current persisted timeline overrides when present; never alter it.
        project=directory/f'editor_project_{index}.json'
        if project.is_file():
            try:
                edits=json.loads(project.read_text(encoding='utf-8'))['edits']
                if edits.get('auto_edit'):
                    import auto_edit
                    plan['auto_edit']=auto_edit.normalize(edits['auto_edit'],sum(s['end']-s['start'] for s in edits['segments']))
            except (ValueError,KeyError,TypeError):raise HTTPException(409,'Refresh the saved editor project')
        return plan

    @host.app.get('/api/desktop/learning')
    async def get_status():
        try:return await asyncio.to_thread(lambda:status(store()))
        except Exception:return dict(database='unavailable',reviewed_examples=0,active_model='None',error='Local learning unavailable; editing remains enabled')

    @host.app.put('/api/desktop/learning/privacy')
    async def privacy(req:Privacy):
        try:await asyncio.to_thread(lambda:store().privacy(req.model_dump()));return {'saved':True}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @host.app.delete('/api/desktop/learning')
    @host.app.post('/api/desktop/learning/delete')
    async def delete():
        if running['task'] and not running['task'].done():raise HTTPException(409,'Cancel training before deleting learning history')
        await asyncio.to_thread(lambda:store().delete_history());return {'deleted':True}

    from fastapi import Request
    @host.app.get('/api/clip/{job_id}/{clip_index}/editor/learning')
    async def editor_status(job_id:str,clip_index:int,request:Request):
        plan=await clip_context(job_id,clip_index,request)
        def read():
            db=store();ids=service.observe(plan,plan.get('auto_edit') or {},db)
            candidates=[]
            for item in ids:
                row=db.rows('effect_candidates','id=?',(item['id'],))[0]
                candidates.append({**item,'type':row['data']['effect']['type'],
                    'examples':service.retrieve(db,row['data']['features'])})
            return dict(candidates=candidates,**status(db))
        return await asyncio.to_thread(read)

    @host.app.post('/api/clip/{job_id}/{clip_index}/editor/learning')
    async def feedback(job_id:str,clip_index:int,req:Feedback,request:Request):
        plan=await clip_context(job_id,clip_index,request)
        def write():
            db=store();ids=service.observe(plan,plan.get('auto_edit') or {},db)
            if req.candidate not in {r['id'] for r in ids}:
                # A deliberately snapshotted candidate may precede an autosave
                # revision; accept only if it belongs to this same source/project.
                candidates=db.rows('effect_candidates','id=?',(req.candidate,))
                scenes=db.rows('scene_features')
                candidate_scene=next((s for s in scenes if candidates and s['id']==candidates[0]['scene_id']),None)
                current_projects={s['project_ref'] for s in scenes if s['id'] in {r['scene'] for r in ids}}
                if not candidate_scene or candidate_scene['project_ref'] not in current_projects:raise ValueError('Candidate belongs to another project')
            return service.feedback(db,req.event,req.candidate,req.action,req.before,req.after,req.rating)
        try:return await asyncio.to_thread(write)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @host.app.post('/api/desktop/learning/train')
    async def train(req:Training):
        if req.task not in ('effects','highlight-ranking'):raise HTTPException(400,'Unknown learning task')
        if running['task'] and not running['task'].done():raise HTTPException(409,'Training already running')
        cancel=threading.Event();running['cancel']=cancel
        running['result']=None
        async def run():
            try:running['result']=await asyncio.to_thread(lambda:models.train(store(),datasets.build(store(),task=req.task),{'epochs':req.epochs},cancel))
            except Exception:running['result']={'status':'failed','error':'Local training failed; production model unchanged'}
        running['task']=asyncio.create_task(run());return {'status':'queued'}

    @host.app.get('/api/desktop/learning/train')
    async def training():return dict(status='running' if running['task'] and not running['task'].done() else 'idle',result=running['result'])

    @host.app.delete('/api/desktop/learning/train')
    @host.app.post('/api/desktop/learning/train/cancel')
    async def cancel():
        if running['cancel']:running['cancel'].set()
        return {'status':'cancelling'}

    @host.app.post('/api/desktop/learning/models/{identity}/{state}')
    async def transition(identity:str,state:str):
        try:return await asyncio.to_thread(lambda:models.transition(store(),identity,state))
        except (ValueError,OSError,KeyError):raise HTTPException(400,'Model transition rejected: check review, compatibility and evaluation gates')

    async def highlight_context(job_id,index,request):
        _job,_meta,data,clip,_file=await host._quality_context(job_id,index,request)
        identity=clip.get('learning_candidate_id')
        if not isinstance(identity,str):raise HTTPException(409,'This older clip has no immutable ranking snapshot. Existing editing remains available.')
        db=store();rows=db.rows('effect_candidates','id=?',(identity,))
        if not rows or rows[0]['data'].get('task')!='highlight-ranking':raise HTTPException(409,'Ranking snapshot unavailable; collection may be disabled or history deleted')
        return db,identity,rows[0]

    @host.app.get('/api/clip/{job_id}/{clip_index}/learning-ranking')
    async def clip_ranking_status(job_id:str,clip_index:int,request:Request):
        db,identity,row=await highlight_context(job_id,clip_index,request)
        snapshot=row['data']
        alternatives=[dict(id=r['id'],start=r['data']['start'],end=r['data']['end']) for r in db.rows('effect_candidates') if r['data'].get('task')=='highlight-ranking' and r['data'].get('query')==snapshot['query'] and r['id']!=identity]
        return dict(candidate=identity,start=snapshot['start'],end=snapshot['end'],features=snapshot['features'],alternatives=alternatives,task='highlight-ranking')

    @host.app.post('/api/clip/{job_id}/{clip_index}/learning-ranking')
    async def clip_ranking_feedback(job_id:str,clip_index:int,req:ClipFeedback,request:Request):
        db,identity,_row=await highlight_context(job_id,clip_index,request)
        from learning.highlight_ranking import feedback as clip_feedback
        try:return await asyncio.to_thread(clip_feedback,db,identity,**req.model_dump())
        except ValueError as exc:raise HTTPException(400,str(exc))
