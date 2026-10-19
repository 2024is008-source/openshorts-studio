"""TASK-008 deterministic identity, real libass frames, and existing editor routes."""
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import threading

import httpx
import numpy as np
import pytest
from PIL import Image

import app
import export_quality as quality
import timeline_api
import timeline_project as project
import timeline_render
import video_templates as v
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401

BASE='/api/clip/quality-job/0/editor'


def speech():
    return {'segments':[dict(start=0,end=1,text='Can we finish?',words=[
        dict(word=' Can',start=0,end=.25),dict(word=' we',start=.25,end=.5),dict(word=' finish?',start=.5,end=1)])]}


def edits(template=None):
    value=project.initial({},[dict(start=0,end=2)],None)['edits']
    value['template']=template or v.selected('creator-energy')
    value['template_content']=dict(headline=dict(text='Can we finish?',start=0,end=1.8),labels=[])
    return value


def test_starters_are_versioned_content_free_and_independent():
    library=v.catalog()
    assert len(library)==5 and len({t['id'] for t in library})==5
    for template in library:
        assert template['version']==1 and template['transition']=='cut'
        assert 'headline' not in template and 'labels' not in template
        assert not any(word in json.dumps(template).lower() for word in ['million','prize','treadmill','http:','https:'])
        assert v.normalize(template)==template
    library[0]['colors']['primary']='#FFFFFF'
    assert v.catalog()[0]['colors']['primary']=='#00D9EC'


@pytest.mark.parametrize('section,key,value',[
    ('fonts','family','movie=/etc/passwd'),('colors','primary','red;movie=private'),
    ('fonts','caption_size',float('nan')),('fonts','caption_size',300),
    ('safe','side',0),('safe','bottom',.05),('motion','seconds',float('inf')),
    ('logo','text','bad\nname'),('audio','target',-2),('layout','preference','force-split')])
def test_unsafe_settings_rejected(section,key,value):
    template=v.catalog()[0];template[section][key]=value
    with pytest.raises(ValueError):v.normalize(template)


def test_no_unrecognized_fields_and_unavailable_template():
    template=v.catalog()[0];template['source_path']='../.env'
    with pytest.raises(ValueError):v.normalize(template)
    with pytest.raises(ValueError):v.selected('../../private')
    assert v.selected('none') is None


def test_content_grounding_timestamps_and_template_separation():
    template=v.catalog()[0];original=copy.deepcopy(template)
    assert v.content(edits()['template_content'],speech(),2)['headline']['text']=='Can we finish?'
    assert template==original
    for patch in [dict(text='We won a million dollars!'),dict(end=5),dict(start=1,end=.5)]:
        data=edits()['template_content'];data['headline'].update(patch)
        with pytest.raises(ValueError):v.content(data,speech(),2)
    assert v.initial_content(template,{},2)['headline']['text']==''
    data=dict(labels=[dict(kind='progress',text='We completed 2 of 5.',start=0,end=1,evidence='We completed 2 of 5.')])
    with pytest.raises(ValueError):v.content(data,speech(),2)
    evidence={'segments':[dict(start=0,end=1,text='We completed 2 of 5.')]}
    assert v.content(data,evidence,2)['labels'][0]['text']=='We completed 2 of 5.'
    data['labels'][0]['text']='5'
    with pytest.raises(ValueError):v.content(data,evidence,2)


def test_captions_and_headline_keep_alignment_and_safes(tmp_path):
    ass=tmp_path/'template.ass';template=v.catalog()[0]
    template['safe'].update(top=.2,bottom=.3,side=.16)
    v.make_ass(ass,template,speech(),2,(1080,1920),text=edits()['template_content'])
    raw=ass.read_text(encoding='utf-8-sig')
    assert 'PlayResX: 1080' in raw and 'PlayResY: 1920' in raw
    assert 'Can we finish?' in raw and r'\fscx85' in raw
    assert '0:00:00.25' in raw and '0:00:00.50' in raw
    assert r'\c&HECD900&' in raw
    # A completely protected subject region suppresses optional hook/branding.
    template['logo']['enabled']=True
    v.make_ass(ass,template,speech(),2,(1080,1920),text=edits()['template_content'],captions=False,
        faces=[dict(start=0,end=2,x=0,y=0,width=1,height=1)])
    assert not any(line.startswith('Dialogue:') for line in ass.read_text(encoding='utf-8-sig').splitlines())


