"""Read-only native dashboard, derived from recovered projects and delivered media.

Never accepts client filesystem paths. Thumbnail work is bounded, cached and runs
inside the existing owned desktop worker, without invoking any AI provider.
"""
import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def delivered(engine, job_id, clip):
    url = clip.get('video_url', '')
    if not isinstance(url, str) or not url.startswith('/videos/'):
        return None
    relative = unquote(urlsplit(url).path)[len('/videos/'):]
    if not relative.startswith(job_id + '/') or not engine._servable_export(relative):
        return None
    safe = engine._safe_under(engine.OUTPUT_DIR, relative)
    if safe and Path(safe).is_file():
        return Path(safe).resolve()
    return None


def thumbnail(path):
    fingerprint = hashlib.sha256(f'{path.name}:{path.stat().st_size}:{path.stat().st_mtime_ns}'.encode()).hexdigest()[:16]
    target = path.parent / f'.desktop-home-{fingerprint}.jpg'
    if target.is_symlink():
        return None
    if not target.exists():
        try:
            result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y',
                '-i', str(path), '-frames:v', '1', '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2',
                '-threads', '1', str(target)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
            if result.returncode:
                target.unlink(missing_ok=True)
                return None
        except (OSError, subprocess.SubprocessError):
            target.unlink(missing_ok=True)
            return None
    return str(target) if target.is_file() else None


def snapshot(engine):
    root = Path(engine.OUTPUT_DIR).resolve()
    projects, exports = [], []
    for job_id, job in list(engine.jobs.items()):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
            continue
        folder = (root / job_id).resolve()
        if not folder.is_relative_to(root) or not folder.is_dir():
            continue
        clips = (job.get('result') or {}).get('clips', [])
        clips = [clip for clip in clips if isinstance(clip, dict)]
        if not clips:
            continue
        media = []
        for i, clip in enumerate(clips):
            try:
                path = delivered(engine, job_id, clip)
                if path:
                    stat = path.stat()
                    duration, resolution = 0, '—'
                    report = Path(str(path) + '.quality.json')
                    if report.is_file() and not report.is_symlink() and report.stat().st_size < 2 * 1024**2:
                        try:
                            quality = json.loads(report.read_text('utf-8'))
                            if quality.get('fingerprint') == {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}:
                                measured = quality.get('measurements', {})
                                duration = float(measured.get('duration', 0))
                                if not math.isfinite(duration) or duration < 0:
                                    duration = 0
                                width, height = int(measured.get('width', 0)), int(measured.get('height', 0))
                                if width > 0 and height > 0:
                                    resolution = f'{width} × {height}'
                        except (OSError, ValueError, TypeError, OverflowError):
                            pass
                    row = dict(job_id=job_id, clip_index=clip.get('clip_index', i),
                        title=str(clip.get('title') or path.stem)[:240],
                        modified=stat.st_mtime, size=stat.st_size, duration=duration,
                        format=path.suffix.lstrip('.').upper(), resolution=resolution, video_url=clip['video_url'])
                    media.append((row, path))
                    exports.append(row)
            except (OSError, TypeError, ValueError):
                continue
        modified = max([folder.stat().st_mtime] + [r['modified'] for r, _ in media])
        projects.append(dict(job_id=job_id, title=str((job.get('result') or {}).get('title') or clips[0].get('title') or job_id)[:240],
            clips=len(clips), status=job.get('status', 'unknown'), modified=modified,
            size=sum(r['size'] for r, _ in media), thumbnail=None,
            _media=media[0][1] if media else None))
    projects.sort(key=lambda x: x['modified'], reverse=True)
    for project in projects[:3]:
        try:
            if project['_media']:
                project['thumbnail'] = thumbnail(project['_media'])
        except OSError:
            pass
    for project in projects:
        project.pop('_media', None)
    exports.sort(key=lambda x: x['modified'], reverse=True)
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    return dict(projects=projects[:500], exports=exports[:12],
        project_count=len(projects), export_count=len(exports), free_bytes=free,
        exports_description='Rendered clip files in your local library',
        speed_estimate=None)


def register(engine):
    lock = asyncio.Lock()

    @engine.app.get('/api/desktop/home')
    async def home():
        # Serialise cache writes; no FFmpeg work on the ASGI event loop.
        async with lock:
            return await asyncio.to_thread(snapshot, engine)
