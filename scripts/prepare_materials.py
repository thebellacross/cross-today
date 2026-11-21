"""Incremental local preparation. Originals are read-only; real files keep their names."""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from music.common import ROOT,config,file_hash,save_json
from music.library import EXTENSIONS,import_one
from music.preparation import prepared_name

def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'Prepared Sounds');args=parser.parse_args()
    root=args.source.resolve();out=args.output.resolve();cache=ROOT/'.cache/audio';settings=config()['import']
    files=sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS)
    names=Counter(str(p.relative_to(root).with_name(prepared_name(p.name))).casefold() for p in files);rows=[]
    for source in files:
        m=import_one(source,cache,settings);relative=source.relative_to(root);name=prepared_name(source.name)
        if names[str(relative.with_name(name)).casefold()]>1:name=source.name+' - prepared.wav'
        dest=out/relative.parent/name;dest.parent.mkdir(parents=True,exist_ok=True);prepared=cache/m['prepared_file'];sha=m['preparation']['sha256']
        if dest.exists() and file_hash(dest)!=sha:raise RuntimeError('A different prepared file already exists. Choose a separate output folder; nothing was overwritten.')
        if not dest.exists():os.link(prepared,dest) # A real file, sharing cache storage; no shortcut or library copy.
        assert file_hash(source)==m['source_hash'] and file_hash(dest)==sha
        rows.append({'source':str(source),'source_hash':m['source_hash'],'prepared':str(dest),'preparation':m['preparation']})
        save_json(ROOT/'.state/preparation/local-manifest.json',rows)
        print(json.dumps({'completed':len(rows),'total':len(files),'removed_seconds':round(m['preparation']['removed_frames']/m['preparation']['sample_rate'],3)}),flush=True)
    print(json.dumps({'prepared_files':len(rows),'output':str(out),'originals_unchanged':True,'incremental_cache':True}))

if __name__=='__main__':main()
