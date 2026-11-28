"""Prepare only the current public edition's artwork for the Pages build.

This runs independently of the frozen music engine. No audio, release metadata,
private material, or existing reproduction environment is modified.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'CROSS-artwork-build'}), timeout=60) as response:
                return response.read()
        except urllib.error.URLError as error:
            if attempt == 2 or (isinstance(error, urllib.error.HTTPError) and error.code < 500 and error.code != 429):
                raise
            time.sleep(attempt + 1)


def prepare(out, if_changed=False):
    cfg = json.loads((ROOT / 'config.json').read_text())
    api = os.environ.get('WORKER_URL') or cfg['worker_url']
    album = json.loads(fetch(api.rstrip('/') + '/public/current'))
    version = hashlib.sha256((ROOT / 'web/record.js').read_bytes()).hexdigest()[:16]
    source = album['assets']['cover.png']
    identity = {'id': album['id'], 'source_sha256': source['sha256'], 'renderer': version}
    if if_changed:
        try:
            previous = json.loads(fetch(cfg['site_url'].rstrip('/') + '/record-preview.json'))
            if all(previous.get(key) == value for key, value in identity.items()):
                return False
        except (urllib.error.URLError, ValueError):
            pass  # A missing first build must still produce the artwork.
    # Download from the configured public endpoint, never an arbitrary URL from metadata.
    import re
    if not re.fullmatch(r'album-\d{4}-\d{2}-\d{2}', album['id']):
        raise ValueError('Invalid public edition identifier')
    cover = fetch(api.rstrip('/') + '/media/' + album['id'] + '/cover.png')
    if len(cover) != source['bytes'] or hashlib.sha256(cover).hexdigest() != source['sha256']:
        raise ValueError('Published cover checksum did not match its manifest')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'cover.png').write_bytes(cover)
    (out / 'album.json').write_text(json.dumps(album))
    (out / 'identity.json').write_text(json.dumps(identity))
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--if-changed', action='store_true')
    args = parser.parse_args()
    changed = prepare(args.out, args.if_changed)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'changed={str(changed).lower()}\n')
    print('Public record artwork prepared.' if changed else 'Published record artwork is already current.')
