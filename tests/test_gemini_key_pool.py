import itertools
import json
import pytest
import gemini_keys as pool


def environment():
    return {'GEMINI_API_KEY':'fixture-1',**{f'GEMINI_API_KEY_{i}':f'fixture-{i}' for i in range(1,9)}}


def test_reads_all_eight_in_numeric_order_and_deduplicates():
    env=environment();env['GEMINI_API_KEY_10']='fixture-10'
    assert pool.configured(env)==[*(f'fixture-{i}' for i in range(1,9)),'fixture-10']


def test_each_job_gets_different_primary_and_all_failover_keys(monkeypatch):
    monkeypatch.setattr(pool,'_jobs',itertools.count())
    jobs=[pool.assign_job(environment()) for _ in range(9)]
    assert [job['GEMINI_API_KEY'] for job in jobs[:8]]==[f'fixture-{i}' for i in range(1,9)]
    assert jobs[8]['GEMINI_API_KEY']=='fixture-1'
    assert all(len(pool.configured(job))==8 for job in jobs)


def test_protected_pool_clears_router_and_preserves_model(tmp_path,monkeypatch):
    from desktop.gemini_keys import apply_pool
    from desktop.credentials import CredentialStore
    (tmp_path/'credentials.dpapi').write_bytes(b'protected-fixture')
    monkeypatch.setattr(CredentialStore,'load',lambda self:json.dumps([f'fixture-{i}' for i in range(1,9)]))
    result=apply_pool({'LLM_PROVIDER':'openai','LLM_BASE_URL':'http://router','LLM_API_KEY':'old',
        'GEMINI_MODEL':'existing-model','GEMINI_API_KEY_9':'old'},tmp_path)
    assert result['LLM_PROVIDER']=='gemini' and 'LLM_BASE_URL' not in result and 'LLM_API_KEY' not in result
    assert len(pool.configured(result))==8 and result['GEMINI_MODEL']=='existing-model'


def test_main_and_director_use_same_eight_key_order(monkeypatch):
    import main
    import story_director
    for name in pool.numbered_names(__import__('os').environ):monkeypatch.delenv(name)
    for name,value in environment().items():monkeypatch.setenv(name,value)
    assert main._gemini_api_keys()==story_director.api_keys()==list(environment().values())[:1]+[f'fixture-{i}' for i in range(2,9)]


def test_explicit_user_key_can_be_isolated_from_all_numbered_slots():
    env=environment()
    for name in pool.numbered_names(env):env.pop(name)
    env['GEMINI_API_KEY']='explicit-key'
    assert pool.configured(env)==['explicit-key']


def test_logs_redact_new_key_format(monkeypatch):
    import app
    key='AQ.'+'a'*40
    monkeypatch.setenv('GEMINI_API_KEY_8',key)
    assert key not in app._scrub_secrets('provider error: '+key)
