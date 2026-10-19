import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from desktop.generation_drafts import register,validate_settings
from desktop.import_worker import probe
from desktop.security import LocalAccess


def test_native_settings_map_existing_engine_options():
    validate_settings(dict(Mode='clips',Analysis='hybrid',OutputFormat='square',AutoDuration=True,AutoCount=True,MinimumSeconds=5,MaximumSeconds=60,CaptionPreset='creator-bold',Framing='subject',Pacing='emotional',AudioPreset='dialogue'),120)
    validate_settings(dict(Mode='highlights',Analysis='hybrid',SummarySeconds=60,TargetSeconds=30,TargetClips=4),120)


@pytest.mark.parametrize('settings',[dict(HighlightStrategy='manual'),dict(HighlightStrategy='key-moments'),dict(Mode='highlights',AutoDuration=True),dict(Analysis='thorough'),dict(OutputFormat='4:5'),dict(StoryMode='comedy'),dict(MinimumSeconds=70),dict(MinimumSeconds=30,MaximumSeconds=31),dict(SourceHasCaptions=True,Captions=True),dict(TargetClips=0),dict(TargetSeconds=float('nan'))])
def test_unsupported_or_invalid_settings_rejected(settings):
    with pytest.raises((ValueError,TypeError)):validate_settings(settings,60)


def test_authenticated_draft_persistence_revision_and_source_validation(tmp_path):
    identity='f'*32;folder=tmp_path/'uploads'/'native-imports'/identity;folder.mkdir(parents=True)
    media=tmp_path/'source.mp4';media.write_bytes(b'fixture media')
    stat=media.stat();(folder/'manifest.json').write_text(json.dumps(dict(path=str(media),duration=120,size=stat.st_size,mtime_ns=stat.st_mtime_ns)))
    output=tmp_path/'output';output.mkdir()
    app=FastAPI();register(SimpleNamespace(app=app,UPLOAD_DIR=str(tmp_path/'uploads'),OUTPUT_DIR=str(output)))
    secured=LocalAccess(app,'x'*48,'http://127.0.0.1:5510')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=secured),base_url='http://127.0.0.1:5510') as client:
            route=f'/api/desktop/imports/{identity}/settings'
            assert (await client.get(route)).status_code==403
            client.headers['X-OpenShorts-Session']='x'*48
            assert (await client.get(route)).json()=={'draft':None}
            body=dict(Version=1,Revision=0,SourceId=identity,Encoder='auto',OutputLocation=str(output),TemplateId='',Settings=dict(Mode='clips',Analysis='hybrid',OutputFormat='square',AutoDuration=True,AutoCount=True,CaptionPreset='creator-bold',Framing='subject'))
            response=await client.put(route,json=body);assert response.status_code==200
            saved=response.json()['draft'];assert saved['Revision']==1
            assert (await client.get(route)).json()['draft']==saved
            assert (await client.put(route,json=body)).status_code==409
            saved['Revision']=1;saved['Settings']['UnsupportedFocus']=['comedy']
            assert (await client.put(route,json=saved)).status_code==400
            del saved['Settings']['UnsupportedFocus'];saved['OutputLocation']=str(tmp_path/'outside')
            assert (await client.put(route,json=saved)).status_code==400
            saved['OutputLocation']=str(output);media.write_bytes(b'changed source')
            assert (await client.put(route,json=saved)).status_code==400
            assert (await client.get(route)).json()['draft']['Revision']==1
            presets=(await client.get('/api/desktop/caption-presets')).json()['presets']
            from caption_renderer import options
            assert presets['creator-bold']==options('creator-bold')
            assert media.exists() and not list(folder.glob('*.writing'))
    asyncio.run(run())
