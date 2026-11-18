"""Actions orchestration. Only generated assets enter public GitHub Releases."""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .common import ROOT, canonical, digest, file_hash, save_json
from .library import import_one, ADAPTER_VERSION
from .album import create_album

class Cloud:
    def __init__(self):
        self.base=os.environ['WORKER_URL'].rstrip('/')
        if not self.base.startswith('https://') and not self.base.startswith('http://127.0.0.1:'):raise ValueError('Worker URL must use HTTPS.')
        self.run_token=os.environ['RUN_TOKEN'];self.gh_token=os.environ['GH_TOKEN'];self.repo=os.environ['GITHUB_REPOSITORY']
        self.storage_repo=os.environ.get('STORAGE_REPOSITORY','');self.storage_token=os.environ.get('STORAGE_TOKEN','');self.next_write=0
        if self.repo!='thebellacross/cross-today':raise ValueError('Unexpected repository. Explicitly update the configured owner before deployment.')
        self.run=os.environ.get('GITHUB_RUN_ID','local')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
        self.http=requests.Session();self.http.mount('https://',HTTPAdapter(max_retries=Retry(total=4,backoff_factor=2,status_forcelist=[429,500,502,503,504],allowed_methods=frozenset(['GET','HEAD','PUT']))))
    def api(self,path,method='GET',data=None,raw=None,missing=False):
        headers={'Authorization':'Bearer '+self.run_token}
        r=self.http.request(method,self.base+path,headers=headers,json=data if raw is None else None,data=raw,timeout=300)
        if missing and r.status_code==404:return None
        if not r.ok:raise RuntimeError(f'Private service request failed ({r.status_code}); credentials and source paths omitted.')
        return r.json() if 'application/json' in r.headers.get('Content-Type','') else r.content
    def gh(self,path,method='GET',data=None,raw=None,missing=False,upload=False):
        base='https://uploads.github.com' if upload else 'https://api.github.com'
        private=bool(self.storage_repo and (path=='/repos/'+self.storage_repo or path.startswith('/repos/'+self.storage_repo+'/')))
        if method not in ('GET','HEAD'):
            if private:self.api('/internal/storage/write','POST',{})
            else:
                time.sleep(max(0,self.next_write-time.monotonic()));self.next_write=time.monotonic()+1.25
        headers={'Authorization':'Bearer '+(self.storage_token if private else self.gh_token),'Accept':'application/vnd.github+json','User-Agent':'cross-today'}
        if raw is not None:headers['Content-Type']='application/octet-stream'
        r=self.http.request(method,base+path,headers=headers,json=data if raw is None else None,data=raw,timeout=300)
        if missing and r.status_code==404:return None
        if not r.ok:raise RuntimeError(f'GitHub operation failed ({r.status_code}); previous current edition is preserved.')
        return r.json() if r.content else None
    def release(self,job_id):return self.gh(f'/repos/{self.repo}/releases/tags/{job_id}',missing=True)
    def upload_assets(self,job_id,folder,album):
        release=self.release(job_id)
        if not release:release=self.gh(f'/repos/{self.repo}/releases','POST',{'tag_name':job_id,'name':album['catalog']+' '+album['title'],'draft':True,'body':'Daily generated audio by CROSS. Original source recordings are private.'})
        if not release['draft']:
            # A failure after making the Release public must never pair old media
            # with a new seed/manifest, including an explicit re-snapshot retry.
            self.verify_assets(release['id'],album)
            return release
        existing={a['name']:a for a in self.gh(f'/repos/{self.repo}/releases/{release["id"]}/assets?per_page=100')}
        for name,asset in existing.items():
            if name not in album['assets'] and name!='album.json':self.gh(f'/repos/{self.repo}/releases/assets/{asset["id"]}','DELETE')
        for name,meta in album['assets'].items():
            a=existing.get(name)
            if a and a['size']==meta['bytes'] and a.get('digest')=='sha256:'+meta['sha256']:continue
            if a:self.gh(f'/repos/{self.repo}/releases/assets/{a["id"]}','DELETE')
            with open(folder/name,'rb') as source:self.gh(f'/repos/{self.repo}/releases/{release["id"]}/assets?name={name}','POST',raw=source,upload=True)
        # Keep the generated manifest in the draft as an additional recovery record.
        if 'album.json' in existing:self.gh(f'/repos/{self.repo}/releases/assets/{existing["album.json"]["id"]}','DELETE')
        with open(folder/'album.json','rb') as source:self.gh(f'/repos/{self.repo}/releases/{release["id"]}/assets?name=album.json','POST',raw=source,upload=True)
        self.verify_assets(release['id'],album)
        return release
    def verify_assets(self,release_id,album):
        assets={a['name']:a for a in self.gh(f'/repos/{self.repo}/releases/{release_id}/assets?per_page=100')}
        for name,meta in album['assets'].items():
            a=assets.get(name)
            if not a or a['size']!=meta['bytes']:raise RuntimeError('Release is incomplete; current album was not switched.')
            if a.get('digest'):
                if a['digest']!='sha256:'+meta['sha256']:raise RuntimeError('Release checksum mismatch.')
            else:
                # Older API responses may omit digest. Verify the generated asset,
                # using the authenticated API endpoint (including draft Releases).
                headers={'Authorization':'Bearer '+self.gh_token,'Accept':'application/octet-stream','User-Agent':'cross-today'}
                with self.http.get(f'https://api.github.com/repos/{self.repo}/releases/assets/{a["id"]}',headers=headers,stream=True,timeout=300) as response:
                    if not response.ok:raise RuntimeError('Release verification failed.')
                    checksum=hashlib.sha256()
                    for chunk in response.iter_content(1024*1024):checksum.update(chunk)
                if checksum.hexdigest()!=meta['sha256']:raise RuntimeError('Release checksum mismatch.')
    def private_put(self,key,path):
        path=Path(path)
        if key.startswith(('selected/','catalog/','exports/')) and self.storage_repo:
            return self.retained_put(key,path)
        if path.stat().st_size<=32*1024*1024:
            with open(path,'rb') as f:self.api('/internal/permanent/'+key,'PUT',raw=f)
            return
        upload=self.api('/internal/objects/begin','POST',{'key':key,'bytes':path.stat().st_size})
        with path.open('rb') as f:
            part=0
            while True:
                chunk=f.read(upload['part_size'])
                if not chunk:break
                part+=1;self.api(f'/internal/objects/{upload["id"]}/part?n={part}','PUT',raw=chunk)
        self.api(f'/internal/objects/{upload["id"]}/complete','POST',{})
    def retained_put(self,key,path):
        parts=key.split('/');kind=parts[0];private=kind=='exports'
        if kind=='selected':tag='kept-'+parts[1];name=parts[2]
        elif kind=='catalog':tag='catalog-'+parts[1][6:10];name=parts[1]+'-cover-small.jpg'
        elif kind=='exports':tag='export-'+parts[1];name=parts[2]
        else:raise ValueError('Unsupported retained object')
        repo=self.storage_repo if private else self.repo
        if private:
            if not self.storage_token or self.gh('/repos/'+repo).get('private') is not True:raise RuntimeError('Private storage repository is unavailable or not private.')
        size=path.stat().st_size;checksum=file_hash(path)
        if size>=2*1024**3:raise ValueError('Release asset must be smaller than 2 GiB.')
        release=self.gh(f'/repos/{repo}/releases/tags/{tag}',missing=True)
        if not release:release=self.gh(f'/repos/{repo}/releases','POST',{'tag_name':tag,'target_commitish':'main','name':tag,'draft':False,'make_latest':'false','body':'Retained project output. Excluded from daily cleanup.'})
        asset=None
        for page in range(1,11):
            assets=self.gh(f'/repos/{repo}/releases/{release["id"]}/assets?per_page=100&page={page}')
            asset=next((a for a in assets if a['name']==name),None)
            if asset or len(assets)<100:break
        if asset:
            if asset['size']!=size or asset.get('digest')!='sha256:'+checksum:raise RuntimeError('Retained file differs from the completed upload; refusing to overwrite it.')
        else:
            with path.open('rb') as source:asset=self.gh(f'/repos/{repo}/releases/{release["id"]}/assets?name={name}','POST',raw=source,upload=True)
        if asset['size']!=size or asset.get('digest')!='sha256:'+checksum:raise RuntimeError('Retained file checksum mismatch.')
        self.api('/internal/storage/register','POST',{'key':key,'id':asset['id'],'bytes':size,'sha256':checksum})
    def download_private(self,path,target):
        headers={'Authorization':'Bearer '+self.run_token}
        head=self.http.head(self.base+path,headers=headers,timeout=120)
        if not head.ok or not head.headers.get('Content-Length'):raise RuntimeError('Private source retrieval failed.')
        size=int(head.headers['Content-Length']);offset=0
        with open(target,'wb') as output:
            while offset<size:
                end=min(size,offset+8*1024*1024)-1;received=0
                with self.http.get(self.base+path,headers={**headers,'Range':f'bytes={offset}-{end}'},stream=True,timeout=300) as response:
                    if response.status_code!=206 or response.headers.get('Content-Range')!=f'bytes {offset}-{end}/{size}':raise RuntimeError('Private source range validation failed.')
                    for chunk in response.iter_content(1024*1024):output.write(chunk);received+=len(chunk)
                if received!=end-offset+1:raise RuntimeError('Private source transfer was incomplete.')
                offset=end+1
    def material_snapshot(self,job,cache):
        clips=[]
        for source in job['sources']:
            key=digest({'source':source['hash'],'profile':dict(job['config']['import'],adapter=ADAPTER_VERSION)})
            saved=self.api(f'/internal/cache/{key}/manifest.json',missing=True)
            if isinstance(saved,bytes):saved=json.loads(saved)
            good=bool(saved)
            if saved:
                for c in saved['clips']:
                    target=cache/c['cache_file'];target.parent.mkdir(parents=True,exist_ok=True)
                    data=self.api(f'/internal/cache/{key}/{c["id"]}.wav',missing=True)
                    if data is None:good=False;break
                    target.write_bytes(data)
                    if c.get('cache_sha256') and file_hash(target)!=c['cache_sha256']:good=False;break
                    c['name']=source['name'];c['tags']=source['tags']
            if not good:
                target=ROOT/'.state/cloud-sources'/source['hash'];target.parent.mkdir(parents=True,exist_ok=True);self.download_private('/internal/sources/'+source['hash'],target)
                try:
                    saved=import_one(target,cache,job['config']['import'],name=source['name'],tags=source['tags'],expected_hash=source['hash'])
                except ValueError:
                    self.api('/internal/sources/'+source['hash'],'PUT',{'ok':False});raise RuntimeError('One selected recording failed validation; fix or disable it before a new snapshot.')
                for c in saved['clips']:
                    with open(cache/c['cache_file'],'rb') as f:self.api(f'/internal/cache/{key}/{c["id"]}.wav','PUT',raw=f)
                self.api(f'/internal/cache/{key}/manifest.json','PUT',raw=canonical(saved))
                target.unlink() # Only this ephemeral Actions download; the original remains in private cloud storage.
            self.api('/internal/sources/'+source['hash'],'PUT',{'ok':True,'clips':len(saved['clips'])});clips.extend(saved['clips'])
        clips=sorted({c['id']:c for c in clips}.values(),key=lambda c:(c['source_hash'],c['start_frame']))
        snapshot={'schema':1,'import':job['config']['import'],'clips':clips};snapshot['id']=digest(snapshot)
        if not clips:raise RuntimeError('No valid recordings; publication stopped without fallback.')
        self.api(f'/internal/permanent/snapshots/{job["id"]}.json','PUT',raw=canonical(snapshot));return snapshot
    def compose(self,job_id):
        job=self.api(f'/internal/jobs/{job_id}/claim','POST',{'run':self.run})
        if job.get('done'):return
        if job['status']=='ready':
            if job.get('publish'):self.publish(job_id,job)
            return
        folder=ROOT/'output'/job_id;cache=ROOT/'.cache/audio'
        snapshot=self.material_snapshot(job,cache)
        album=create_album(snapshot,cache,folder,int(job['seed']),job['day'],job['number'],settings=job['config'],final_override=job['final_decision'])
        self.upload_assets(job_id,folder,album)
        self.private_put(f'catalog/{job_id}/cover-small.jpg',folder/'cover-small.jpg')
        result=self.api(f'/internal/jobs/{job_id}/ready','POST',{'run':self.run,'album':album})
        if result['publish']:self.publish(job_id,{**job,'album':album})
    def publish(self,job_id,job=None):
        if job is None:job=self.api(f'/internal/jobs/{job_id}/claim','POST',{'run':self.run})
        if job.get('done'):return
        if not job.get('album'):return self.compose(job_id)
        release=self.release(job_id)
        if not release:raise RuntimeError('Prepared release is missing. The previous album remains current.')
        self.verify_assets(release['id'],job['album'])
        if release['draft']:self.gh(f'/repos/{self.repo}/releases/{release["id"]}','PATCH',{'draft':False})
        self.api(f'/internal/jobs/{job_id}/publish','POST',{'run':self.run})
        print('Published '+job_id,flush=True);self.cleanup()
    def download_generated(self,job_id,name,meta):
        # Only a known generated Release asset, never an arbitrary client URL.
        if not re.fullmatch(r'album-\d{4}-\d{2}-\d{2}',job_id) or not re.fullmatch(r'[a-z0-9.-]+',name):raise ValueError('Invalid generated asset')
        r=self.http.get(f'https://github.com/{self.repo}/releases/download/{job_id}/{name}',timeout=300);r.raise_for_status()
        if len(r.content)!=meta['bytes'] or hashlib.sha256(r.content).hexdigest()!=meta['sha256']:raise RuntimeError('Generated asset checksum mismatch')
        return r.content
    def select(self,selection_id):
        s=self.api('/internal/selections/'+selection_id)
        if s['status']=='ready':return
        try:
            track=s['track'];manifest=s['manifest'];mapping={track['wav']:'track.wav',track['src']:'track.mp3','cover.png':'cover.png','provenance.json':'provenance.json','credits.txt':'credits.txt'}
            with tempfile.TemporaryDirectory() as directory:
                for original,destination in mapping.items():
                    data=self.download_generated(s['album'],original,manifest['assets'][original])
                    if destination=='provenance.json':
                        provenance=json.loads(data);provenance['selected_track']={'album':s['album'],'n':track['n'],'title':track['title'],'seed':track['seed'],'original_wav':track['wav'],'original_mp3':track['src']};data=canonical(provenance)
                    path=Path(directory)/destination;path.write_bytes(data);self.private_put(f'selected/{selection_id}/{destination}',path)
            self.api('/internal/selections/'+selection_id,'POST',{'status':'ready'});print('Selected audio permanently saved.',flush=True)
        except Exception:
            self.api('/internal/selections/'+selection_id,'POST',{'status':'failed'});raise
    def export(self,export_id):
        e=self.api('/internal/exports/'+export_id)
        if e['status']=='ready':return
        titles=[f'{i:02d}. {s["track"]["title"]}' for i,s in enumerate(e['selections'],1)]
        common={'release.json':canonical(e['playlist']),'tracklist.txt':'\n'.join(titles).encode(),'credits.txt':((e['playlist']['title'] or 'Selected')+'\nCROSS\n\n'+'\n'.join(titles)+'\n\n'+e['playlist']['notes']).encode()}
        limit=max(64*1024**2,min(int(e.get('volume_bytes',1024**3)),1536*1024**2))
        def write(z,name,data=None,path=None):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_STORED;info.external_attr=0o644<<16
            with z.open(info,'w',force_zip64=True) as dest:
                if path:
                    with path.open('rb') as src:shutil.copyfileobj(src,dest,1024*1024)
                else:dest.write(data)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);volumes=[];z=None;total=0
            for i,s in enumerate(e['selections'],1):
                files=[]
                for name in ('track.wav','track.mp3','cover.png','provenance.json','credits.txt'):
                    path=root/(str(i)+'-'+name);self.download_private(f'/internal/permanent/selected/{s["id"]}/{name}',path);files.append((name,path))
                size=sum(p.stat().st_size for _,p in files)
                if i==1:common['cover.png']=next(p for n,p in files if n=='cover.png').read_bytes()
                if z is None or total+size>limit:
                    if z:z.close()
                    path=root/f'release-{len(volumes)+1:02d}.zip';volumes.append(path);z=zipfile.ZipFile(path,'w');total=65536
                    for name,data in common.items():write(z,name,data=data)
                for name,path in files:write(z,f'{i:02d}/{name}',path=path);total+=path.stat().st_size;path.unlink()
                write(z,f'{i:02d}/curation.txt',data=s.get('note','').encode())
            if z:z.close()
            if len(volumes)==1:
                target=root/'release.zip';volumes[0].rename(target);volumes=[target]
            for path in volumes:self.private_put(f'exports/{export_id}/{path.name}',path)
            self.api('/internal/exports/'+export_id,'POST',{'files':[p.name for p in volumes]})
        print('Curated release package ready.',flush=True)
    def cleanup(self):
        for job_id in self.api('/internal/cleanup'):
            # Retirement is atomically reserved before deleting. New selections then fail clearly.
            self.api('/internal/cleanup','POST',{'id':job_id})
            release=self.release(job_id)
            if release:self.gh(f'/repos/{self.repo}/releases/{release["id"]}','DELETE')
            self.gh(f'/repos/{self.repo}/git/refs/tags/{job_id}','DELETE',missing=True)
            self.api('/internal/cleanup','POST',{'id':job_id,'deleted':True})

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['tick','render','publish','select','export','cleanup']);p.add_argument('--job',default='');a=p.parse_args();cloud=Cloud()
    try:
        if a.mode=='tick':cloud.api('/internal/tick','POST',{})
        elif a.mode=='render':cloud.compose(a.job)
        elif a.mode=='publish':cloud.publish(a.job)
        elif a.mode=='select':cloud.select(a.job)
        elif a.mode=='export':cloud.export(a.job)
        elif a.mode=='cleanup':cloud.cleanup()
    except Exception:
        if a.mode in ('render','publish') and re.fullmatch(r'album-\d{4}-\d{2}-\d{2}',a.job):
            try:cloud.api(f'/internal/jobs/{a.job}/failed','POST',{'run':cloud.run})
            except Exception:pass
        if a.mode=='export' and re.fullmatch(r'[0-9a-f-]{36}',a.job):
            try:cloud.api(f'/internal/exports/{a.job}','POST',{'status':'failed'})
            except Exception:pass
        # Never include private API URLs, uploaded filenames or credentials in public Actions logs.
        raise SystemExit('Task failed. The management page retains the safe status and the previous published edition.')

if __name__=='__main__':main()
