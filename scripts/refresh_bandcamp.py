"""Refresh the public discography at publication time; preserve the artist identity."""
import argparse
import datetime
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'CROSS-discography/1.0'}), timeout=20) as response:
        return response.read()


class ReleaseGrid(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.item = None
        self.in_title = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'li' and 'music-grid-item' in attrs.get('class', '').split():
            self.item = {'title': ''}
        if self.item is None:
            return
        if tag == 'a' and attrs.get('href'):
            self.item['href'] = attrs['href']
        if tag == 'img':
            self.item['image'] = attrs.get('data-original') or attrs.get('src', '')
        if tag == 'p' and 'title' in attrs.get('class', '').split():
            self.in_title = True

    def handle_data(self, data):
        if self.in_title and self.item is not None:
            self.item['title'] += data

    def handle_endtag(self, tag):
        if tag == 'p':
            self.in_title = False
        if tag == 'li' and self.item is not None:
            self.items.append(self.item)
            self.item = None


def releases(page, base):
    parser = ReleaseGrid()
    parser.feed(page)
    result = []
    for entry in parser.items:
        if not entry.get('href') or not entry.get('image') or not entry['title'].strip():
            continue
        url = urljoin(base, entry['href'])
        slug = urlparse(url).path.rstrip('/').split('/')[-1]
        source = urljoin(base, entry['image'])
        if urlparse(url).hostname != urlparse(base).hostname or not re.fullmatch(r'[a-z0-9-]+', slug):
            continue
        if not (urlparse(source).hostname or '').endswith('.bcbits.com'):
            continue
        source = re.sub(r'_\d+\.jpg$', '_16.jpg', source)
        result.append({'title': entry['title'].strip(), 'url': url,
                       'cover': f'assets/artist/{slug}.jpg', 'cover_source': source})
    if not result:
        title = re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I)
        label = html.unescape(re.sub(r'<[^>]+>', '', title[1])).strip()[:80] if title else 'no title'
        raise ValueError(f'No public releases in response ({len(page)} characters, {label!r})')
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
        print(f'Bandcamp refresh unavailable ({type(error).__name__}: {error}); kept the verified discography.')
