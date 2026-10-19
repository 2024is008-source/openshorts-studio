"""TASK-004: measured timing, native libass frames, and editable caption tracks."""
import copy
import json
import re
import shutil
import subprocess

import numpy as np
import pytest

import caption_renderer as cr
import transcribe_backends as tb
from caption_timing import relative_words, phrases, caption_position
from subtitles import _escape_ffmpeg_filter_value
from test_caption_api import caption_job  # noqa: F401
from test_export_quality_api import job, request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401


def speech():
    return {'segments':[{'words':[dict(word=' Hello,',start=.1,end=.4,emphasis=True),
                                  dict(word=' world!',start=.8,end=1.2)]}]}


def test_measured_clock_clamp_and_emphasis(tmp_path):
    transcript=speech();before=copy.deepcopy(transcript)
    words=relative_words(transcript,.2,1,.1)
    assert words[0]['start']==0 and words[0]['end']==pytest.approx(.3)
    assert words[0]['emphasis'] and words[-1]['end']==.8
    ass=tmp_path/'duration.ass'
    assert cr.generate(transcript,0,20,ass,media_duration=1,preset='creator-bold')
    events=[line.split(',')[2] for line in ass.read_text(encoding='utf-8-sig').splitlines() if line.startswith('Dialogue:')]
    assert max(events)<='0:00:01.00'
    assert transcript==before


def test_fast_punctuation_and_configurable_groups():
    transcript={'segments':[{'words':[dict(word=' Yes.',start=i*.08,end=i*.08+.06) for i in range(12)]}]}
    blocks=phrases(relative_words(transcript,0,2),max_words=4,min_duration=.45)
    assert [len(b) for b in blocks]==[4,4,4]
    assert relative_words(None,0,1)==[]


def test_face_appearing_mid_phrase_reserves_whole_interval():
    face=[dict(start=.5,end=1,x=.2,y=.5,width=.6,height=.3)]
    assert caption_position(.1,faces=face)[1]>.5
    assert caption_position(.1,faces=face,end=1)[1]<.5


@pytest.mark.parametrize('effect',['none','fade','pop','scale','reveal','bounce'])
def test_animation_is_valid_ass_and_never_restarts_on_word_boundary(tmp_path,effect):
    path=tmp_path/f'{effect}.ass'
    assert cr.generate(speech(),0,2,path,preset='openshorts-dynamic',effect=effect,line_spacing=1.6,max_words=2)
    text=path.read_text(encoding='utf-8-sig')
    assert not any(ord(char)<32 and char not in '\n\r\t' for char in text)
    if effect in ('pop','bounce'):
        assert '\\fscx100.000' in cr.animation_tags(effect,400,100)
        assert '\\fscx94.000' not in cr.animation_tags(effect,400,100)
    if effect=='reveal':assert '\\alpha&HFF&' in text
    if effect=='scale':assert '\\fscx106.000' in text


def test_two_line_spacing_and_hook_safe_area(tmp_path):
    p=tmp_path/'safe.ass'
    transcript={'segments':[{'words':[dict(word=' '+word,start=i*.1,end=i*.1+.1)
        for i,word in enumerate(['A','readable','caption','with','natural','lines'])]}]}
    assert cr.generate(transcript,0,2,p,font_size=80,line_spacing=1.6,max_lines=2,position='top',
        faces=[dict(x=0,y=.06,width=1,height=.2,start=0,end=2)])
    positions=[int(y) for y in re.findall(r'\\pos\(518,(\d+)\)',p.read_text(encoding='utf-8-sig'))]
    assert positions and min(positions)>1920*.26 and max(positions)<1920*.80


def test_audio_clock_delay_is_observed_once_and_safe(tmp_path,monkeypatch):
    media=tmp_path/'delayed.mp4';media.write_bytes(b'fixture')
    transcript=speech();before=copy.deepcopy(transcript)
    monkeypatch.setattr(tb.subprocess,'check_output',lambda *a,**k:json.dumps({
        'format':{'start_time':'3'},'streams':[{'codec_type':'audio','start_time':'3.25'}]}).encode())
    anchored=tb._anchor_audio_clock(media,transcript)
    assert anchored['segments'][0]['words'][0]['start']==.35
    assert anchored['audio_offset_seconds']==.25 and transcript==before
    assert tb._anchor_audio_clock(media,anchored) is anchored
    monkeypatch.setenv('CAPTION_MEDIA_CLOCK','0')
    assert tb._anchor_audio_clock(media,transcript) is transcript


def test_missing_audio_clock_probe_falls_back(tmp_path,monkeypatch):
    media=tmp_path/'exists.mp4';media.touch()
    monkeypatch.setattr(tb.subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('ffprobe',30)))
    transcript=speech()
    assert tb._anchor_audio_clock(media,transcript) is transcript


