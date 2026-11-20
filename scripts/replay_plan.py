"""Replay a frozen composition plan against its retained material snapshot."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from music.common import ROOT,digest,file_hash
from music.renderer import render_plan
from music.studio import encode
p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--cache',default='.cache/audio');p.add_argument('--output',required=True);p.add_argument('--allow-version-mismatch',action='store_true');a=p.parse_args()
plan=json.loads(Path(a.plan).read_text());snapshot=json.loads(Path(a.snapshot).read_text());actual=digest({f.name:file_hash(f) for f in sorted((ROOT/'music').glob('*.py'))});recorded=plan.get('replay',{}).get('engine_hash')
if recorded and actual!=recorded and not a.allow_version_mismatch:raise SystemExit('Engine differs from this plan. Check out its immutable engine_ref and use its recorded dependencies, or explicitly allow a non-identical version comparison.')
audio,report,_=render_plan(plan,snapshot,a.cache);out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);encode(audio,plan['sample_rate'],out,True,plan.get('output_sample_rate',plan['sample_rate']));print(json.dumps({'file':str(out),'sha256':file_hash(out),'same_engine':actual==recorded,'plan_id':plan['plan_id'],'clipped_samples':report['clipped_samples']}))
