import argparse
import json
import os
import shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
cfg=json.loads((root/'config.json').read_text());api=os.environ.get('WORKER_URL') or cfg['worker_url']
if not api.startswith('https://'):raise SystemExit('A deployed HTTPS Worker is required before publishing the site.')
allowed={'index.html','style.css','app.js','client.js','score.html','score.js','catalog.html','catalog.js','artist.json'}
for name in allowed:shutil.copy2(root/'web'/name,out/name)
shutil.copytree(root/'web/assets',out/'assets',dirs_exist_ok=True)
(out/'public-config.json').write_text(json.dumps({'api':api,'site_url':cfg['site_url']}))
(out/'.nojekyll').touch()
