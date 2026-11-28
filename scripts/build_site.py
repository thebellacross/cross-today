import argparse
import json
import os
import shutil
import hashlib
import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--record-preview',type=Path);a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
cfg=json.loads((root/'config.json').read_text());api=os.environ.get('WORKER_URL') or cfg['worker_url']
if not api.startswith('https://'):raise SystemExit('A deployed HTTPS Worker is required before publishing the site.')
allowed={'index.html','style.css','listening.css','app.js','record.js','record-boot.js','track-picker.js','scratch-audio.js','scratch-voice.js','scratch-worklet.js','client.js','score.html','score.js','score-view.js','catalog.html','catalog.js','artist.json'}
for name in allowed:shutil.copy2(root/'web'/name,out/name)
shutil.copytree(root/'web/assets',out/'assets',dirs_exist_ok=True)
(out/'public-config.json').write_text(json.dumps({'api':api,'site_url':cfg['site_url']}))
(out/'.nojekyll').touch()
if a.record_preview:
    preview=json.loads((a.record_preview/'record-preview.json').read_text())
    if not re.fullmatch(r'album-\d{4}-\d{2}-\d{2}',preview['id']):raise ValueError('Invalid prepared edition identifier')
    if not re.fullmatch(r'[a-f0-9]{64}',preview['source_sha256']):raise ValueError('Invalid source cover checksum')
    name=preview['file']
    if Path(name).name!=name or not name.endswith('.webp'):raise ValueError('Invalid prepared record filename')
    data=(a.record_preview/name).read_bytes()
    if hashlib.sha256(data).hexdigest()!=preview['sha256']:raise ValueError('Prepared record checksum mismatch')
    (out/name).write_bytes(data)
    (out/'record-preview.json').write_text(json.dumps(preview))
    page=(out/'index.html').read_text().replace('assets/record-outline.svg',name)
    page=page.replace('data-preview-id=""',f'data-preview-id="{preview["id"]}"').replace('data-preview-hash=""',f'data-preview-hash="{preview["source_sha256"]}"')
    (out/'index.html').write_text(page)
