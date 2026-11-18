"""Explicit folder selection, incremental original-file synchronization to private cloud storage."""
import argparse
import getpass
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from music.library import EXTENSIONS
from music.common import config,file_hash,ROOT,save_json

def main():
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--worker',default=config()['worker_url']);p.add_argument('--keychain',action='store_true',help='Read this project\'s admin credential from the macOS login Keychain.');a=p.parse_args()
    if not a.worker.startswith('https://'):raise SystemExit('Configure the deployed HTTPS worker first.')
    if a.keychain:
        from keychain_credentials import credential
        password=credential('ADMIN_TOKEN')
        if not password:raise SystemExit('The project admin credential is not in the login Keychain yet.')
    else:password=getpass.getpass('Project admin token (hidden): ')
    session=requests.Session();session.headers['Authorization']='Bearer '+password
    session.mount('https://',HTTPAdapter(max_retries=Retry(total=5,backoff_factor=3,status_forcelist=[429,500,502,503,504],allowed_methods=frozenset(['GET','POST','PUT']))))
    base=a.worker.rstrip('/')+'/api/'
    def api(route,data):
        r=session.post(base+route,json=data,timeout=180);r.raise_for_status();return r.json()
    imported=[]
    for file in sorted(Path(a.folder).resolve().rglob('*')):
        if not file.is_file() or file.is_symlink() or file.suffix.lower() not in EXTENSIONS:continue
        sha=file_hash(file);u=api('uploads/begin',{'hash':sha,'name':file.name,'extension':file.suffix.lower(),'bytes':file.stat().st_size})
        if not u.get('exists'):
            with open(file,'rb') as source:
                n=0
                while True:
                    chunk=source.read(u['part_size'])
                    if not chunk:break
                    n+=1
                    for attempt in range(3):
                        r=session.put(base+f'uploads/{u["id"]}/part?n={n}',data=chunk,timeout=180)
                        if r.ok:break
                        if attempt==2:r.raise_for_status()
            api(f'uploads/{u["id"]}/complete',{})
        imported.append({'hash':sha,'name':file.name,'bytes':file.stat().st_size});print(f'{len(imported)} synchronized',flush=True)
        save_json(ROOT/'.state/sync.json',{'worker':a.worker,'files':imported})
    print('Synchronization complete. Original files were not changed.')

if __name__=='__main__':main()
