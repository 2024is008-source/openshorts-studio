"""TASK-006: conservative source-clock decisions and real gapless A/V assembly."""
import copy
import json
from pathlib import Path
import subprocess
import asyncio

import numpy as np
import pytest

import pacing as p
import clip_selection as cs
import recut
from generation_options import pacing_options,clip_target_options,RESUME_OPTIONS
from test_story_selection import segment
from test_export_quality_api import job,request  # noqa: F401
from test_export_quality import real_clip  # noqa: F401
from test_editing_director import signals  # noqa: F401


def speech():
    return {'segments':[segment(1,3,'Here is the complete setup.','A'),
        segment(7,10,'Here is the complete result.','A')]}


def cfg(mode='balanced',trim=False,allow=False):
    return dict(mode=mode,trim_silence=trim,allow_incomplete=allow)


def measured(a,b):return dict(available=True,intervals=[[3,7]])


@pytest.mark.parametrize('mode',list(p.MODES))
def test_modes_align_to_complete_speech_without_filling_target(mode):
    t=speech();before=copy.deepcopy(t)
    report=p.plan(dict(start=1.5,end=9),t,12,cfg(mode))
    assert report['segments'][0]['start']<=1 and report['segments'][-1]['end']>=10
    assert report['validation']['complete_ending'] and report['output_duration']<12
    assert t==before


def test_fast_speech_does_not_cut_words_or_drop_punctuation():
    transcript={'segments':[segment(0,1,'A very quick complete sentence.','A'),segment(1.1,2,'Another complete thought.','A')]}
    report=p.plan(dict(start=.4,end=1.8),transcript,2,cfg('fast'))
    assert report['segments']==[dict(start=0.,end=2.)]
    assert recut.virtual_transcript(transcript,report['segments'])['segments'][0]['words'][-1]['word'].endswith('.')


def test_multiple_overlapping_speakers_are_fully_retained():
    transcript={'segments':[segment(0,5,'Can you explain what happened?','A'),segment(4,8,'Yes we fixed the motor.','B'),
        segment(7,11,'And the boat reached safety.','A')]}
    report=p.plan(dict(start=1,end=7),transcript,12,cfg())
    assert report['segments'][0]['start']==0 and report['segments'][0]['end']>=11


def test_incomplete_ending_extends_to_available_complete_thought():
    transcript={'segments':[segment(0,5,'The motor would not start','A'),segment(6,10,'Then we repaired it.','A')]}
    report=p.plan(dict(start=0,end=4),transcript,12,cfg())
    assert report['segments'][-1]['end']>=10


def test_abrupt_source_ending_is_rejected_unless_explicitly_allowed():
    transcript={'segments':[segment(0,8,'We were about to','A')]}
    with pytest.raises(ValueError,match='Abrupt ending'):p.plan(dict(start=0,end=8),transcript,8,cfg())
    report=p.plan(dict(start=0,end=8),transcript,8,cfg(allow=True))
    assert not report['validation']['complete_ending'] and 'intentionally allowed' in report['warnings'][0]


def test_scene_alignment_only_in_speech_free_margins():
    report=p.plan(dict(start=1,end=10),speech(),12,cfg(),scene_cuts=[.7,2,10.5])
    assert report['segments']==[dict(start=.7,end=10.5)]


def test_only_measured_same_speaker_gap_can_be_shortened():
    report=p.plan(dict(start=1,end=10),speech(),12,cfg('fast',True),measure=measured)
    assert report['segments']==[dict(start=.9,end=3.2),dict(start=6.8,end=10.2)]
    assert report['removed_silence']==[dict(start=3.2,end=6.8,reason='Measured silence between complete same-speaker sentences.')]
    assert report['transition']=='straight' and report['audio_join_fade_ms']==8


@pytest.mark.parametrize('mode',['emotional','balanced','educational'])
def test_pacing_styles_keep_increasing_pause_space(mode):
    report=p.plan(dict(start=1,end=10),speech(),12,cfg(mode,True),measure=measured)
    removed=sum(r['end']-r['start'] for r in report['removed_silence'])
    assert removed==pytest.approx({'emotional':0,'balanced':3.2,'educational':2.8}[mode])