@pytest.fixture(scope='module')
def layout_media(tmp_path_factory):
    directory=tmp_path_factory.mktemp('template-layouts');result={}
    # Deterministic already-composed shots isolate template preservation from
    # detector variability. Reframer tests separately cover source geometry.
    filters={
        'CENTER':'color=c=0x304050:s=1080x1920:r=4:d=1',
        'TRACK':'color=c=0x304050:s=1080x1920:r=4:d=1,drawbox=x=460:y=500:w=160:h=400:color=0xC08060:t=fill',
        'BLUR':'color=c=0x304050:s=1080x1920:r=4:d=1,drawbox=x=0:y=650:w=1080:h=608:color=0x447799:t=fill',
        'SPLIT':'color=c=0x304050:s=1080x1920:r=4:d=1,drawbox=x=0:y=960:w=1080:h=960:color=0x704030:t=fill',
        'EDITORIAL':'color=c=0x304050:s=1080x1920:r=4:d=1,drawbox=x=0:y=1050:w=1080:h=600:color=0x447799:t=fill'}
    for name,source in filters.items():
        path=directory/f'{name}.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',source,
            '-c:v','libx264','-threads','1','-preset','ultrafast','-pix_fmt','yuv420p',str(path)],
            check=True,capture_output=True,timeout=30)
        result[name]=path
    return result


