import hashlib
import zipfile
from pathlib import Path

import pytest

from music.album import download_archives
from music.cloud import Cloud, failure_diagnostic, ServiceFailure

def test_public_failure_diagnostic_never_includes_private_error_text():
    try:
        raise ValueError('/private/recording.wav https://private.invalid?token=secret')
    except ValueError as error:
        result=failure_diagnostic(error)
    assert 'ValueError' in result
    assert not any(x in result for x in ('recording','private.invalid','secret'))
    assert 'HTTP 403' in failure_diagnostic(ServiceFailure('GitHub','POST',403))


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
