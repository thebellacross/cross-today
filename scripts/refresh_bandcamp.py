"""Refresh the public discography at publication time; preserve the artist identity."""
import argparse
import datetime
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'CROSS-discography/1.0'}), timeout=20) as response:
        return response.read()


def releases(page, base):
    result = []
    for block in re.findall(r'<li\b[^>]*class="[^"]*music-grid-item[^>]*>(.*?)</li>', page, re.S):
        link = re.search(r'<a\s+href="([^"]+)"', block)
        title = re.search(r'<p\s+class="title"[^>]*>(.*?)</p>', block, re.S)
        cover = re.search(r'<img[^>]*(?:src|data-original)="(https://[^\"]+bcbits\.com/[^\"]+)"', block)
        if not all((link, title, cover)):
            continue
        url = urljoin(base, html.unescape(link[1]))
        slug = urlparse(url).path.rstrip('/').split('/')[-1]
        if urlparse(url).hostname != urlparse(base).hostname or not re.fullmatch(r'[a-z0-9-]+', slug):
            continue
        source = re.sub(r'_\d+\.jpg$', '_16.jpg', html.unescape(cover[1]))
        result.append({'title': html.unescape(re.sub(r'<[^>]+>', '', title[1])).strip(),
                       'url': url, 'cover': f'assets/artist/{slug}.jpg', 'cover_source': source})
    if not result:
        raise ValueError('No public Bandcamp releases could be verified')
    return result


def release_date(page):
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        data = json.loads(raw)
        value = data.get('datePublished')
        if value:
            for pattern in ('%d %b %Y %H:%M:%S %Z', '%d %b %Y', '%Y-%m-%d'):
                try:
                    return datetime.datetime.strptime(value, pattern).date().isoformat()
                except ValueError:
                    pass
    raise ValueError('Release date could not be verified')


def refresh(destination, fetcher=fetch):
    previous = json.loads((destination / 'artist.json').read_text())
    base = previous['bandcamp']
    found = releases(fetcher(urljoin(base, 'music')).decode(), base)
    prior = {item['url']: item for item in previous['albums']}
    images = {}
    for item in found:
        old = prior.get(item['url'], {})
        item['released'] = old.get('released') or release_date(fetcher(item['url']).decode())
        path = destination / item['cover']
        if old.get('cover_source') != item['cover_source'] or not path.exists():
            image = fetcher(item['cover_source'])
            if not image.startswith(b'\xff\xd8\xff'):
                raise ValueError('Bandcamp did not return a JPEG cover')
            images[path] = image
    # Validate everything before replacing the saved list or any cover.
    for path, image in images.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
    data = {**previous, 'albums': found, 'verified_at': datetime.date.today().isoformat()}
    (destination / 'artist.json').write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return len(found)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ROOT / 'web')
    parser.add_argument('--keep-on-error', action='store_true')
    args = parser.parse_args()
    try:
        print(f'Verified {refresh(args.out)} Bandcamp releases.')
    except Exception as error:
        if not args.keep_on_error:
            raise
        print(f'Bandcamp refresh unavailable ({type(error).__name__}); kept the verified discography.')
