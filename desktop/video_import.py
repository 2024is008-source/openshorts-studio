"""Session-owned acquisition jobs on the existing authenticated desktop API."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
from fastapi import HTTPException, Request
from story_director import atomic_json

MAX_BYTES = 2 * 1024**3
MAX_SECONDS = 7200
RESERVE = 2 * 1024**3
EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}


def register(engine):
    from desktop.generation_drafts import register as register_drafts
    register_drafts(engine)
    from desktop.processes import ProcessTree, command
    jobs = {}
    cancelled = set()
    lock = threading.RLock()

    def get(identity):
        with lock:
            if identity not in jobs:
                raise HTTPException(404, 'Import is not owned by this session')
            return jobs[identity]

    def state(job):
        path = job['folder'] / 'state.json'
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            data = {'state': 'validating', 'status': 'Validating source…'}
        # The atomic manifest is the commit point. A late cancel must never remove committed media.
        try:
            media = json.loads((job['folder'] / 'manifest.json').read_text('utf-8'))
            return dict(data, state='completed', status='Import completed.', media=media, import_id=job['id'])
        except (OSError, ValueError):
            pass
        if job.get('cancelled'):
            return {'state': 'cancelled', 'status': 'Import cancelled.'}
        if job['process'].poll() is not None and data.get('state') not in ('completed', 'failed'):
            # The worker can commit and exit between the manifest read and poll.
            # Recheck the commit point before classifying a fast import as failed.
            try:
                media = json.loads((job['folder'] / 'manifest.json').read_text('utf-8'))
                return dict(data, state='completed', status='Import completed.', media=media, import_id=job['id'])
            except (OSError, ValueError):
                pass
            try:
                final = json.loads(path.read_text('utf-8'))
                if final.get('state') == 'failed':
                    return dict(final, import_id=job['id'])
            except (OSError, ValueError):
                pass
            data = {'state': 'failed', 'status': 'Import worker stopped. Retry the import.',
                    'worker_exit_code': getattr(job['process'], 'returncode', None)}
        return dict(data, import_id=job['id'])

    def start(body):
        from desktop.import_worker import validate_source
        validate_source(body)  # syntax only; DNS/network belong to the owned worker
        root = Path(engine.UPLOAD_DIR).resolve() / 'native-imports'
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ValueError('Linked import storage is not supported')
        with lock:
            if any(j['process'].poll() is None and state(j).get('state') != 'completed' for j in jobs.values()):
                raise HTTPException(409, 'Another import is still running')
            if len(jobs) >= 100:
                raise HTTPException(429, 'Restart the application before importing more sources')
            if shutil.disk_usage(root).free < RESERVE:
                raise HTTPException(507, 'Free at least 2 GB in the video library and retry')
            identity = body.get('import_id') or uuid.uuid4().hex
            if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
                raise ValueError('Invalid import identity')
            if identity in cancelled:
                raise HTTPException(409, 'Import cancelled before startup')
            if identity in jobs:
                return {'import_id': identity}
            folder = root / identity
            folder.mkdir()
            tree = ProcessTree()
            try:
                atomic_json(str(folder / 'request.json'), body)
                process = tree.start(command('--worker', 'native-import', folder), env=dict(os.environ), cwd=str(root))
            except BaseException:
                tree.close()
                shutil.rmtree(folder)
                raise
            job = dict(id=identity, folder=folder, tree=tree, process=process, cancelled=False, close_lock=threading.Lock())
            jobs[identity] = job
        def monitor():
            try:
                process.wait(timeout=1200)
            except Exception:
                with job['close_lock']:
                    tree.close()
            finally:
                with job['close_lock']:
                    tree.close()
                data = state(job)
                if data.get('state') != 'completed':
                    # This directory was created for this job, never a user directory.
                    for child in folder.iterdir():
                        if (child.name in ('request.json', 'request.json.writing', 'state.json.writing', 'manifest.json.writing', 'preview.jpg') or child.name.startswith('source.')) and child.is_file() and not child.is_symlink():
                            child.unlink(missing_ok=True)
                (folder / 'request.json').unlink(missing_ok=True)
        threading.Thread(target=monitor, daemon=True).start()
        return {'import_id': identity}

    @engine.app.post('/api/desktop/imports')
    async def create(request: Request):
        raw = await request.body()
        if len(raw) > 16384:
            raise HTTPException(413, 'Import request is too large')
        try:
            body = json.loads(raw)
            return await asyncio.to_thread(start, body)
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)[:200])

    @engine.app.get('/api/desktop/imports/{identity}')
    async def status(identity: str):
        return state(get(identity))

    @engine.app.post('/api/desktop/imports/{identity}/cancel')
    async def cancel(identity: str):
        with lock:
            if identity not in jobs:
                if len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity) or len(cancelled) >= 100:
                    raise HTTPException(404, 'Import is not owned by this session')
                cancelled.add(identity)
                return {'state': 'cancelled'}
        job = get(identity)
        if state(job).get('state') == 'completed':
            return state(job)
        job['cancelled'] = True
        def stop():
            with job['close_lock']:
                job['tree'].close()
        await asyncio.to_thread(stop)
        return state(job)