def frame(path):
    raw=subprocess.run(['ffmpeg','-v','error','-threads','1','-ss','0.5','-i',str(path),'-frames:v','1',
        '-filter_threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],check=True,capture_output=True,timeout=15).stdout
    return np.frombuffer(raw,dtype=np.uint8).reshape(1920,1080,3)


@pytest.mark.parametrize('template_id',['creator-energy','minimal-studio','story-focus','podcast','challenge'])
@pytest.mark.parametrize('layout',['CENTER','TRACK','BLUR','SPLIT','EDITORIAL'])
def test_full_hd_frame_regression(tmp_path,layout_media,template_id,layout):
    output=tmp_path/'render.mp4';template=v.selected(template_id)
    text=dict(headline=dict(text='Can we finish?',start=0,end=1),labels=[])
    ranges=[dict(start=0,end=1,layout=layout)]
    v.render(layout_media[layout],output,template,speech(),1,text=text,ranges=ranges,faces=[])
    video,_=quality.streams(quality.probe(output))
    assert (video['width'],video['height'])==(1080,1920)
    picture=frame(output);before=frame(layout_media[layout])
    # Every outer edge retains the source: no unexpected padding or full canvas.
    perimeter=np.concatenate([picture[:25].reshape(-1,3),picture[-100:].reshape(-1,3),
        picture[:,:50].reshape(-1,3),picture[:,-50:].reshape(-1,3)])
    expected=np.concatenate([before[:25].reshape(-1,3),before[-100:].reshape(-1,3),
        before[:,:50].reshape(-1,3),before[:,-50:].reshape(-1,3)])
    assert np.mean(np.abs(perimeter.astype(float)-expected))<3
    assert np.mean(perimeter)>15
    # Shared hook top region and caption band contain rendered graphics.
    difference=np.max(np.abs(picture.astype(float)-before),axis=2)
    if layout=='EDITORIAL':
        assert difference[100:500,100:950].mean()<3  # distributed context wins over a headline
    else:assert (difference[100:500,100:950]>25).sum()>80
    caption_band=(850,1050) if layout=='SPLIT' else (1000,1250) if layout=='EDITORIAL' else (1250,1550)
    assert (difference[caption_band[0]:caption_band[1],100:950]>25).sum()>50
    # Delivered shot geometry remains unchanged outside overlay regions.
    assert np.abs(picture[600,540].astype(float)-before[600,540]).max()<10
    Image.fromarray(picture).save(tmp_path/f'{template_id}-{layout}.png')


def test_custom_save_duplicate_reopen_and_batch_preflight(job):
    template=v.catalog()[0];original=copy.deepcopy(template)
    saved=request('POST',BASE+'/templates',json={'template':dict(template,name='My cyan style')})
    assert saved.status_code==200,saved.text
    custom=saved.json()['template'];assert custom['id'].startswith('custom-')
    duplicate=request('POST',BASE+'/templates',json={'template':custom}).json()['template']
    assert duplicate['id']!=custom['id'] and len(request('GET',BASE+'/templates').json()['templates'])==7
    assert template==original
    data=json.loads(job['meta'].read_text());data['shorts'].append(dict(data['shorts'][0],clip_id='clip_2'))
    job['meta'].write_text(json.dumps(data))
    second='/api/clip/quality-job/1/editor'
    assert request('GET',second).status_code==200
    before=job['video'].read_bytes()
    rejected=request('POST',BASE+'/template-batch',json={'template':custom,'clips':{'0':0,'1':9}})
    assert rejected.status_code==409
    assert request('GET',BASE).json()['project']['revision']==0
    applied=request('POST',BASE+'/template-batch',json={'template':custom,'clips':{'0':0,'1':0}})
    assert applied.status_code==200,applied.text
    assert request('GET',second).json()['project']['edits']['template']==custom
    assert request('GET',BASE).json()['project']['revision']==1
    assert job['video'].read_bytes()==before


def test_template_save_grounding_and_auth(job,monkeypatch):
    draft=request('GET',BASE).json()['project'];data=edits()
    assert request('PUT',BASE,json={'revision':draft['revision'],'edits':data}).status_code==400
    data['template_content']['headline']['text']=''
    assert request('PUT',BASE,json={'revision':0,'edits':data}).status_code==200
    assert request('GET',BASE).json()['project']['edits']['template']==data['template']
    from types import SimpleNamespace
    job['record']['user_id']='owner';monkeypatch.setattr(app,'BILLING_ENABLED',True)
    async def foreign(_):return SimpleNamespace(id='other')
    monkeypatch.setattr(app,'_user_from_request',foreign)
    assert request('GET',BASE+'/templates').status_code==404
    assert request('POST',BASE+'/templates',json={'template':v.catalog()[0]}).status_code==404
    assert request('POST',BASE+'/template-batch',json={'template':v.catalog()[0],'clips':{'0':1}}).status_code==404


def test_template_changes_reuse_video_and_preview_final_share_decisions(tmp_path,real_clip,monkeypatch):
    monkeypatch.setenv('CAPTION_FACE_PLACEMENT','0')
    source=real_clip('template-source',video='color=c=0x304050:s=108x192:r=24:d=2')
    rows=project.captions(speech());data=edits();data['template']['logo']['enabled']=True
    common=dict(rows=rows,source=str(source),canonical=str(source),canonical_range=dict(start=0,end=2),
        fps=24,audio=True,directory=tmp_path,cancel=threading.Event(),progress=lambda *args:None)
    first,cache=timeline_render.render(edits=data,size=(108,192),**common)
    data['template']['colors']['primary']='#FF00FF'
    changed,changed_cache=timeline_render.render(edits=data,size=(108,192),**common)
    assert changed!=first and changed_cache['segment_hits']==1 and changed_cache['clean_key']==cache['clean_key']
    assert changed_cache['template_applied']
    final,final_cache=timeline_render.render(edits=data,size=(1080,1920),**common)
    assert quality.streams(quality.probe(final))[0]['width']==1080 and final_cache['template_applied']
    assert v.audio_settings(data['template'])['target']==-16


def test_face_policy_upgrade_invalidates_overlays_but_reuses_clean_video(tmp_path,real_clip,monkeypatch):
    import caption_renderer
    monkeypatch.setenv('CAPTION_FACE_PLACEMENT','0')
    source=real_clip('face-policy-source',video='color=c=0x304050:s=108x192:r=24:d=2')
    common=dict(edits=edits(),rows=project.captions(speech()),source=str(source),canonical=str(source),
        canonical_range=dict(start=0,end=2),size=(108,192),fps=24,audio=True,directory=tmp_path,
        cancel=threading.Event(),progress=lambda *args:None)
    first,before=timeline_render.render(**common)
    monkeypatch.setattr(caption_renderer,'FACE_PLACEMENT_VERSION',caption_renderer.FACE_PLACEMENT_VERSION+1)
    second,after=timeline_render.render(**common)
    assert first!=second and before['clean_key']==after['clean_key']
    assert after['segment_hits']==1


def test_template_without_captions_publishes_graphics_and_correct_audio(job,monkeypatch):
    monkeypatch.setenv('CAPTION_FACE_PLACEMENT','0');monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *args:None)
    draft=request('GET',BASE).json()['project'];data=draft['edits'];data['template']=v.selected('challenge')
    data['template']['logo']['enabled']=True;data['template']['audio']['target']=-18.
    data['template_content']=dict(headline=dict(text='',start=0,end=1),labels=[])
    data['style']['enabled']=False
    assert request('PUT',BASE,json={'revision':0,'edits':data}).status_code==200
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            assert (await client.post(BASE+'/run',json={'revision':1,'mode':'final'})).status_code==200
            await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],40)
            saved=(await client.get(BASE)).json()['project']
            assert saved['status']=='completed',saved
            assert saved['result']['cache']['template_applied']
            assert saved['result']['quality_report']['audio_mastering']['key']['settings']['target']==-18
            filename=saved['result']['new_video_url'].split('/')[-1]
            assert filename.startswith('subtitled_') and quality.read_report(job['directory']/filename)['accepted']
    asyncio.run(run())


