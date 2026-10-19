"""Bounded local editor media catalogue; no AI calls or client paths."""
import asyncio
import functools
import json
import math
from pathlib import Path
import re
import subprocess

EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.mp3', '.wav', '.m4a', '.aac', '.png', '.jpg', '.jpeg', '.webp'}


@functools.lru_cache(maxsize=128)
def probe(path, size, stamp):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,width,height', '-of', 'json', path],
            capture_output=True, timeout=5)
        data = json.loads(result.stdout[:65536]) if result.returncode == 0 else {}
        duration=float(data.get('format', {}).get('duration') or 0)
        return duration if math.isfinite(duration) and 0<=duration<=864000 else 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return 0


def catalogue(engine, job_id):
    from desktop.home import delivered, thumbnail
    root = Path(engine.OUTPUT_DIR).resolve()
    folder = (root / job_id).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id) or not folder.is_relative_to(root) or job_id not in engine.jobs:
        return []
    candidates = []
    source = engine._locate_source(job_id)
    if source:
        path = Path(source).resolve()
        uploads = Path(engine.UPLOAD_DIR).resolve()
        if path.is_file() and (path.is_relative_to(folder) or path.is_relative_to(uploads) and path.name.startswith(job_id + '_')):
            candidates.append((path, True, None))
    for i, clip in enumerate((engine.jobs[job_id].get('result') or {}).get('clips', [])[:30]):
        path = delivered(engine, job_id, clip)
        if path and not any(p == path for p, _, _ in candidates):
            candidates.append((path, False, clip.get('clip_index', i)))
    media = folder / 'media'
    if media.is_dir() and media.resolve().is_relative_to(folder):
        for path in sorted(media.iterdir())[:100]:
            if path.is_file() and not path.is_symlink() and not path.name.startswith('.') and path.suffix.lower() in EXTENSIONS:
                candidates.append((path.resolve(), False, None))
    rows = []
    for index, (path, source, clip_index) in enumerate(candidates[:100]):
        try:
            stat = path.stat()
            kind = 'Images' if path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'} else 'Audio' if path.suffix.lower() in {'.mp3', '.wav', '.m4a', '.aac'} else 'Videos'
            image = str(path) if kind == 'Images' else thumbnail(path) if kind == 'Videos' and index < 6 else None
            rows.append(dict(path=str(path), name=path.name, kind=kind, source=source,
                clip_index=clip_index, duration=probe(str(path), stat.st_size, stat.st_mtime_ns), thumbnail=image))
        except OSError:
            continue
    return rows


def register(engine):
    @engine.app.get('/api/desktop/assets/{job_id}')
    async def assets(job_id: str):
        return {'assets': await asyncio.to_thread(catalogue, engine, job_id)}
