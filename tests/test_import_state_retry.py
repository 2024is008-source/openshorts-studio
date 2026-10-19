"""Windows import status publication remains bounded under read contention."""
import json
import os
import pytest
from desktop import import_worker as worker

pytestmark=pytest.mark.skipif(os.name != 'nt',reason='Windows sharing error semantics')

def denied():
    error=PermissionError('synthetic access denial');error.winerror=5
    return error

def test_status_eventually_publishes_after_reader_releases(tmp_path,monkeypatch):
    real=worker.atomic_json;attempts=[]
    def publish(path,value):
        attempts.append(1)
        if len(attempts)==1:raise denied()
        return real(path,value)
    monkeypatch.setattr(worker,'atomic_json',publish)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    worker.ImportJob(tmp_path).update(state='completed')
    assert json.loads((tmp_path/'state.json').read_text('utf-8'))['state']=='completed'
    assert len(attempts)==2

def test_permanent_denial_raises_without_false_completion(tmp_path,monkeypatch):
    waits=[]
    def publish(*_):raise denied()
    monkeypatch.setattr(worker,'atomic_json',publish)
    monkeypatch.setattr(worker.time,'sleep',waits.append)
    with pytest.raises(PermissionError):worker.ImportJob(tmp_path).update(state='completed')
    assert 0 < sum(waits) < 1
    assert not (tmp_path/'state.json').exists()

def test_unclassified_permission_failure_is_not_retried(tmp_path,monkeypatch):
    waits=[]
    def publish(*_):raise PermissionError('non-sharing permission failure')
    monkeypatch.setattr(worker,'atomic_json',publish)
    monkeypatch.setattr(worker.time,'sleep',waits.append)
    with pytest.raises(PermissionError):worker.ImportJob(tmp_path).update(state='completed')
    assert waits==[]
