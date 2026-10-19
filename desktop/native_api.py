"""WPF bootstrap and additive routes. Existing browser host remains available."""
import asyncio
import os
from pathlib import Path
from fastapi import HTTPException


def register(engine):
    from desktop.video_import import register as register_imports
    register_imports(engine)
    from desktop.home import register as register_home
    register_home(engine)
    from desktop.editor_assets import register as register_assets
    register_assets(engine)
    from desktop.cache import register as register_cache
    register_cache(engine)
    from desktop.generation_review import register as register_review
    register_review(engine)
    from learning.api import register as register_learning
    register_learning(engine)
    @engine.app.get('/api/desktop/contract')
    async def contract():
        from desktop.contract import describe
        return describe(engine)

    @engine.app.get('/api/desktop/source/{job_id}')
    async def source(job_id: str):
        if job_id not in engine.jobs:
            raise HTTPException(404, 'Project not found')
        source = engine._locate_source(job_id)
        if not source:
            raise HTTPException(404, 'Retained source is unavailable')
        path = Path(source).resolve()
        output = Path(engine.OUTPUT_DIR).resolve() / job_id
        uploads = Path(engine.UPLOAD_DIR).resolve()
        if not path.is_file() or not (path.is_relative_to(output) or
                (path.is_relative_to(uploads) and path.name.startswith(job_id + '_'))):
            raise HTTPException(400, 'Invalid retained source')
        from desktop.native_media import playback_path
        return {'path': await asyncio.to_thread(playback_path,path,output)}

    @engine.app.get('/api/desktop/templates')
    async def templates():
        import video_templates
        return {'templates': video_templates.catalog()}

    @engine.app.get('/api/desktop/media/{job_id}/{clip_index}')
    async def media(job_id: str, clip_index: int):
        # Use recovered clip identity and existing safe-under/servable checks;
        # clients cannot ask the worker to read an arbitrary local file.
        job = engine.jobs.get(job_id)
        if not job or clip_index < 0:
            raise HTTPException(404, 'Clip not found')
        for i, clip in enumerate((job.get('result') or {}).get('clips', [])):
            if clip.get('clip_index', i) != clip_index:
                continue
            from urllib.parse import urlsplit, unquote
            relative = unquote(urlsplit(clip.get('video_url', '')).path).removeprefix('/videos/')
            if not relative.startswith(job_id + '/') or not engine._servable_export(relative):
                raise HTTPException(404, 'Clip media is unavailable')
            path = engine._safe_under(engine.OUTPUT_DIR, relative)
            if path and Path(path).is_file():
                from desktop.native_media import playback_path
                return {'path': await asyncio.to_thread(playback_path,path,Path(path).parent)}
        raise HTTPException(404, 'Clip media is unavailable')

    @engine.app.post('/api/desktop/jobs/{job_id}/cancel')
    async def cancel(job_id: str):
        job = engine.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, 'Job not found')
        if job.get('status') not in ('queued', 'processing'):
            return {'status': job.get('status')}
        job['cancel_requested'] = True
        tree = job.get('_desktop_tree')
        if tree:
            await asyncio.to_thread(tree.close)
        engine._clear_resume_manifest(job_id)
        return {'status': 'cancelling'}


def main():
    from desktop.credentials import CredentialStore
    from desktop.storage import Storage
    from desktop.processes import environment
    from desktop.backend import serve
    local = os.environ.get('OPENSHORTS_LIBRARY')
    token = os.environ.get('OPENSHORTS_LOCAL_TOKEN', '')
    ready = Path(os.environ['OPENSHORTS_READY_FILE']).resolve()
    storage = Storage(local=local, roaming=os.environ.get('OPENSHORTS_ROAMING'))
    if len(token) < 32 or not ready.is_relative_to(storage.work.resolve()):
        raise ValueError('Invalid native bootstrap')
    storage.check_space()
    env = environment(storage, storage.settings(), CredentialStore(storage.roaming).load())
    env.update(OPENSHORTS_LOCAL_TOKEN=token, OPENSHORTS_READY_FILE=str(ready))
    os.environ.clear()
    os.environ.update(env)
    os.chdir(storage.local)
    serve(native=True)
