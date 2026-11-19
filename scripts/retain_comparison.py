"""Retain an explicitly confirmed local audition in the existing private service.
The input confirmation file is private and is never committed or published.
"""
import argparse,copy,json,os,shutil,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keychain_credentials import credential
from music.common import ROOT,config,digest,file_hash,save_json,canonical
from music.cloud import Cloud
from music.renderer import render_plan
from music.studio import encode
from music.preference import vector
import requests
import numpy as np

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',required=True);parser.add_argument('--confirmation',required=True);a=parser.parse_args();cfg=config();confirmation=Path(a.confirmation);feedback=json.loads(confirmation.read_text())
    if feedback.get('origin')!='human' or feedback.get('confirmed') is not True or feedback.get('choice') not in ('A','B','both','neither','unknown','technical'):raise SystemExit('An explicit owner choice is required.')
    if feedback.get('server_revision'):
        print('This confirmed comparison is already retained; no duplicate label was created.');return
    folder=Path(a.folder);result=json.loads((folder/'result.json').read_text());snapshot=json.loads((folder/'snapshot.json').read_text());known={c['id']:c for c in result['candidates']}
    if [known[i]['audio_hash'] for i in feedback['order']]!=feedback['audio_hashes']:raise SystemExit('The confirmation does not belong to these exact audio files.')
    for c in result['candidates']:
        if file_hash(folder/(c['prefix']+'.wav'))!=c['audio_hash'] or file_hash(folder/(c['prefix']+'.mp3'))!=c['audition_hash']:raise SystemExit('An audition file changed after confirmation.')
    retained=folder.parent/(folder.name+'-retained');retained.mkdir(exist_ok=True)
    for path in folder.iterdir():
        if path.is_file():shutil.copy2(path,retained/path.name)
    mapping={};code_hash=digest({f.name:file_hash(f) for f in sorted((ROOT/'music').glob('*.py'))})
    for c in result['candidates']:
        prefix=c['prefix'];p=json.loads((folder/(prefix+'-plan.json')).read_text());r=json.loads((folder/(prefix+'-report.json')).read_text());old=p.pop('plan_id');p['parent_id']=mapping.get(p['parent_id'],p['parent_id']);p['replay']={'engine_ref':cfg['engine_ref'],'engine_hash':code_hash,'numpy':np.__version__,'model_version':None,'configuration':{**r.get('replay',{}).get('config',{}),'controls':p['controls']},'local_audition_prior_id':old}
        p['plan_id']=digest(p);mapping[old]=p['plan_id'];audio,verified,_=render_plan(p,snapshot,ROOT/'.cache/audio');encode(audio,p['sample_rate'],retained/'replay-check.wav',True)
        if file_hash(retained/'replay-check.wav')!=c['audio_hash']:raise SystemExit('Replay failed; no preference was uploaded.')
        (retained/'replay-check.wav').unlink();r.update(plan=p,plan_id=p['plan_id']);c.update(id=p['plan_id'],parent_id=p['parent_id'],features=vector(p,verified));save_json(retained/(prefix+'-plan.json'),p);save_json(retained/(prefix+'-report.json'),r)
    result['source_hashes']=sorted(set(c['source_hash'] for c in snapshot['clips']));result['suggested']=mapping.get(result['suggested'],result['suggested'])
    for row in result['decision']['ranking']:row['id']=mapping.get(row['id'],row['id'])
    result['files']={p.name:{'sha256':file_hash(p),'bytes':p.stat().st_size} for p in retained.iterdir() if p.is_file() and p.name!='result.json'};save_json(retained/'result.json',result)
    token=credential('GITHUB_TOKEN');os.environ.update(WORKER_URL=cfg['worker_url'],RUN_TOKEN=credential('RUN_TOKEN'),GH_TOKEN=token,GITHUB_REPOSITORY='thebellacross/cross-today',STORAGE_REPOSITORY=credential('STORAGE_REPOSITORY'),STORAGE_TOKEN=token)
    cloud=Cloud();task_id=feedback.get('remote_task') or str(uuid.uuid4());feedback['remote_task']=task_id;save_json(confirmation,feedback)
    cloud.api('/internal/studio/import','POST',{'id':task_id,'profile_id':feedback['profile_id'],'engine_ref':cfg['engine_ref'],'seed':result['decision']['seed']})
    # Store only these versioned derivatives, never the rest of the local library.
    for clip in snapshot['clips']:
        key=clip['cache_file'].split('/')[0];source=ROOT/'.cache/audio'/clip['cache_file']
        with source.open('rb') as f:cloud.api(f'/internal/cache/{key}/{clip["id"]}.wav','PUT',raw=f)
    for name in result['files']:cloud.private_put(f'lab/{task_id}/{name}',retained/name)
    cloud.api(f'/internal/studio/tasks/{task_id}/ready','POST',{'run':'local-verified-import','result':result})
    if not feedback.get('remote_comparison'):
        comparison=cloud.api('/internal/studio/import-comparison','POST',{'task':task_id,'order':[mapping[i] for i in feedback['order']],'scope':feedback['scope']});feedback['remote_comparison']=comparison['id'];save_json(confirmation,feedback)
    admin=requests.Session();admin.headers.update(Authorization='Bearer '+credential('ADMIN_TOKEN'))
    response=admin.post(cfg['worker_url']+'/api/studio/feedback',json={'comparison':feedback['remote_comparison'],'choice':feedback['choice'],'scope':feedback['scope'],'note':feedback['user_text'],'confirmed':True},timeout=60)
    if not response.ok:raise SystemExit('Private feedback persistence failed with HTTP '+str(response.status_code))
    saved=response.json();feedback['server_revision']=saved['revision'];save_json(confirmation,feedback);print(json.dumps({'task':task_id,'feedback':saved['id'],'choice':saved['choice'],'audio_hashes':saved['audio_hashes'],'stored':'private service'},ensure_ascii=False))

if __name__=='__main__':main()
