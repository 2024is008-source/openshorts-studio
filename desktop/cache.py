"""Remove only aged native thumbnail/feature caches, preserving all media."""
import asyncio
from pathlib import Path
import re
import time

PATTERN=re.compile(r'(?:\.desktop-home-[0-9a-f]{16}\.jpg|editor_thumb_[0-9a-f]{24}_[0-7]\.jpg|editor_features_[0-9a-f]{24}\.json)')


def clean(engine,now=None):
    from timeline_api import _active
    root=Path(engine.OUTPUT_DIR).resolve();count=size=skipped=0
    cutoff=(now or time.time())-86400
    for job_id,job in list(engine.jobs.items()):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',job_id):continue
        if job.get('status') in ('queued','processing') or any(key[0]==job_id for key in list(_active)):continue
        folder=(root/job_id).resolve()
        if not folder.is_relative_to(root) or not folder.is_dir():continue
        for directory in (folder,folder/'media'):
            if not directory.is_dir() or not directory.resolve().is_relative_to(folder):continue
            for path in directory.iterdir():
                if not PATTERN.fullmatch(path.name) or path.is_symlink():continue
                try:
                    stat=path.stat()
                    if not path.is_file() or stat.st_mtime>=cutoff:continue
                    path.unlink();count+=1;size+=stat.st_size
                except OSError:skipped+=1
    return dict(files=count,bytes=size,skipped=skipped,minimum_age_hours=24)


def register(engine):
    @engine.app.post('/api/desktop/cache/cleanup')
    async def cleanup():
        return await asyncio.to_thread(clean,engine)
