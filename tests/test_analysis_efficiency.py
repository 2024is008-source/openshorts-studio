"""No-network regression checks for analysis latency and recovery contracts."""
import json
import threading
import time
from types import SimpleNamespace as NS
import httpx
import pytest
import story_director as sd
from test_gemini_chapter_compatibility import provider  # noqa: F401
from test_generation_review import engine,fixture
from desktop.generation_review import progress


@pytest.mark.parametrize('error',[httpx.ReadTimeout(''),httpx.WriteTimeout(''),httpx.ConnectError('')])
def test_empty_transport_messages_retry_same_video(provider,monkeypatch,error):
    monkeypatch.setattr(sd.time,'sleep',lambda n:None)
    provider.answers[:]=[error,dict(chapter_summary='Observed.',moments=[])]
    assert sd._inspect('fixture.mp4','Observe.','fixture-model')[0]['moments']==[]
    assert len(provider.calls)==2 and len(provider.uploaded)==1
    assert sd.analysis_failure(error)['retryable'] is True


def test_small_proxy_skips_upload_poll_delete_and_sets_bounded_thinking(provider,tmp_path):
    video=tmp_path/'small.mp4';video.write_bytes(b'test media')
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]
    sd._inspect(video,'Observe.','gemini-3.1-flash-lite')
    assert not provider.uploaded and not provider.deleted
    assert provider.calls[0]['contents'][0].inline_data.data==b'test media'
    assert provider.calls[0]['config'].thinking_config.thinking_level.value=='MINIMAL'
    assert len(provider.calls)==len(provider.closed)==1


def chapter(i,duration=900):
    return dict(offset=i*177,end=min(duration,i*177+180),chapter_summary='Observed.',moments=[])


def test_parallel_work_is_bounded_and_saves_out_of_order_on_failure(tmp_path,monkeypatch):
    monkeypatch.setenv('GEMINI_ANALYSIS_WORKERS','2')
    # Observe both completed futures as one batch to make the failure ordering
    # deterministic; production may have one more valid request already in flight.
    wait=sd.wait;monkeypatch.setattr(sd,'wait',lambda futures,**kwargs:wait(futures))
    barrier=threading.Barrier(2);lock=threading.Lock();calls=[];offsets=[]
    def work(i):
        with lock:calls.append(i);offsets.append(sd._chapter_context.key_offset)
        barrier.wait(timeout=3)
        if i==0:raise httpx.ReadTimeout('')
        return chapter(i)
    cache={'source_key':'fixture','chapters':[]};path=tmp_path/'story_analysis.json'
    with pytest.raises(httpx.ReadTimeout):sd._run_chapters(cache,path,5,900,work)
    assert set(calls)=={0,1} and sorted(offsets)==[0,1]
    saved=json.loads(path.read_text());assert saved['chapters']==[] and set(saved['completed'])=={'1'}
    assert json.loads((tmp_path/'analysis_failure.json').read_text())['completed_chapters']==1
    resumed=[]
    result=sd._run_chapters(saved,path,5,900,lambda i:resumed.append(i) or chapter(i))
    assert 1 not in resumed and set(resumed)=={0,2,3,4}
    assert sorted(result)==[0,1,2,3,4] and len(json.loads(path.read_text())['chapters'])==5
    assert not (tmp_path/'analysis_failure.json').exists()


def test_parallel_execution_really_overlaps_without_timing_assertions(tmp_path,monkeypatch):
    monkeypatch.setenv('GEMINI_ANALYSIS_WORKERS','2');barrier=threading.Barrier(2)
    def work(i):barrier.wait(timeout=3);return chapter(i,357)
    result=sd._run_chapters({'source_key':'x','chapters':[]},tmp_path/'cache.json',2,357,work)
    assert len(result)==2


def test_cross_job_cache_adopts_only_exact_legacy_identity(tmp_path,monkeypatch):
    root=tmp_path/'cache';monkeypatch.setenv('OPENSHORTS_ANALYSIS_CACHE',str(root))
    key='a'*64;old=tmp_path/'output/old';new=tmp_path/'output/new';old.mkdir(parents=True);new.mkdir()
    old_cache={'source_key':key,'chapters':[chapter(0)]}
    (old/'story_analysis.json').write_text(json.dumps(old_cache))
    reused,shared=sd._reusable_analysis({'source_key':key,'chapters':[]},new/'story_analysis.json',key)
    assert reused==old_cache and shared.parent==root
    sd._run_chapters(reused,new/'story_analysis.json',1,180,lambda i:pytest.fail('Cached chapter must not be bought twice'),shared)
    assert shared.is_file()
    other,_=sd._reusable_analysis({'source_key':'b'*64,'chapters':[]},new/'story_analysis.json','b'*64)
    assert not other['chapters']


def test_out_of_order_progress_counts_completions_not_highest_chapter(tmp_path):
    e=engine(tmp_path);fixture(e);e.jobs['job-one'].update(status='processing',logs=[
        'Video analysis: chapter 7/10 (1062–1242s)',
        'Video analysis completed: chapter 7/10',
        'Video analysis completed: chapter 7/10'])
    stage=next(s for s in progress(e,'job-one')['stages'] if s['id']=='analyze')
    assert stage['percent']==10


def test_error_diagnostics_include_status_without_provider_secrets():
    from google.genai.errors import ServerError
    error=ServerError(503,{'error':{'message':'private request body','status':'UNAVAILABLE','code':503}})
    report=sd.analysis_failure(error)
    assert report['status_code']==503 and report['retryable']
    assert 'private' not in json.dumps(report)


def test_large_proxy_upload_recovers_blank_write_timeout(provider,monkeypatch,tmp_path):
    from google import genai
    client=genai.Client();upload=client.files.upload;calls=[]
    def flaky(**kwargs):
        calls.append(1)
        if len(calls)==1:raise httpx.WriteTimeout('')
        return upload(**kwargs)
    monkeypatch.setattr(client.files,'upload',flaky)
    monkeypatch.setattr(sd.time,'sleep',lambda n:None)
    media=tmp_path/'large.mp4'
    with media.open('wb') as file:file.truncate(12*1024*1024+1)
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]
    sd._inspect(media,'Observe.','fixture-model')
    assert len(calls)==2 and len(provider.calls)==len(provider.deleted)==1


def test_server_errors_retry_without_reupload_and_stop_after_three(provider,monkeypatch):
    from google.genai.errors import ServerError
    monkeypatch.setattr(sd.time,'sleep',lambda n:None)
    failure=ServerError(503,{'error':{'code':503,'status':'UNAVAILABLE','message':'Temporary'}})
    provider.answers[:]=[failure]*3
    with pytest.raises(ServerError):sd._inspect('fixture.mp4','Observe.','fixture-model')
    assert len(provider.calls)==3 and len(provider.uploaded)==len(provider.closed)==1


def test_chapter_keys_rotate_without_mutating_shared_environment(provider,monkeypatch):
    from google import genai
    factory=genai.Client;slots=[]
    def client(**kwargs):slots.append(kwargs['api_key']);return factory(**kwargs)
    monkeypatch.setattr(genai,'Client',client)
    monkeypatch.setattr(sd,'api_keys',lambda:['slot-zero','slot-one'])
    sd._chapter_context.key_offset=1
    try:
        provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]
        sd._inspect('fixture.mp4','Observe.','fixture-model')
    finally:sd._chapter_context.key_offset=0
    assert slots==['slot-one']
