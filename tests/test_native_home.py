import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from desktop.home import register, snapshot
from desktop.security import LocalAccess


def engine(tmp_path):
    root = tmp_path / 'output'
    root.mkdir()
    def safe(base, relative):
        path = (Path(base) / relative).resolve()
        return str(path) if path.is_relative_to(Path(base).resolve()) else None
    return SimpleNamespace(app=FastAPI(), jobs={}, OUTPUT_DIR=str(root),
        _safe_under=safe, _servable_export=lambda relative: not relative.endswith('rejected.mp4'))


def fixture(e, job_id='job-one'):
    folder = Path(e.OUTPUT_DIR) / job_id
    folder.mkdir()
    path = folder / 'clip.mp4'
    path.write_bytes(b'local video fixture')
    e.jobs[job_id] = {'status': 'completed', 'result': {'clips': [
        {'clip_index': 7, 'title': 'My real project', 'start': 1, 'end': 90,
         'video_url': f'/videos/{job_id}/clip.mp4'}]}}
    stat = path.stat()
    Path(str(path) + '.quality.json').write_text(json.dumps({
        'fingerprint': {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
        'measurements': {'duration': 3.0, 'width': 1080, 'height': 1920}}))
    return path


def test_dashboard_is_authenticated_and_empty_library_is_honest(tmp_path):
    e = engine(tmp_path)
    register(e)
    secured = LocalAccess(e.app, 'x' * 48, 'http://127.0.0.1:5510')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=secured), base_url='http://127.0.0.1:5510') as client:
            assert (await client.get('/api/desktop/home')).status_code == 403
            response = await client.get('/api/desktop/home', headers={'X-OpenShorts-Session': 'x' * 48})
            assert response.status_code == 200
            data = response.json()
            assert data['projects'] == data['exports'] == []
            assert data['project_count'] == data['export_count'] == 0
            assert data['speed_estimate'] is None
    asyncio.run(run())


def test_real_metadata_stable_clip_identity_and_measured_duration(tmp_path, monkeypatch):
    e = engine(tmp_path)
    path = fixture(e)
    monkeypatch.setattr('desktop.home.thumbnail', lambda p: None)
    data = snapshot(e)
    assert data['project_count'] == data['export_count'] == 1
    assert data['projects'][0]['title'] == 'My real project'
    row = data['exports'][0]
    assert row['clip_index'] == 7 and row['size'] == path.stat().st_size
    assert row['duration'] == 3.0 and row['resolution'] == '1080 × 1920'
    # A stale quality sidecar cannot mislabel a modified file.
    path.write_bytes(b'changed video')
    row = snapshot(e)['exports'][0]
    assert row['duration'] == 0 and row['resolution'] == '—'


def test_missing_rejected_foreign_and_traversal_media_not_exposed(tmp_path, monkeypatch):
    e = engine(tmp_path)
    path = fixture(e)
    path.unlink()
    clips = e.jobs['job-one']['result']['clips']
    for url in ['/videos/job-one/../../outside.mp4', '/videos/foreign/clip.mp4',
                '/videos/job-one/rejected.mp4', 'https://example.org/video.mp4']:
        clips.append({'title': 'invalid', 'video_url': url})
    e.jobs['../outside'] = e.jobs['job-one']
    monkeypatch.setattr('desktop.home.thumbnail', lambda p: None)
    data = snapshot(e)
    assert data['exports'] == []
    assert data['project_count'] == 1
    assert data['projects'][0]['thumbnail'] is None


def test_thumbnail_generation_is_bounded_and_cached(tmp_path, monkeypatch):
    from desktop.home import thumbnail
    e = engine(tmp_path)
    path = fixture(e)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs['timeout'] == 8 and '-nostdin' in args
        Path(args[-1]).write_bytes(b'cached jpg')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('desktop.home.subprocess.run', run)
    image = thumbnail(path)
    assert image == thumbnail(path) and len(calls) == 1
    path.write_bytes(b'new content invalidates thumbnail')
    assert thumbnail(path) != image and len(calls) == 2