@pytest.mark.parametrize('fps',[24,30,60])
@pytest.mark.parametrize('color',['#00FF88','#FFE500','#00FFFF'])
def test_sample_frames_highlight_only_during_measured_speech(tmp_path,fps,color):
    """Decode targeted RGB frames; dark background cannot masquerade as highlights."""
    path=tmp_path/'captions.ass';video=tmp_path/'sample.mp4'
    # Keep words in one readable phrase across the short silent gap.
    transcript={'segments':[{'words':[dict(word=' Hello',start=.1,end=.4),dict(word=' again',start=.7,end=1.1)]}]}
    assert cr.generate(transcript,0,1.4,path,270,480,preset='clean-podcast',highlight_color=color,effect='none')
    safe=_escape_ffmpeg_filter_value(str(path))
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
        f'color=c=0x223344:s=270x480:r={fps}:d=1.4','-vf',f"ass=filename='{safe}'",
        '-c:v','libx264','-threads','1','-preset','ultrafast',str(video)],check=True,capture_output=True,timeout=20)
    def sample(time):
        png=tmp_path/f'{time}.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(time),'-i',str(video),'-frames:v','1',str(png)],check=True,capture_output=True,timeout=10)
        from PIL import Image
        image=np.asarray(Image.open(png).convert('RGB')).astype(int)
        r,g,b=image[:,:,0],image[:,:,1],image[:,:,2]
        mask=(g>130)&(g-r>65) if color=='#00FF88' else ((r>150)&(g>150)&(g-b>65) if color=='#FFE500' else (g>130)&(b>130)&(g-r>65))
        return mask
    during=sample(.25);gap=sample(.52);after=sample(1.25)
    assert during.sum()>8
    assert gap.sum()==0 and after.sum()==0
    ys,xs=np.where(during)
    assert min(ys)>480*.12 and max(ys)<480*.80 and min(xs)>0 and max(xs)<270


def test_correction_saved_reopened_and_restyled_without_asr(caption_job,monkeypatch):
    import subtitles
    monkeypatch.setattr(subtitles,'transcribe_audio',lambda *a:pytest.fail('retained timing must avoid ASR'))
    body=dict(job_id='quality-job',clip_index=0,caption_preset='openshorts-dynamic',max_words=3,min_phrase_ms=600,line_spacing=1.4,
        words=[dict(text='Corrected!',startMs=100,endMs=700,aligned=True,emphasis=True)])
    response=request('POST','/api/subtitle',json=body)
    assert response.status_code==200,response.text
    data=request('GET','/api/clip/quality-job/0/transcript').json()
    assert data['captions'][0]['text']=='Corrected!' and data['captions'][0]['emphasis']
    assert data['captionSettings']['max_words']==3 and data['captionSettings']['line_spacing']==1.4
    response=request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,caption_preset='minimal'))
    assert response.status_code==200,response.text
    assert request('GET','/api/clip/quality-job/0/transcript').json()['captions'][0]['text']=='Corrected!'


def test_rendered_preview_does_not_publish_or_modify_clip(caption_job):
    before=caption_job['meta'].read_bytes();original=caption_job['video'].read_bytes()
    response=request('POST','/api/subtitle/preview',json=dict(job_id='quality-job',clip_index=0,
        caption_preset='creator-bold',effect='reveal',max_words=2,min_phrase_ms=600,line_spacing=1.3))
    assert response.status_code==200,response.text
    assert response.json()['quality_report']['accepted'] and 'caption_preview_0.mp4' in response.json()['video_url']
    assert caption_job['meta'].read_bytes()==before and caption_job['video'].read_bytes()==original


def test_caption_input_limits_and_empty_edits(caption_job):
    base=dict(job_id='quality-job',clip_index=0,caption_preset='minimal')
    for field,value in [('max_words',13),('min_phrase_ms',0),('line_spacing',2)]:
        assert request('POST','/api/subtitle',json={**base,field:value}).status_code==422
    assert request('POST','/api/subtitle',json={**base,'words':[]}).status_code==422
    assert request('GET','/api/clip/quality-job/-1/transcript').status_code==404


def test_dubbed_corrections_skip_asr_and_uncached_preview_is_explicit(caption_job,monkeypatch):
    import subtitles
    translated=caption_job['directory']/'translated_es_example_clip_1.mp4'
    shutil.copy(caption_job['video'],translated)
    data=json.loads(caption_job['meta'].read_text());data['shorts'][0]['video_url']='/videos/quality-job/'+translated.name
    caption_job['meta'].write_text(json.dumps(data))
    caption_job['record']['result']['clips'][0]['video_url']=data['shorts'][0]['video_url']
    base=dict(job_id='quality-job',clip_index=0,caption_preset='minimal')
    assert request('GET','/api/clip/quality-job/0/transcript').json()['audioAlignmentNeeded']
    assert request('POST','/api/subtitle/preview',json=base).status_code==409
    monkeypatch.setattr(subtitles,'transcribe_audio',lambda *a:pytest.fail('explicit corrections override ASR'))
    response=request('POST','/api/subtitle',json={**base,'words':[dict(text='Hola!',startMs=100,endMs=700,aligned=True)]})
    assert response.status_code==200,response.text
    assert request('GET','/api/clip/quality-job/0/transcript').json()['captions'][0]['text']=='Hola!'


