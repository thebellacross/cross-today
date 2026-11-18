"""Refresh public identity and discography; never invent missing artist details."""
import datetime
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from music.common import save_json
cfg=json.loads((ROOT/'config.json').read_text());base=cfg['bandcamp'];session=requests.Session()
def fetch(url):
    r=session.get(url,timeout=45);r.raise_for_status();return r
page=fetch(base).text
clean=lambda s:html.unescape(re.sub(r'<[^>]+>','',s)).strip()
identity=re.search(r'<p\s+id="band-name-location"[^>]*>(.*?)</p>',page,re.S)
if not identity:raise SystemExit('Bandcamp layout was not recognized; the existing artist list is unchanged.')
name=re.search(r'<span\s+class="title"[^>]*>(.*?)</span>',identity[1],re.S)
if not name:raise SystemExit('Artist identity could not be verified.')
avatar=re.search(r'<img\s+[^>]*src="([^"]+)"[^>]*class="band-photo"',page)
if not avatar:raise SystemExit('Artist avatar could not be verified.')
previous=json.loads((ROOT/'web/artist.json').read_text()) if (ROOT/'web/artist.json').exists() else {}
prior={a['url']:a for a in previous.get('albums',[])};albums=[];assets=ROOT/'web/assets/artist';assets.mkdir(parents=True,exist_ok=True)
for block in re.findall(r'<li\b[^>]*class="[^"]*music-grid-item[^>]*>(.*?)</li>',page,re.S):
    href=re.search(r'<a\s+href="([^"]+)"',block);title=re.search(r'<p\s+class="title"[^>]*>(.*?)</p>',block,re.S);cover=re.search(r'<img[^>]*(?:src|data-original)="(https://[^\"]+bcbits\.com/[^\"]+)"',block)
    if not all([href,title,cover]):continue
    url=urljoin(base,html.unescape(href[1]));slug=urlparse(url).path.rstrip('/').split('/')[-1]
    if not re.fullmatch(r'[a-z0-9-]+',slug) or urlparse(url).hostname!=urlparse(base).hostname:continue
    detail=fetch(url).text;date=prior.get(url,{}).get('released')
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',detail,re.S):
        try:
            value=json.loads(raw).get('datePublished')
            if value:
                for pattern in ['%d %b %Y %H:%M:%S %Z','%d %b %Y','%Y-%m-%d']:
                    try:date=datetime.datetime.strptime(value,pattern).date().isoformat();break
                    except ValueError:pass
        except (ValueError,AttributeError):pass
    source=html.unescape(cover[1]);image=fetch(source);(assets/(slug+'.jpg')).write_bytes(image.content)
    albums.append({'title':clean(title[1]),'url':url,'cover':f'assets/artist/{slug}.jpg','cover_source':source,'released':date})
if not albums:raise SystemExit('No albums could be verified; the existing list is unchanged.')
avatar_url=html.unescape(avatar[1]);(assets/'bellacross.jpg').write_bytes(fetch(avatar_url).content)
data={'name':clean(name[1]),'bandcamp':base,'avatar':'assets/artist/bellacross.jpg','avatar_source':avatar_url,'bio':previous.get('bio',''),'location':previous.get('location',''),'verified_at':datetime.date.today().isoformat(),'albums':albums}
save_json(ROOT/'web/artist.json',data);print(f'Verified {data["name"]}: {len(albums)} Bandcamp releases. Publish the updated website to apply.')