@pytest.mark.parametrize('kind',['unavailable','not_silent','unknown_speaker','different_speaker','scene_cut'])
def test_uncertain_pauses_and_speaker_exchanges_are_preserved(kind):
    transcript=speech();cuts=[]
    measurement=measured
    if kind=='unavailable':measurement=lambda a,b:dict(available=False,intervals=[])
    if kind=='not_silent':measurement=lambda a,b:dict(available=True,intervals=[])
    if kind=='unknown_speaker':transcript['segments'][1]['speaker']=None
    if kind=='different_speaker':transcript['segments'][1]['speaker']='B'
    if kind=='scene_cut':cuts=[5]
    report=p.plan(dict(start=1,end=10),transcript,12,cfg('fast',True),measure=measurement,scene_cuts=cuts)
    assert not report['removed_silence'] and len(report['segments'])==1


def test_reaction_shot_and_laughter_are_not_removed_as_silence():
    reaction=dict(start=0,end=11,preserve_context=True,story=dict(evidence=[
        dict(id='reaction',start=3,end=7,channel='visual',description='The listener raises both hands.')]))
    report=p.plan(dict(start=1,end=10),speech(),12,cfg('fast',True),moments=[reaction],measure=measured)
    assert not report['removed_silence']


def test_known_connected_setup_and_payoff_extend_clip():
    from test_multimodal_story_detection import candidate,source
    full=candidate();full['start']=1;full['end']=27
    shortened=copy.deepcopy(full);shortened['end']=17
    shortened['story']['evidence']=shortened['story']['evidence'][:2]
    shortened['story']['beats']=shortened['story']['beats'][:2]
    report=p.plan(shortened,source(),30,cfg(),moments=[full])
    assert report['segments'][-1]['end']>=27


def test_unrelated_later_payoff_is_not_attached():
    other=dict(start=1,end=28,story=dict(mode='challenge',evidence=[dict(id='other',start=20,end=25,channel='visual',description='A trophy is visible.')],
        beats=[dict(role='outcome',evidence_ids=['other'])]))
    report=p.plan(dict(start=1,end=3),speech(),30,cfg(),moments=[other])
    assert report['segments'][-1]['end']<7


def test_repetition_is_identified_but_never_deleted():
    transcript={'segments':[segment(0,3,'We finally repaired the motor.','A'),segment(4,7,'We finally repaired the motor.','A')]}
    report=p.plan(dict(start=0,end=7),transcript,8,cfg())
    assert len(report['repeated_dialogue'])==1 and report['repeated_dialogue'][0]['action']=='preserved_for_review'
    assert report['segments'][0]['end']>=7


@pytest.mark.parametrize('duration',[2,4,8])
def test_short_source_remains_usable_with_longer_target(duration):
    transcript={'segments':[segment(.1,duration-.1,'A short complete thought.','A')]}
    candidates=cs.fallback_story_candidates(transcript,duration,target=30)
    selected=cs.select_story_candidates(candidates,transcript,duration,target=30)
    assert selected and selected[0]['end']<=duration
    report=p.plan(selected[0],transcript,duration,cfg())
    assert report['output_duration']<=duration


def test_no_speech_does_not_claim_verified_sentence_completion():
    report=p.plan(dict(start=0,end=2),None,2,cfg())
    assert report['validation']['complete_ending'] is None


def test_no_silence_decode_when_no_internal_edit_is_requested():
    report=p.plan(dict(start=1,end=10),speech(),12,cfg(),measure=lambda *a:pytest.fail('no audio decode needed'))
    assert not report['removed_silence']


@pytest.mark.parametrize('target',[15,30,45,60,37])
def test_targets_stay_soft_and_pacing_settings_are_recoverable(target):
    assert float(clip_target_options(target)['CLIP_TARGET_SECONDS'])==target
    assert set(pacing_options('fast',True))<=RESUME_OPTIONS
    with pytest.raises(ValueError):pacing_options('unsafe',True)


def test_segment_only_timing_survives_paced_recipes():
    transcript={'language':'en','segments':[dict(start=1,end=3,text='First complete thought.',speaker='A'),dict(start=7,end=10,text='Second complete thought.',speaker='A')]}
    report=p.plan(dict(start=1,end=10),transcript,12,cfg('fast',True),measure=measured)
    remapped=recut.virtual_transcript(transcript,report['segments'])
    assert [s['text'] for s in remapped['segments']]==['First complete thought.','Second complete thought.']
    assert all(not s['words'] for s in remapped['segments'])
    assert remapped['segments'][1]['start']==pytest.approx(2.5)


def test_failed_candidates_are_reported_without_publishing_them(tmp_path):
    t={'segments':[segment(0,4,'An unfinished thought','A')]}
    accepted,rejected=p.prepare_clips([dict(start=0,end=4)],t,4,tmp_path/'missing.mp4',tmp_path)
    assert accepted==[] and 'Abrupt ending' in rejected[0]['reason']


