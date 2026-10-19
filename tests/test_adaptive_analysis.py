"""No-credit adaptive contracts. Provider outputs are synthetic test data only."""
import copy
import json
import math
import threading
from pathlib import Path
from types import SimpleNamespace as NS
import httpx
import pytest
from adaptive_analysis import candidates,media_index,transcript,pipeline
from adaptive_analysis.runtime import Cache,Ledger,DEFAULTS,BudgetExceeded,Cancelled,configuration,digest
from adaptive_analysis.gemini import Operation,scope
from test_gemini_chapter_compatibility import provider  # noqa:F401


def config(category='podcast-education',**kwargs):
    return dict(DEFAULTS['balanced'],mode='balanced',category=category,cost_ceiling=None,input_price=None,output_price=None,**kwargs)


def index(duration=80,active=False,speech=True):
    return dict(version=1,duration=duration,units=[dict(id='u0',start=5.,end=15.,text='Try small steps. Practice improves your skill.',complete=True,speaker='a')] if speech else [],
        scenes=[dict(start=0,end=duration)],motion=[dict(start=40.,end=40.5,mean_change=.1,peak_change=.8,frames=12)] if active else [],
        audio=[],speaker_turns=[],faces=None,crop_paths=None,subjects=None)


def chapter(need='none',category='podcast-education'):
    return dict(category=category,summary_unit_ids=['u0'],moments=[dict(start=5.,end=15.,unit_ids=['u0'],quote='Try small steps.',title='Practice improves skill',role='takeaway',importance=.8,story_complete=True,visual_need=need)])


def observed(seconds,event='A player moves across the field',confidence=.9,shot='action'):
    return dict(chapter_summary='Source observation.',moments=[],scene_cuts=[],scene_observations=[dict(start=0.,end=seconds,shot_type=shot,event=event,confidence=confidence,layout_intent='preserve_scene',layout_evidence='Action spans the source frame',preserve_context=True,editing_cues=[])])


