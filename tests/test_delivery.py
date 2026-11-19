import hashlib
import zipfile
from types import SimpleNamespace
from pathlib import Path

import pytest

from music.album import download_archives
from music.cloud import Cloud, failure_diagnostic, ServiceFailure

@pytest.mark.parametrize('method,attempts',[('GET',3),('POST',1)])
def test_truncated_private_reads_retry_without_duplicating_writes(monkeypatch,method,attempts):
    import requests
    from types import SimpleNamespace
    cloud=Cloud.__new__(Cloud);cloud.base='https://example.test';cloud.run_token='test-only';seen=[]
    def request(verb,url,**kwargs):
        seen.append((verb,url))
        if len(seen)<=2:raise requests.exceptions.ChunkedEncodingError('simulated truncated body')
        return SimpleNamespace(ok=True,status_code=200,headers={},content=b'complete snapshot bytes')
    cloud.http=SimpleNamespace(request=request);monkeypatch.setattr('music.cloud.time.sleep',lambda _:None)
    if method=='GET':assert cloud.api('/internal/cache/frozen',method)==b'complete snapshot bytes'
    else:
        with pytest.raises(requests.exceptions.ChunkedEncodingError):cloud.api('/internal/cache/frozen',method)
    assert seen==[(method,'https://example.test/internal/cache/frozen')]*attempts

def test_private_read_transport_retry_is_bounded(monkeypatch):
    import requests
    from types import SimpleNamespace
    cloud=Cloud.__new__(Cloud);cloud.base='https://example.test';cloud.run_token='test-only';seen=[]
    def request(*args,**kwargs):seen.append(1);raise requests.exceptions.Timeout('simulated timeout')
    cloud.http=SimpleNamespace(request=request);monkeypatch.setattr('music.cloud.time.sleep',lambda _:None)
    with pytest.raises(requests.exceptions.Timeout):cloud.api('/internal/cache/frozen')
    assert len(seen)==4

def test_public_failure_diagnostic_never_includes_private_error_text():
    try:
        raise ValueError('/private/recording.wav https://private.invalid?token=secret')
    except ValueError as error:
        result=failure_diagnostic(error)
    assert 'ValueError' in result
    assert not any(x in result for x in ('recording','private.invalid','secret'))
    assert 'HTTP 403' in failure_diagnostic(ServiceFailure('GitHub','POST',403))

def test_draft_release_is_found_before_git_tag_exists():
    cloud=Cloud.__new__(Cloud);cloud.repo='thebellacross/cross-today'
    draft={'id':17,'tag_name':'album-2026-11-16','draft':True}
    cloud.gh=lambda path,**kwargs: None if '/releases/tags/' in path else [draft]
    assert cloud.release('album-2026-11-16')==draft
    assert cloud.release('album-2026-11-17') is None

def test_private_metadata_transfer_avoids_cdn_compression(tmp_path):
    class Response:
        status_code=206
        headers={'Content-Range':'bytes 0-3/4'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,*args):yield b'text'
    class CDN:
        def head(self,url,headers,**kwargs):
            # Compressible metadata loses Content-Length when compression is allowed.
            return SimpleNamespace(ok=True,headers={'Content-Length':'4'} if headers.get('Accept-Encoding')=='identity' else {})
        def get(self,url,headers,**kwargs):
            assert headers['Accept-Encoding']=='identity'
            assert headers['Range']=='bytes=0-3'
            return Response()
    cloud=Cloud.__new__(Cloud);cloud.base='https://example.test';cloud.run_token='test-only';cloud.http=CDN()
    target=tmp_path/'credits.txt';cloud.download_private('/private/credits.txt',target)
    assert target.read_bytes()==b'text'


def test_large_downloads_split_into_complete_independent_archives(tmp_path):
    for name in ('cover.png', 'credits.txt', 'score.json', 'provenance.json'):
        (tmp_path / name).write_bytes(b'x')
    for n in range(1, 4):
        (tmp_path / f'{n:02d}.wav').write_bytes(bytes([n]) * 40)
    downloads = download_archives(tmp_path, 'wav', limit=65600)
    assert len(downloads) == 3
    seen = []
    for filename in downloads.values():
        with zipfile.ZipFile(tmp_path / filename) as archive:
            assert {'cover.png', 'credits.txt', 'score.json', 'provenance.json'} <= set(archive.namelist())
            assert archive.testzip() is None
            seen.extend(name for name in archive.namelist() if name.endswith('.wav'))
    assert sorted(seen) == ['01.wav', '02.wav', '03.wav']


@pytest.mark.parametrize('remote', ['matching', 'missing', 'wrong_size', 'wrong_hash'])
def test_retry_never_pairs_public_release_with_different_generated_audio(remote):
    cloud = Cloud.__new__(Cloud)
    cloud.repo = 'thebellacross/cross-today'
    cloud.release = lambda job: {'id': 17, 'draft': False}
    checksum = hashlib.sha256(b'generated music').hexdigest()
    album = {'assets': {'01.mp3': {'bytes': 15, 'sha256': checksum}}}
    asset = {'id': 22, 'name': '01.mp3', 'size': 15, 'digest': 'sha256:' + checksum}
    if remote == 'wrong_size':
        asset['size'] = 14
    if remote == 'wrong_hash':
        asset['digest'] = 'sha256:' + '0' * 64
    cloud.gh = lambda *args, **kwargs: [] if remote == 'missing' else [asset]
    if remote == 'matching':
        assert cloud.upload_assets('album-2026-11-18', Path('/unused'), album)['id'] == 17
    else:
        with pytest.raises(RuntimeError):
            cloud.upload_assets('album-2026-11-18', Path('/unused'), album)