@pytest.fixture
def silence_media(tmp_path):
    video=tmp_path/'quiet.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=96x160:r=24:d=5',
        '-f','lavfi','-i','sine=frequency=440:duration=5','-af',"volume=enable='between(t,1,4)':volume=0",
        '-c:v','libx264','-threads','1','-c:a','aac',str(video)],check=True,capture_output=True,timeout=20)
    return video


def test_real_silence_detection_cached_and_invalidated(silence_media,tmp_path,monkeypatch):
    result=p.detect_silence(silence_media,0,5,tmp_path)
    assert result['available'] and any(a<=1.1 and b>=3.9 for a,b in result['intervals'])
    original=p.subprocess.run
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:pytest.fail('must reuse measured cache'))
    assert p.detect_silence(silence_media,0,5,tmp_path)['cache_hit']
    monkeypatch.setattr(p.subprocess,'run',original)
    assert not p.detect_silence(tmp_path/'missing.mp4',0,5,tmp_path)['available']


def test_real_gapless_audio_concat_preserves_frames_and_duration(silence_media,tmp_path,monkeypatch):
    monkeypatch.setenv('FFMPEG_ENCODER','x264')
    output=tmp_path/'joined.mp4';segments=[dict(start=0,end=1),dict(start=4,end=5)]
    recut.run_cut_concat(str(silence_media),segments,str(output),str(tmp_path),continuous_audio=True)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)],timeout=10))
    video=next(s for s in info['streams'] if s['codec_type']=='video');audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'])==(96,160)
    assert abs(float(video['duration'])-2)<.05 and abs(float(audio['duration'])-2)<.06
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vn','-f','s16le','-ac','1','-ar','8000','-'],timeout=15)
    samples=np.frombuffer(raw,dtype=np.int16).astype(float)
    # Energy survives immediately on both sides of the join; no padded AAC part gap.
    for a,b in [(.95,.985),(1.015,1.05)]:assert np.sqrt(np.mean(samples[int(a*8000):int(b*8000)]**2))>100
    frames=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vf','fps=4,scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],timeout=15)
    pixels=np.frombuffer(frames,dtype=np.uint8).reshape(-1,3)
    assert len(pixels)==8 and all(pixel[2]>150 for pixel in pixels)


def test_timed_out_measurement_preserves_source(monkeypatch,tmp_path):
    file=tmp_path/'source';file.touch()
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('ffmpeg',45)))
    assert p.detect_silence(file,0,10,tmp_path)==dict(available=False,intervals=[])


def test_connected_reaction_after_speech_is_kept():
    transcript=speech()
    evidence=[dict(id='setup',start=1,end=3,channel='transcript',quote=transcript['segments'][0]['text']),
        dict(id='reaction',start=10,end=12,channel='visual',description='The listener raises both hands.')]
    moment=dict(start=1,end=12,story=dict(evidence=evidence,beats=[dict(role='reaction',evidence_ids=['reaction'])]))
    report=p.plan(dict(start=1,end=10),transcript,14,cfg(),moments=[moment])
    assert report['segments'][-1]['end']>=12


@pytest.mark.parametrize('mode',['emotional','comedy'])
def test_known_emotional_or_comedy_story_preserves_meaningful_pause(mode):
    transcript=speech()
    clip=dict(start=1,end=10,story=dict(mode=mode,evidence=[
        dict(id=str(i),start=s['start'],end=s['end'],channel='transcript',quote=s['text']) for i,s in enumerate(transcript['segments'])]))
    assert not p.plan(clip,transcript,12,cfg('fast',True),measure=measured)['removed_silence']


def test_out_of_order_source_recipe_is_rejected_not_silently_rewritten():
    clip=dict(start=0,end=5,recipe=dict(segments=[dict(start=7,end=10),dict(start=1,end=3)]))
    with pytest.raises(ValueError,match='chronological'):p.plan(clip,speech(),12,cfg())


def test_single_pass_concat_normalizes_assembled_audio_once(monkeypatch):
    monkeypatch.setenv('AUDIO_MASTERING','0')  # legacy normalization remains available
    monkeypatch.setenv('FFMPEG_ENCODER','x264');monkeypatch.setenv('AUDIO_NORMALIZE','1')
    command=recut.continuous_cut_command('source.mp4',[dict(start=1,end=3),dict(start=7,end=10)],'output.mp4')
    graph=command[command.index('-filter_complex')+1]
    assert '-af' not in command and graph.count('loudnorm=')==1
    assert 'afade=t=in' in graph and 'afade=t=out' in graph