def test_generation_template_selection_and_legacy_default():
    from generation_options import normalize_options,RESUME_OPTIONS
    assert 'VIDEO_TEMPLATE' not in normalize_options()
    assert normalize_options(video_template='podcast')['VIDEO_TEMPLATE']=='podcast'
    assert 'VIDEO_TEMPLATE' in RESUME_OPTIONS
    assert request('GET','/api/video-templates').status_code==200
    with pytest.raises(ValueError):normalize_options(video_template='missing')


def test_layer_edits_preserve_template_and_caption_disable(job,monkeypatch):
    data=json.loads(job['meta'].read_text());data['transcript']=speech()
    clip=data['shorts'][0]
    clip.update(video_template=v.selected('story-focus'),template_content=edits()['template_content'],template_captions_enabled=False)
    job['meta'].write_text(json.dumps(data))
    calls=[]
    monkeypatch.setattr(v,'render',lambda *args,**kwargs:calls.append((args,kwargs)))
    output=app._reapply_captions('quality-job',0,str(job['video']),suppress_template_hook=True)
    assert output and calls
    assert not calls[0][0][2]['hook']['enabled'] and not calls[0][1]['captions']
    assert calls[0][0][2]['captions']['preset']=='cinematic'
    assert calls[0][1]['text']==clip['template_content']
    assert v.selected('story-focus')['hook']['enabled']  # library was not mutated


def test_template_feature_flag_and_framing_policy(monkeypatch):
    monkeypatch.setenv('FRAMING_PRESET','balanced')
    monkeypatch.setenv('VIDEO_TEMPLATE','story-focus')
    assert v.framing_preference()=='balanced'
    monkeypatch.setenv('VIDEO_TEMPLATE','podcast')
    assert v.framing_preference()=='balanced'
    monkeypatch.setenv('VIDEO_TEMPLATE','none')
    assert v.framing_preference()=='balanced'
    monkeypatch.setenv('VIDEO_TEMPLATES_ENABLED','0')
    assert v.selected('none') is None
    with pytest.raises(ValueError,match='disabled'):v.selected('podcast')


def test_template_normalization_is_required_again_after_trimming():
    rows=project.captions(speech());data=edits()
    assert project.normalize(data,2,rows)['template_content']['headline']['text']=='Can we finish?'
    data['segments']=[dict(start=.5,end=2)]
    with pytest.raises(ValueError):project.normalize(data,2,rows)


def test_malformed_library_and_batch_path_indices_are_rejected(job):
    path=job['directory']/'custom_video_templates.json';path.write_text('{bad')
    assert request('GET',BASE+'/templates').status_code==409
    path.unlink()
    result=request('POST',BASE+'/template-batch',json={'template':v.catalog()[0],'clips':{'../file':0}})
    assert result.status_code==400 and not list(job['directory'].glob('editor_project_*'))
