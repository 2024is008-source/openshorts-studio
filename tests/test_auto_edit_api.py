import json
import asyncio
import httpx

import pytest

import auto_edit
import editing_director
import story_director
import app
import timeline_api
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401

BASE='/api/clip/quality-job/0/editor'


def attach_plan(job):
    words={'segments':[dict(start=.2,end=1.4,words=[dict(word=' 100',start=.3,end=.8)])]}
    cues={'moments':[{'editing_cues':[dict(kind='number',start=.2,end=1.4,quote='100',evidence='The speaker says 100.',confidence=.95)]}]}
    plan=editing_director.compile_plan(media=str(job['video']),width=64,height=36,fps=24.,out_size=(108,192),
        ranges=[(0,48,'TRACK')],xs=[22]*48,ys=[0]*48,crop_size=(20,36),
        context={'source_path':str(job['video']),'segments':[dict(start=0,end=2)],'transcript':words,'analysis':cues},
        subjects={0:[[27,12,5,8]]})
    editing_director.save(job['video'],plan)
    data=json.loads(job['meta'].read_text());data['shorts'][0]['edit_decision_file']=job['video'].name+'.edit.json'
    job['meta'].write_text(json.dumps(data));return plan


def test_regenerate_reuses_retained_analysis_and_preserves_manual_overrides(job,monkeypatch):
    attach_plan(job)
    monkeypatch.setattr(story_director,'analyze_source',lambda *a,**k:pytest.fail('No paid analysis during regeneration'))
    result=request('GET',BASE);assert result.status_code==200,result.text
    project=result.json()['project'];settings=project['edits']['auto_edit']
    assert settings['effects'][0]['type']=='number_highlight'
    settings['effects'][0].update(origin='manual',intensity=.3)
    response=request('POST',BASE+'/auto-edit',json=dict(revision=0,settings=settings))
    assert response.status_code==200,response.text
    assert response.json()['provider_calls']==response.json()['transcription_runs']==0
    value=response.json()['auto_edit']
    assert next(e for e in value['effects'] if e['origin']=='manual')['intensity']==.3
    project['edits']['auto_edit']=value
    saved=request('PUT',BASE,json=dict(revision=0,edits=project['edits']))
    assert saved.status_code==200,saved.text
    assert request('GET',BASE).json()['project']['edits']['auto_edit']==saved.json()['project']['edits']['auto_edit']
    assert request('POST',BASE+'/auto-edit',json=dict(revision=0,settings=settings)).status_code==409


def test_missing_scene_analysis_does_not_fabricate_effects(job):
    response=request('POST',BASE+'/auto-edit',json=dict(revision=0,settings=auto_edit.defaults()))
    assert response.status_code==200,response.text
    assert response.json()['auto_edit']['effects']==[]
    assert response.json()['auto_edit']['skipped']


def test_effect_only_final_export_preserves_clean_base_for_removal(job,monkeypatch):
    attach_plan(job)
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            edits=(await client.get(BASE)).json()['project']['edits'];edits['style']['enabled']=False
            config=edits['auto_edit'];config['effects'][0].update(type='smooth_zoom_in',category='camera',parameters=dict(zoom=1.06),origin='manual')
            assert (await client.put(BASE,json=dict(revision=0,edits=edits))).status_code==200
            assert (await client.post(BASE+'/run',json=dict(revision=1,mode='final'))).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],60)
            saved=(await client.get(BASE)).json()['project'];assert saved['status']=='completed',saved
            assert saved['result']['cache']['effects_applied']
            data=json.loads(job['meta'].read_text());clip=data['shorts'][0]
            clean=job['directory']/clip['editor_clean_file'];delivered=job['directory']/saved['result']['new_video_url'].split('/')[-1]
            assert clean.is_file() and delivered.is_file() and clean.read_bytes()!=delivered.read_bytes()
            assert saved['result']['quality_report']['accepted']
            # Disabling effects uses the clean base, rather than applying another zoom.
            edits=saved['edits'];edits['auto_edit']['enabled']=False
            assert (await client.put(BASE,json=dict(revision=1,edits=edits))).status_code==200
            assert (await client.post(BASE+'/run',json=dict(revision=2,mode='preview'))).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],60)
            again=(await client.get(BASE)).json()['project'];assert again['status']=='preview_ready',again
            assert not again['result']['cache']['effects_applied']
    asyncio.run(scenario())