def test_prepared_recipe_reuses_exact_segments_for_render_and_preview(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'detect_silence',lambda *a:measured(0,12))
    original=dict(start=1,end=10,story_report=dict(evidence=[],limitations=[]))
    clips,rejected=p.prepare_clips([original],speech(),12,'source',tmp_path,config=cfg('fast',True))
    assert not rejected
    assert clips[0]['recipe']['segments']==clips[0]['pacing_report']['segments']
    assert clips[0]['recipe']['pacing_audio_continuity']
    assert clips[0]['end']==recut.total_duration(clips[0]['recipe']['segments'])
    assert 'recipe' not in original


def test_delayed_source_audio_keeps_its_picture_offset(tmp_path,monkeypatch):
    monkeypatch.setenv('FFMPEG_ENCODER','x264');monkeypatch.setenv('AUDIO_NORMALIZE','0')
    source=tmp_path/'delayed.mp4';output=tmp_path/'joined.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=96x160:r=24:d=2',
        '-itsoffset','0.25','-f','lavfi','-i','sine=frequency=440:duration=1.75',
        '-c:v','libx264','-threads','1','-c:a','aac',str(source)],check=True,capture_output=True,timeout=15)
    recut.run_cut_concat(str(source),[dict(start=0,end=1),dict(start=1,end=2)],str(output),str(tmp_path),continuous_audio=True)
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vn','-ac','1','-ar','8000','-f','s16le','-'],timeout=15)
    samples=np.frombuffer(raw,dtype=np.int16).astype(float)
    rms=lambda a,b:np.sqrt(np.mean(samples[int(a*8000):int(b*8000)]**2))
    assert rms(.05,.18)<5 and rms(.35,.5)>100 and rms(1.05,1.15)>100


def test_generation_api_rejects_invalid_pacing_before_processing(monkeypatch):
    import app
    async def key(_):return 'test-only-key'
    monkeypatch.setattr(app,'resolve_gemini',key)
    response=request('POST','/api/process',json={'pacing_mode':'unknown'})
    assert response.status_code==400 and 'pacing_mode' in response.text


def test_director_saves_audio_join_decision_for_preview(signals):
    from test_editing_director import compile
    signals['pacing_audio_continuity']=True
    assert compile(signals)['audio']['continuous_source_audio']


def test_paced_editor_preview_and_final_keep_continuity_recipe(job,monkeypatch):
    import httpx
    import app
    import timeline_api
    monkeypatch.setattr(app,'_archive_clip_edit_bg',lambda *a:None)
    data=json.loads(job['meta'].read_text())
    data['shorts'][0]['recipe']=dict(v=1,segments=[dict(start=0,end=1),dict(start=1,end=2)],
        canonical_range=dict(start=0,end=2),source_montage=True,pacing_audio_continuity=True)
    job['meta'].write_text(json.dumps(data))
    base='/api/clip/quality-job/0/editor'
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            draft=(await client.get(base)).json()['project']
            draft['edits']['style']['enabled']=False
            assert (await client.put(base,json={'revision':0,'edits':draft['edits']})).status_code==200
            for mode in ('preview','final'):
                response=await client.post(base+'/run',json={'revision':1,'mode':mode})
                assert response.status_code==200,response.text
                await asyncio.wait_for(timeline_api._active[('quality-job',0)]['task'],45)
                project=(await client.get(base)).json()['project']
                assert project['status'] in ('preview_ready','completed'),project
                assert project['result']['recipe']['pacing_audio_continuity']
                assert project['result']['quality_report']['accepted']
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['scene','speaker','long_gap'])
def test_abrupt_ending_does_not_attach_an_unrelated_following_scene(change):
    transcript={'segments':[segment(0,5,'An unfinished thought','A'),segment(6,10,'A different complete statement.','A')]}
    cuts=[]
    if change=='scene':cuts=[5.5]
    if change=='speaker':transcript['segments'][1]['speaker']='B'
    if change=='long_gap':transcript['segments'][1]=segment(8,12,'A different complete statement.','A')
    with pytest.raises(ValueError,match='Abrupt ending'):p.plan(dict(start=0,end=5),transcript,14,cfg(),scene_cuts=cuts)


def test_important_quiet_visual_before_speech_is_not_trimmed():
    transcript=speech()
    evidence=[dict(id='object',start=.2,end=.8,channel='visual',description='The challenge rules are visible on a sign.'),
        dict(id='speech',start=1,end=3,channel='transcript',quote=transcript['segments'][0]['text'])]
    story=dict(evidence=evidence)
    report=p.plan(dict(start=0,end=10,story=story),transcript,12,cfg('fast'),moments=[dict(start=0,end=10,story=story)])
    assert report['segments'][0]['start']<=.2
