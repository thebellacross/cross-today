"""Add native stereo derivatives. Do not rewrite originals or legacy caches."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from music.common import ROOT,save_json,config
from music.library import import_folder
p=argparse.ArgumentParser();p.add_argument('folder');a=p.parse_args();old=ROOT/'.state/snapshot.json'
if old.exists():
    before=json.loads(old.read_text());save_json(ROOT/'.state/snapshots'/(before['id']+'.json'),before)
settings=dict(config()['import'],channels='preserve');snapshot,errors=import_folder(a.folder,settings=settings);save_json(ROOT/'.state/snapshots'/(snapshot['id']+'.json'),snapshot)
print(json.dumps({'snapshot':snapshot['id'],'clips':len(snapshot['clips']),'invalid_files':len(errors),'legacy_cache_retained':True}))