@pytest.fixture
def run(monkeypatch,tmp_path):
    import adaptive_analysis.gemini as adapter
    source=tmp_path/'source.mp4';source.write_bytes(b'synthetic source identity')
    monkeypatch.setenv('OPENSHORTS_ANALYSIS_CACHE',str(tmp_path/'cache'))
    monkeypatch.setenv('OPENSHORTS_LEARNING_DIR',str(tmp_path/'learning'))
    monkeypatch.setenv('GENERATION_MODE','clips')
    monkeypatch.setenv('GEMINI_MODEL','fixture-model');monkeypatch.setenv('GEMINI_MODEL_VISION','fixture-model')
    calls=[];state=dict(index=index(),chapter=chapter(),event='Visible presenter',confidence=.9,fail=None)
    class FakeGateway:
        def __init__(self,model,ledger):self.ledger=ledger
        def text(self,prompt,schema,identity,kind='text',images=()):
            self.ledger.request(identity,kind,max(1,len(prompt)//3));calls.append((kind,prompt))
            if schema is transcript.NarrativeMap:return dict(ordered_candidate_ids=[],related_groups=[])
            if kind=='visual':
                assert len(images)==3
                return observed(15,'Visible presenter',shot='single_subject')
            return copy.deepcopy(state['chapter'])
        def video(self,proxy,prompt,seconds,identity,fps=2):
            self.ledger.request(identity,'visual',int(seconds*fps*128),seconds);calls.append(('video',seconds))
            if state['fail']:raise state['fail']
            return observed(seconds,state['event'],state['confidence'])
    monkeypatch.setattr(adapter,'Gateway',FakeGateway)
    def encode(args,**kwargs):Path(args[-1]).write_bytes(b'synthetic encoded media');return NS(returncode=0)
    monkeypatch.setattr(pipeline.subprocess,'run',encode)
    def analyze(cfg=None,cancel=None):
        return pipeline.analyze(source,None,state['index']['duration'],tmp_path/'out',cfg=cfg or config(),cancel=cancel,index_builder=lambda *a,**k:copy.deepcopy(state['index']))
    return NS(analyze=analyze,state=state,calls=calls,path=tmp_path,source=source)


def test_transcript_precedes_visual_and_reuses_completed_work(run):
    run.state.update(index=index(active=True),chapter=chapter('video'))
    first=run.analyze()
    assert run.calls[0][0]=='text' and any(k=='video' for k,_ in run.calls)
    assert first['moments'] and all(m['verification_status']=='model_observed' for m in first['moments'])
    count=len(run.calls);second=run.analyze()
    assert len(run.calls)==count and second['metrics']['cache_hits']>=2
    assert second['metrics']['requests']==dict(text=0,visual=0)


@pytest.mark.parametrize('category',['podcast-motivation','podcast-education','podcast-comedy','challenge','cricket','football','general'])
def test_categories_and_silent_independent_action(run,category):
    run.state.update(index=index(active=True,speech=False))
    value=run.analyze(config(category))
    assert value['moments'] and value['moments'][0]['origins']==['local_visual']
    assert not any(k=='text' for k,_ in run.calls)
    assert value['moments'][0]['layout_intent']=='preserve_scene'


def test_budget_zero_never_encodes_or_sends_visual(run,monkeypatch):
    run.state.update(index=index(active=True),chapter=chapter('video'))
    monkeypatch.setattr(pipeline.subprocess,'run',lambda *a,**kw:pytest.fail('No encoding after visual budget exhausted'))
    cfg=config();cfg['visual_requests']=0
    value=run.analyze(cfg)
    assert not value['moments'] and value['verification_receipts'][0]['status']=='budget_exhausted'
    assert not any(k=='video' for k,_ in run.calls)


def test_false_commentary_and_uncertain_visual_outcome_are_withheld(run):
    run.state.update(chapter=chapter('none','football'),event='Unknown outcome: more context is needed',index=index(active=True))
    value=run.analyze(config('football'))
    assert not value['moments']
    assert any('confident' in u for row in value['candidates'] for u in row['uncertainty'])


def test_context_expansion_shares_retry_budget_and_stays_bounded(run):
    run.state.update(chapter=chapter('video'),event='More context is needed',confidence=.2)
    cfg=config();cfg['retries']=1
    value=run.analyze(cfg)
    assert not value['moments'] and value['verification_receipts'][0]['status']=='needs_context'
    assert len([r for r in run.calls if r[0]=='video'])==2
    assert value['metrics']['retry_count']==1 and value['metrics']['video_seconds']==38
    assert value['metrics']['unique_operation_video_seconds']==23


def test_same_identity_legacy_chapter_is_reused_without_new_video(run):
    import story_director as sd
    run.state['chapter']=chapter('video')
    output=run.path/'out';output.mkdir()
    chapter_data=dict(observed(80),offset=0,end=80)
    (output/'story_analysis.json').write_text(json.dumps(dict(source_key=sd.source_analysis_key(run.source,None,80,'fixture-model'),chapters=[chapter_data])))
    value=run.analyze()
    assert value['moments'] and value['verification_receipts'][0]['status']=='retained_chapter'
    assert not any(k=='video' for k,_ in run.calls)
    run.source.write_bytes(b'changed legacy source')
    run.analyze();assert any(k=='video' for k,_ in run.calls)


def test_model_visual_description_replaces_speculative_transcript_title(run):
    run.state.update(chapter=chapter('video','football'),event='A player approaches the penalty area')
    run.state['chapter']['moments'][0]['title']='They won the championship with a goal!'
    value=run.analyze(config('football'))
    assert 'championship' not in value['moments'][0]['video_title_for_youtube_short']
    assert not value['moments'][0]['story_complete']


def test_missing_speech_and_no_activity_do_not_fabricate_clips(run):
    run.state['index']=index(speech=False)
    value=run.analyze()
    assert not value['moments'] and not run.calls


def test_text_only_safety_policy_has_no_visual_authority(run):
    value=run.analyze()
    assert value['moments'][0]['verification_status']=='text_grounded'
    assert value['scene_observations'][0]['confidence']==0
    assert value['scene_observations'][0]['editing_cues']==[]
    assert value['metrics']['video_seconds']==0


def test_summary_copy_uses_retained_source_instead_of_unverified_prize(run,monkeypatch):
    import story_director as sd
    monkeypatch.setenv('GENERATION_MODE','highlights')
    monkeypatch.setattr(sd,'plan_summary',lambda *a:dict(shorts=[dict(start=0,end=10,recipe={'segments':[dict(start=5,end=15)]},video_title_for_youtube_short='Won a million-dollar prize!',viral_hook_text='Million dollar winner')]))
    value=run.analyze();short=value['summary_shorts'][0]
    assert short['video_title_for_youtube_short']=='Try small steps.' and short['viral_hook_text']=='Try small steps.'
    assert 'million' not in json.dumps(short).lower()


def test_targeted_stills_are_separate_from_motion_verification(run):
    run.state['chapter']=chapter('frames')
    value=run.analyze()
    assert value['moments'] and value['verification_receipts'][0]['kind']=='frames'
    assert value['metrics']['video_seconds']==0 and value['metrics']['requests']['visual']==1


def test_partial_failure_resume_keeps_text_cache_and_retries_visual_only(run):
    run.state.update(chapter=chapter('video'),fail=httpx.ReadTimeout(''))
    first=run.analyze();assert not first['moments']
    count=len([r for r in run.calls if r[0]=='text'])
    run.state['fail']=None;second=run.analyze()
    assert second['moments'] and len([r for r in run.calls if r[0]=='text'])==count
    assert not (run.path/'out'/'analysis_failure.json').exists()


def test_candidates_beyond_inspected_context_are_not_truncated_into_claims(run):
    run.state.update(index=index(duration=120),chapter=chapter('video'))
    run.state['chapter']['moments'][0].update(start=0,end=100)
    value=run.analyze();assert not value['moments']
    assert any('exceeds' in u for r in value['candidates'] for u in r['uncertainty'])


def test_cancellation_and_changed_source_invalidate_reuse(run):
    event=threading.Event();event.set()
    with pytest.raises(Cancelled):run.analyze(cancel=event)
    assert not run.calls
    run.analyze();count=len(run.calls);run.source.write_bytes(b'different source')
    run.analyze();assert len(run.calls)>count


def test_knowledge_records_are_unreviewed_and_exclude_speech(run):
    from learning.database import Store
    run.analyze();store=Store(run.path/'learning');records=store.rows('editing_decisions')
    assert records and all(r['status']=='unreviewed' for r in records)
    assert 'Try small steps' not in json.dumps(records)
    assert not store.rows('reviewed_examples') and not store.rows('model_registry')


@pytest.mark.parametrize('bounds',[(float('nan'),8),(-1,5),(5,4),(0,float('inf')),(0,90)])
def test_invalid_candidate_timestamps_are_rejected(bounds):
    assert candidates.fuse([dict(start=bounds[0],end=bounds[1])],80)==[]


def test_quote_grounding_rejects_fabrication_and_missing_units():
    value=chapter();value['moments'][0]['quote']='You won a million dollars.'
    assert transcript.ground(value,index()['units'],80)==[]
    value=chapter();value['moments'][0]['unit_ids']=['missing']
    assert transcript.ground(value,index()['units'],80)==[]


def test_incomplete_asr_does_not_receive_positive_completeness():
    units=index()['units'];units[0]['complete']=False
    assert not transcript.ground(chapter(),units,80)[0]['story_complete']


def test_oversized_asr_is_bounded_without_invented_word_timestamps():
    original=dict(index()['units'][0],text='word '*10000)
    groups=transcript.chapters([original])
    assert len(groups)>1 and all(sum(len(u['text']) for u in group)<=12000 for group in groups)
    assert all(u['start']==5 and u['end']==15 and not u['complete'] for group in groups for u in group)


def test_visual_discovery_is_independent_and_fusion_retains_provenance():
    visual=candidates.local_candidates(index(active=True,speech=False),'football')
    assert visual and visual[0]['title']=='Unverified visual activity'
    speech=dict(visual[0],origins=['transcript'],story_complete=True)
    fused=candidates.fuse(visual+[speech],80)
    assert len(fused)==1 and set(fused[0]['origins'])=={'local_visual','transcript'}
    assert not fused[0]['story_complete']


def test_budget_retry_transfer_and_cost_are_shared(tmp_path):
    cfg=config();cfg.update(retries=1,input_price=1.,output_price=1.,cost_ceiling=.01)
    ledger=Ledger(cfg,tmp_path/'m.json');ledger.request('a','visual',1000,10)
    ledger.transfer_retry('a')
    with pytest.raises(BudgetExceeded):ledger.request('a','visual',1000,10)
    assert ledger.video_seconds==10
    ledger.record_usage(dict(input_tokens=100000))
    with pytest.raises(BudgetExceeded):ledger.check()


@pytest.mark.parametrize('failure',[httpx.ReadTimeout(''),httpx.WriteTimeout('')])
def test_adaptive_transport_does_not_reset_operation_budget(provider,tmp_path,monkeypatch,failure):
    import story_director as sd
    monkeypatch.setattr(sd.time,'sleep',lambda _:None)
    media=tmp_path/'proxy.mp4';media.write_bytes(b'fixture')
    cfg=config();cfg['retries']=0;ledger=Ledger(cfg,tmp_path/'m.json')
    provider.answers[:]=[failure]
    with scope(Operation(ledger,digest('test'),8,100)):
        with pytest.raises(BudgetExceeded):sd._inspect(media,'Observe.','fixture-model')
    assert len(provider.calls)==1
    if isinstance(failure,httpx.WriteTimeout):assert not provider.uploaded


def test_429_does_not_rotate_adaptive_keys(provider,tmp_path,monkeypatch):
    import story_director as sd
    from google.genai.errors import ClientError
    monkeypatch.setattr(sd,'api_keys',lambda:['fixture-one','fixture-two'])
    provider.answers[:]=[ClientError(429,{'error':{'code':429,'message':'quota','status':'RESOURCE_EXHAUSTED'}})]
    media=tmp_path/'proxy.mp4';media.write_bytes(b'fixture')
    with scope(Operation(Ledger(config(),tmp_path/'m.json'),digest('test'),8,100)):
        with pytest.raises(ClientError):sd._inspect(media,'Observe.','fixture-model')
    assert len(provider.calls)==1


def test_adaptive_upload_reused_across_operations_for_same_key(provider,tmp_path):
    import story_director as sd
    media=tmp_path/'proxy.mp4'
    # Reuse/expiry concerns Files API media, above the bounded inline threshold.
    with media.open('wb') as file:file.truncate(6*1024*1024)
    ledger=Ledger(config(),tmp_path/'m.json')
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]*2
    for identity in ('one','two'):
        with scope(Operation(ledger,digest(identity),8,100)):
            sd._inspect(media,'Observe.','fixture-model')
    assert len(provider.uploaded)==1 and len(provider.calls)==2 and not provider.deleted
    raw=(tmp_path/'amce-upload-references.json').read_text()
    assert 'test-only-placeholder' not in raw


def test_expired_uploaded_reference_is_replaced_once(provider,tmp_path,monkeypatch):
    import story_director as sd
    from google.genai.errors import ClientError
    from google import genai
    media=tmp_path/'proxy.mp4'
    with media.open('wb') as file:file.truncate(6*1024*1024)
    ledger=Ledger(config(),tmp_path/'m.json');provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]*2
    with scope(Operation(ledger,digest('one'),8,100)):sd._inspect(media,'Observe.','fixture-model')
    client=genai.Client();original=client.files.get;calls=[]
    def get(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise ClientError(404,{'error':{'code':404,'message':'expired','status':'NOT_FOUND'}})
        return original(**kwargs)
    monkeypatch.setattr(client.files,'get',get)
    with scope(Operation(ledger,digest('two'),8,100)):sd._inspect(media,'Observe.','fixture-model')
    assert len(provider.uploaded)==2 and len(provider.calls)==2
    assert sum(ledger.transfer_retries.values())==1


def test_configuration_refuses_unpriced_monetary_limit(monkeypatch):
    monkeypatch.setenv('ANALYSIS_MODE','adaptive-economy');monkeypatch.setenv('AMCE_COST_CEILING','1')
    monkeypatch.delenv('AMCE_INPUT_PRICE',raising=False);monkeypatch.delenv('AMCE_OUTPUT_PRICE',raising=False)
    with pytest.raises(ValueError,match='requires'):configuration()


def test_adaptive_progress_native_contract(tmp_path):
    from test_native_home import engine,fixture
    from desktop.generation_review import progress,analysis_presentation
    e=engine(tmp_path);fixture(e)
    e.jobs['job-one'].update(status='processing',logs=['Preparing source','Transcribing 100%',
        'AMCE_PROGRESS '+json.dumps(dict(stage='story',completed=2,total=5,elapsed_seconds=3.5,cache_reuse=True,retry=False))])
    value=progress(e,'job-one');assert len(value['stages'])==12 and value['overall'] is None
    assert next(s for s in value['stages'] if s['id']=='category')['title']=='Detecting video category'
    stage=next(s for s in value['stages'] if s['id']=='story')
    assert stage['percent']==40 and stage['cache_reuse'] and stage['elapsed_seconds']==3.5
    result=analysis_presentation(dict(job_options={'ANALYSIS_MODE':'adaptive-balanced'},story_analysis={'moments':[{'verification_status':'text_grounded'}]}))
    assert not result['visual_available'] and 'Unsupported' in result['warning']


def test_cache_corruption_does_not_replace_valid_source_with_garbage(tmp_path):
    cache=Cache(tmp_path,{'sha256':'fixture'},'model',config());cache.write('text-story','id',chapter())
    assert cache.read('text-story','id')
    next(tmp_path.glob('*.json')).write_text('corrupt')
    assert cache.read('text-story','id') is None


def test_top_level_failure_redacts_provider_body(tmp_path,monkeypatch):
    import adaptive_analysis
    def broken(*args,**kwargs):raise ValueError('Bearer private-customer-body')
    monkeypatch.setattr(pipeline,'analyze',broken)
    with pytest.raises(RuntimeError) as failure:adaptive_analysis.analyze('source',None,1,tmp_path)
    assert 'private' not in str(failure.value)
    saved=json.loads((tmp_path/'analysis_failure.json').read_text())
    assert saved['adaptive'] and saved['error_type']=='ValueError' and 'private' not in json.dumps(saved)


def test_real_local_index_decodes_every_frame_on_cpu(tmp_path):
    import subprocess
    source=tmp_path/'short.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=2','-c:v','libx264','-threads','1',str(source)],check=True,capture_output=True,timeout=30)
    motion,resources=media_index.measure_motion(source,2)
    assert resources['decoded_frames']==60 and resources['retained_image_buffers']==2
    assert all(0<=r['start']<r['end']<=2 for r in motion)
    assert media_index.measure_audio(source,2)==[]
    ledger=Ledger(config(),tmp_path/'metrics.json');cache=Cache(tmp_path/'cache',media_index.identity(source),'fixture',config())
    built=media_index.build(source,None,2,cache,ledger)
    assert built['scenes'] and built['faces'] is None and built['resources']['decoded_frames']==60
    event=threading.Event();event.set()
    from scene_detection import _detect_pyscenedetect
    with pytest.raises(Cancelled):_detect_pyscenedetect(str(source),check=lambda:Ledger(config(),tmp_path/'cancel.json',event).check())
