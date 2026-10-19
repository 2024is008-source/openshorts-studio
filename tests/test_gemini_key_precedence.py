"""Credential precedence and health exclusions; no provider requests."""
import hashlib
import json
import time
from pathlib import Path
from desktop.gemini_keys import apply_pool
from desktop.credentials import CredentialStore
from desktop.processes import environment
from desktop.storage import Storage
from gemini_keys import configured,assign_job


def test_explicit_env_pool_wins_without_loading_old_encrypted_pool(tmp_path,monkeypatch):
    (tmp_path/'credentials.dpapi').write_bytes(b'old')
    monkeypatch.setattr(CredentialStore,'load',lambda *a:(_ for _ in ()).throw(AssertionError('Do not read old pool')))
    value=apply_pool({'GEMINI_API_KEY':'old-ui','GEMINI_API_KEY_9':'old','GEMINI_MODEL':'model'},tmp_path,['new-one','new-two'])
    assert configured(value)==['new-one','new-two'] and value['GEMINI_KEY_SOURCE']=='env'


def test_auth_rejected_key_not_assigned_but_changed_key_is_usable(tmp_path):
    digest=hashlib.sha256(b'rejected').hexdigest()
    (tmp_path/'key-health.json').write_text(json.dumps({'version':1,'keys':{digest:{'model':'model','http_status':401,'checked_at':time.time()}}}))
    env=apply_pool({'GEMINI_MODEL':'model'},tmp_path,['working','rejected'])
    assert configured(env)==['working']
    assert configured(assign_job(env.copy()))==['working']
    assert configured(apply_pool({'GEMINI_MODEL':'model'},tmp_path,['working','replaced']))==['working','replaced']


def test_health_is_model_scoped_and_expires(tmp_path):
    digest=hashlib.sha256(b'key').hexdigest()
    path=tmp_path/'key-health.json'
    def saved(when):path.write_text(json.dumps({'version':1,'keys':{digest:{'model':'old-model','http_status':403,'checked_at':when}}}))
    saved(time.time())
    assert configured(apply_pool({'GEMINI_MODEL':'new-model'},tmp_path,['key']))==['key']
    saved(time.time()-3601)
    assert configured(apply_pool({'GEMINI_MODEL':'old-model'},tmp_path,['key']))==['key']


def test_no_healthy_explicit_keys_does_not_fall_back_to_old_account(tmp_path,monkeypatch):
    digest=hashlib.sha256(b'bad').hexdigest()
    (tmp_path/'key-health.json').write_text(json.dumps({'version':1,'keys':{digest:{'model':'m','http_status':401,'checked_at':time.time()}}}))
    value=apply_pool({'GEMINI_MODEL':'m','GEMINI_API_KEY':'old'},tmp_path,['bad'])
    assert not configured(value) and value['GEMINI_KEY_POOL']=='0'


def test_desktop_reads_all_numbered_env_keys_and_ignores_saved_ui_key(tmp_path,monkeypatch):
    import desktop.processes
    monkeypatch.setattr(desktop.processes,'resources',lambda:tmp_path)
    (tmp_path/'.env').write_text('GEMINI_API_KEY_1=new-one\nGEMINI_API_KEY_2=new-two\nGEMINI_API_KEY_8=new-eight\nGEMINI_MODEL=current-model\n')
    storage=Storage(tmp_path/'library',tmp_path/'profile')
    value=environment(storage,storage.settings(),'old-ui-key')
    assert configured(value)==['new-one','new-two','new-eight']
    assert value['GEMINI_MODEL']=='current-model' and value['GEMINI_KEY_SOURCE']=='env'


def test_corrupt_health_metadata_does_not_break_startup(tmp_path):
    (tmp_path/'key-health.json').write_text('{broken')
    assert configured(apply_pool({},tmp_path,['configured-key']))==['configured-key']
