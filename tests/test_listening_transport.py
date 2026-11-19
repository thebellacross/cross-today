"""Isolated failures; never contact or label the owner's real service."""
from types import SimpleNamespace
import pytest
import requests
from scripts.listening_runner import install_transport,install_pinned_score_reader

TASK='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

@pytest.mark.parametrize('path,method,expected',[
    ('/internal/cache/frozen.wav','GET',3),
    ('/internal/storage/register','POST',3),
    (f'/internal/studio/tasks/{TASK}/ready','POST',3),
    ('/api/unrelated-write','POST',1),
])
def test_only_known_idempotent_operations_repeat(monkeypatch,path,method,expected):
    attempts=[]
    def api(*args,**kwargs):
        attempts.append((args,kwargs))
        if len(attempts)<3:raise requests.exceptions.ConnectionError('simulated interruption')
        return {'ok':True}
    cloud=SimpleNamespace(api=api);monkeypatch.setattr('scripts.listening_runner.time.sleep',lambda _:None)
    audit=install_transport(cloud,TASK,'engine-v11','test-coordinator')
    data={'result':{'engine_ref':'engine-v11'}}
    if expected==1:
        with pytest.raises(requests.exceptions.ConnectionError):cloud.api(path,method,data)
    else:assert cloud.api(path,method,data)=={'ok':True}
    assert len(attempts)==expected;assert data=={'result':{'engine_ref':'engine-v11'}}
    assert audit['engine_ref']=='engine-v11'
    if path.endswith('/ready'):assert attempts[-1][0][2]['result']['transport_adapter']['version']=='private-transport-2'

def test_rejected_quota_waits_without_changing_frozen_arguments(monkeypatch):
    calls=[];sleeps=[]
    class Limited(Exception):safe_detail='Private service POST returned HTTP 429'
    def api(*args,**kwargs):
        calls.append((args,kwargs))
        if len(calls)==1:raise Limited()
        return {'ok':True}
    cloud=SimpleNamespace(api=api);monkeypatch.setattr('scripts.listening_runner.time.sleep',sleeps.append)
    audit=install_transport(cloud,TASK,'engine-v11','test-coordinator');assert cloud.api('/internal/storage/write','POST',{})=={'ok':True}
    assert calls[0]==calls[1] and sleeps==[60] and audit['quota_wait_seconds']==60

def test_network_retries_remain_bounded(monkeypatch):
    calls=[]
    def api(*args,**kwargs):calls.append(1);raise requests.exceptions.Timeout('simulated timeout')
    cloud=SimpleNamespace(api=api);monkeypatch.setattr('scripts.listening_runner.time.sleep',lambda _:None)
    install_transport(cloud,TASK,'engine-v11','test-coordinator')
    with pytest.raises(requests.exceptions.Timeout):cloud.api('/internal/storage/register','POST',{})
    assert len(calls)==4

@pytest.mark.parametrize('valid',[True,False])
def test_pinned_score_reader_preserves_raw_bytes_and_checks_identity(valid):
    import hashlib
    data=b'{"tracks": []}\n';seen=[]
    def api(path):seen.append(path);return data
    cloud=SimpleNamespace(api=api,download_generated=lambda *args:b'ordinary read-only path')
    task={'id':TASK,'parent_daily':{'album':'album-2030-01-01'}};install_pinned_score_reader(cloud,task)
    meta={'bytes':len(data),'sha256':hashlib.sha256(data if valid else b'wrong').hexdigest()}
    if valid:assert cloud.download_generated('album-2030-01-01','score.json',meta)==data
    else:
        with pytest.raises(RuntimeError,match='checksum'):cloud.download_generated('album-2030-01-01','score.json',meta)
    assert seen==[f'/internal/studio/tasks/{TASK}/daily-score'];assert cloud.download_generated('other','other.json',meta)==b'ordinary read-only path'