def test_caption_replacement_preserves_directed_headline(caption_job,monkeypatch):
    import hook_layer
    original='subtitled_123_example_clip_1.mp4'
    shutil.copy(caption_job['video'],caption_job['directory']/original)
    data=json.loads(caption_job['meta'].read_text())
    data['shorts'][0].update(video_url='/videos/quality-job/'+original,
        auto_hook=dict(text='Hello, world!',start_seconds=0,duration_seconds=1,style='outline',animation='fade',y=.06))
    caption_job['meta'].write_text(json.dumps(data))
    caption_job['record']['result']['clips'][0]['video_url']='/videos/quality-job/'+original
    calls=[]
    def render(source,destination,layer):
        calls.append(layer);shutil.copy(source,destination)
    monkeypatch.setattr(hook_layer,'render',render)
    response=request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,caption_preset='minimal'))
    assert response.status_code==200,response.text
    assert len(calls)==1 and calls[0]['text']=='Hello, world!'
    assert '_hooked_' in response.json()['new_video_url']
    assert json.loads(caption_job['meta'].read_text())['shorts'][0]['auto_hook']==data['shorts'][0]['auto_hook']


def test_missing_clean_clip_cannot_stack_captions(caption_job):
    original='subtitled_123_missing.mp4'
    shutil.copy(caption_job['video'],caption_job['directory']/original)
    data=json.loads(caption_job['meta'].read_text());data['shorts'][0]['video_url']='/videos/quality-job/'+original
    caption_job['meta'].write_text(json.dumps(data))
    caption_job['record']['result']['clips'][0]['video_url']=data['shorts'][0]['video_url']
    assert request('POST','/api/subtitle',json=dict(job_id='quality-job',clip_index=0,caption_preset='minimal')).status_code==409


def test_real_container_delayed_audio_clock(tmp_path):
    media=tmp_path/'delayed.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=64x36:r=24:d=1',
        '-itsoffset','0.25','-f','lavfi','-i','sine=frequency=440:duration=0.5',
        '-c:v','libx264','-threads','1','-c:a','aac',str(media)],check=True,capture_output=True,timeout=15)
    anchored=tb._anchor_audio_clock(media,speech())
    # AAC priming changes the exact offset; measure it, never assume .25 exactly.
    assert .20<anchored['audio_offset_seconds']<.26
    assert anchored['segments'][0]['words'][0]['start']==pytest.approx(.1+anchored['audio_offset_seconds'])


def test_dubbed_alignment_is_reused_for_style_changes(caption_job,monkeypatch):
    import subtitles
    translated=caption_job['directory']/'translated_es_example_clip_1.mp4'
    shutil.copy(caption_job['video'],translated)
    data=json.loads(caption_job['meta'].read_text());data['shorts'][0]['video_url']='/videos/quality-job/'+translated.name
    caption_job['meta'].write_text(json.dumps(data))
    caption_job['record']['result']['clips'][0]['video_url']=data['shorts'][0]['video_url']
    calls=[]
    def transcribe(path):calls.append(path);return speech()
    monkeypatch.setattr(subtitles,'transcribe_audio',transcribe)
    monkeypatch.setattr(tb,'release_models',lambda:None)
    base=dict(job_id='quality-job',clip_index=0,caption_preset='minimal')
    assert request('POST','/api/subtitle',json=base).status_code==200
    assert request('GET','/api/clip/quality-job/0/transcript').json()['alignmentBasis']=='final-audio-asr'
    assert request('POST','/api/subtitle',json={**base,'caption_preset':'creator-bold'}).status_code==200
    assert len(calls)==1


def test_changed_base_media_invalidates_saved_alignment(caption_job):
    base=dict(job_id='quality-job',clip_index=0,caption_preset='minimal',
        words=[dict(text='Corrected!',startMs=100,endMs=700,aligned=True)])
    assert request('POST','/api/subtitle',json=base).status_code==200
    caption_job['video'].write_bytes(b'changed media')
    assert request('GET','/api/clip/quality-job/0/transcript').json()['captions'][0]['text']=='Hello,'


def test_malformed_saved_track_uses_original_timing(caption_job):
    base=dict(job_id='quality-job',clip_index=0,caption_preset='minimal')
    assert request('POST','/api/subtitle',json=base).status_code==200
    data=json.loads(caption_job['meta'].read_text());data['shorts'][0]['caption_track']['words']=[{'text':'broken'}]
    caption_job['meta'].write_text(json.dumps(data))
    assert request('GET','/api/clip/quality-job/0/transcript').json()['captions'][0]['text']=='Hello,'
