"""Local project library; only registered inside the protected desktop backend."""
import json
from pathlib import Path
import re
from fastapi import HTTPException, Request
from story_director import atomic_json


def register(engine):
    def directory(job_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
            raise HTTPException(404, 'Project not found')
        root = Path(engine.OUTPUT_DIR).resolve()
        path = (root / job_id).resolve()
        if not path.is_relative_to(root) or not path.is_dir() or job_id not in engine.jobs:
            raise HTTPException(404, 'Project not found')
        return path

    @engine.app.get('/api/desktop/projects')
    async def projects():
        items = []
        for job_id, job in list(engine.jobs.items()):
            if not (job.get('result') or {}).get('clips'):
                continue
            try:
                path = directory(job_id)
                items.append({'job_id': job_id, 'clips': len(job['result']['clips']),
                              'modified': path.stat().st_mtime, 'status': job['status']})
            except (OSError, HTTPException):
                continue
        return {'projects': sorted(items, key=lambda item: item['modified'], reverse=True)}

    @engine.app.post('/api/desktop/projects/{job_id}/restore')
    async def restore(job_id: str):
        path = directory(job_id) / 'desktop-state.json'
        state = None
        if path.exists():
            try: state = json.loads(path.read_text('utf-8'))
            except (OSError, ValueError): pass
        job = engine.jobs[job_id]
        return {'job_id': job_id, 'status': job['status'], 'result': job.get('result'), 'project_state': state}

    @engine.app.put('/api/projects/{job_id}/state')
    async def save_state(job_id: str, request: Request):
        path = directory(job_id)
        body = await request.body()
        if len(body) > 1024**2:
            raise HTTPException(413, 'Project state is too large')
        try: state = json.loads(body)
        except ValueError: raise HTTPException(400, 'Invalid project state')
        if not isinstance(state, dict) or not isinstance(state.get('clips'), list) or len(state['clips']) > 1000:
            raise HTTPException(400, 'Invalid project clips')
        existing = {}
        target = path / 'desktop-state.json'
        if target.exists():
            try: existing = json.loads(target.read_text('utf-8'))
            except (OSError, ValueError): pass
        merged = {clip['index']: clip for clip in existing.get('clips', [])}
        for clip in state['clips']:
            if not isinstance(clip, dict) or type(clip.get('index')) is not int or clip['index'] < 0:
                raise HTTPException(400, 'Invalid clip index')
            name = clip.get('server_file')
            if name is not None and (not isinstance(name, str) or Path(name).name != name or
                not (path / name).resolve().is_relative_to(path) or not (path / name).is_file()):
                raise HTTPException(400, 'Invalid clip media path')
            merged[clip['index']] = {key: clip.get(key) for key in ('index', 'server_file', 'active_layers')}
        atomic_json(str(target), {'clips': list(merged.values())})
        return {'saved': True}
