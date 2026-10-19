import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
import timeline_project as model
from test_export_quality import real_clip  # noqa: F401
from desktop.editor_assets import catalogue, register
from desktop.security import LocalAccess


@pytest.mark.parametrize('value',[{'playhead':float('nan')},{'title':'a\nb'},{'path':'C:/secret'},
    {'assets_visible':1},{'preview_ratio':'evil'},{'segment_index':True}])
def test_workspace_state_rejects_unsafe_or_incompatible_data(value):
    with pytest.raises(ValueError):model.workspace_state(value)


def test_workspace_state_and_export_options_roundtrip():
    state=dict(title='My video',playhead=1.25,assets_visible=False,inspector_visible=True,
        preview_ratio='9:16',segment_index=0,caption_id='7')
    assert model.workspace_state(state)==state
    output=dict(size=[1080,1920],fps=30,encoder='nvenc',quality='high')
    assert model.export_options(output)==output
    assert model.export_options(None)=={}


@pytest.mark.parametrize('value',[{'size':[1,2]},{'fps':True},{'fps':float('nan')},
    {'encoder':'libx264; rm'},{'quality':'invented'},{'path':'outside.mp4'}])
def test_export_options_reject_arbitrary_commands_and_invalid_values(value):
    with pytest.raises(ValueError):model.export_options(value)


def test_explicit_encoder_policy_uses_cpu_and_real_nvenc_probe(monkeypatch):
    import ffmpeg_utils
    from timeline_render import encode
    monkeypatch.setattr(ffmpeg_utils,'nvenc_available',lambda:False)
    assert 'libx264' in encode((1080,1920),options={'encoder':'nvenc','quality':'high'})
    monkeypatch.setattr(ffmpeg_utils,'nvenc_available',lambda:True)
    assert 'h264_nvenc' in encode((1080,1920),options={'encoder':'nvenc','quality':'high'})
    assert 'libx264' in encode((1080,1920),options={'encoder':'x264','quality':'fast'})
    assert 'libx264' in encode((108,192),options={'encoder':'nvenc','quality':'fast'})


def test_export_audio_gain_is_real_cached_and_preserves_source(tmp_path,real_clip):
    import subprocess
    import threading
    import timeline_render
    import export_quality
    source=real_clip('editor-audio')
    identity=export_quality.fingerprint(source)
    settings=dict(volume=0,mute=False,fade=.2,normalize=False,target=-16,ceiling=-2,music=None)
    output=timeline_render.mix_audio(str(source),settings,2,tmp_path,threading.Event(),lambda *a:None)
    assert export_quality.fingerprint(source)==identity
    stamp=Path(output).stat().st_mtime_ns
    assert timeline_render.mix_audio(str(source),settings,2,tmp_path,threading.Event(),lambda *a:None)==output
    assert Path(output).stat().st_mtime_ns==stamp
    decoded=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',output,'-vn','-ac','1','-f','s16le','pipe:1'],capture_output=True,check=True,timeout=15).stdout
    import array
    samples=array.array('h');samples.frombytes(decoded)
    assert len(samples)>1000 and max(abs(n) for n in samples)<5


def test_audio_edits_reject_external_music_and_keep_old_projects_compatible():
    edits=model.initial({},[dict(start=0,end=2)],None)['edits']
    assert 'audio' not in model.normalize(edits,2,[])
    edits['audio']=dict(volume=.5,mute=False,fade=.2,normalize=True,target=-16,ceiling=-2,music='music.mp3')
    assert model.normalize(edits,2,[])['audio']['volume']==.5
    for value in ('../outside.mp3','C:\\outside.mp3','file.mp4'):
        edits['audio']['music']=value
        with pytest.raises(ValueError):model.normalize(edits,2,[])


def test_catalogue_authentication_and_source_path_boundary(tmp_path,monkeypatch):
    output=tmp_path/'output';folder=output/'job-one';folder.mkdir(parents=True)
    uploads=tmp_path/'uploads';uploads.mkdir()
    outside=tmp_path/'secret.mp4';outside.write_bytes(b'outside')
    engine=SimpleNamespace(app=FastAPI(),OUTPUT_DIR=str(output),UPLOAD_DIR=str(uploads),
        jobs={'job-one':{'result':{'clips':[]}}},_locate_source=lambda _:str(outside))
    register(engine)
    assert catalogue(engine,'job-one')==[]
    assert catalogue(engine,'../outside')==[]
    source=folder/'source.mp4';source.write_bytes(b'source')
    engine._locate_source=lambda _:str(source)
    monkeypatch.setattr('desktop.home.thumbnail',lambda _:None)
    monkeypatch.setattr('desktop.editor_assets.probe',lambda *args:5)
    rows=catalogue(engine,'job-one')
    assert len(rows)==1 and rows[0]['source'] and rows[0]['duration']==5
    app=LocalAccess(engine.app,'s'*48,'http://127.0.0.1:5511')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:5511') as client:
            assert (await client.get('/api/desktop/assets/job-one')).status_code==403
            assert (await client.get('/api/desktop/assets/job-one',headers={'X-OpenShorts-Session':'s'*48})).json()['assets'][0]['name']=='source.mp4'
    asyncio.run(run())


def test_cache_files_are_not_user_assets_and_cleanup_preserves_media(tmp_path,monkeypatch):
    import os,time
    from desktop.cache import clean
    folder=tmp_path/'output'/'job-one';media=folder/'media';media.mkdir(parents=True)
    cache=media/('.desktop-home-'+'a'*16+'.jpg');cache.write_bytes(b'generated')
    feature=folder/('editor_features_'+'b'*24+'.json');feature.write_text('{}')
    source=media/'music.wav';source.write_bytes(b'user media')
    unrelated=media/'editor_thumb_user_picture.jpg';unrelated.write_bytes(b'user image')
    old=time.time()-90000
    for path in (cache,feature,source,unrelated):os.utime(path,(old,old))
    engine=SimpleNamespace(OUTPUT_DIR=str(tmp_path/'output'),UPLOAD_DIR=str(tmp_path/'uploads'),
        jobs={'job-one':{'status':'completed','result':{'clips':[]}}},_locate_source=lambda _:None)
    monkeypatch.setattr('desktop.editor_assets.probe',lambda *a:1)
    rows=catalogue(engine,'job-one')
    assert cache.name not in [r['name'] for r in rows]
    result=clean(engine)
    assert result['files']==2 and not cache.exists() and not feature.exists()
    assert source.exists() and unrelated.exists()


def test_long_native_media_uses_short_alias_without_changing_source(tmp_path):
    from desktop.native_media import playback_path
    folder=tmp_path/'project';folder.mkdir()
    deep=folder/('long-source-'*8);deep.mkdir()
    source=deep/('video-'*22+'.mp4');source.write_bytes(b'approved local video')
    assert len(str(source.resolve()))>=240
    alias=Path(playback_path(source,folder))
    assert alias.parent==folder and alias.name.startswith('.desktop-preview-')
    assert alias.read_bytes()==source.read_bytes()
    assert playback_path(source,folder)==str(alias)
