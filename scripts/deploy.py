"""Provision the no-card project. Never creates R2, subscriptions or paid resources.

Read-only by default; --apply deploys the reviewed project into the verified owner accounts.
Credentials travel through the OS Keychain, process environment and CLI stdin, never argv.
"""
import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from keychain_credentials import credential as keychain
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from music.common import config,save_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--message',default='Update CROSS publishing system');args=parser.parse_args()
    cfg=config();repo=cfg['github_owner']+'/'+cfg['repository'];storage_repo=keychain('STORAGE_REPOSITORY') or cfg['github_owner']+'/'+cfg['repository'].removesuffix('-daily')+'-materials'
    if repo!='thebellacross/cross-today':raise SystemExit('Review the target repository before changing deployment ownership.')
    worker_cfg=json.loads((ROOT/'worker/wrangler.jsonc').read_text())
    if cfg.get('storage',{}).get('allow_paid') is not False or cfg['storage']['backend']!='github-free' or worker_cfg.get('r2_buckets') or worker_cfg['vars'].get('STORAGE_BACKEND')!='github-free':raise SystemExit('Free-plan guard: paid storage and R2 provisioning are not authorized.')
    gh=shutil.which('gh') or str(next((ROOT/'.tools/gh').glob('*/bin/gh')))
    node=shutil.which('node') or '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
    env=dict(os.environ,GH_CONFIG_DIR=str(ROOT/'.secrets/gh'),GODEBUG='http2client=0',XDG_CONFIG_HOME=str(ROOT/'.secrets/config'),WRANGLER_LOG_PATH=str(ROOT/'.state/wrangler.log'),WRANGLER_SEND_METRICS='false')
    env['PATH']=str(Path(node).parent)+os.pathsep+env.get('PATH','');sensitive=[]
    def run(command,secret=None,check=True):
        result=subprocess.run(list(map(str,command)),input=secret,text=True,capture_output=True,cwd=ROOT,env=env)
        if check and result.returncode:
            detail=result.stdout+'\n'+result.stderr
            for value in sensitive:
                if value:detail=detail.replace(value,'[redacted]')
            (ROOT/'.state/deploy-error.txt').write_text(detail)
            raise RuntimeError('Deployment command failed: '+Path(str(command[0])).name+' '+str(command[1])+'. Sanitized diagnostics are in .state/deploy-error.txt.')
        return result
    token=keychain('GITHUB_TOKEN')
    if not token:raise SystemExit('NOT DEPLOYED: the project GitHub connection is missing.')
    sensitive.append(token);env['GH_TOKEN']=token
    session=requests.Session();session.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'bellacross-deploy'})
    session.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=2,status_forcelist=[429,500,502,503,504],allowed_methods=frozenset(['GET','HEAD']))))
    def api(path,method='GET',body=None,allow=()):
        response=session.request(method,'https://api.github.com'+path,json=body,timeout=60)
        if response.status_code in allow:return None
        if not response.ok:raise RuntimeError(f'GitHub deployment API returned {response.status_code}.')
        return response.json() if response.content else None
    profile=api('/user')
    if profile['login'].lower()!='thebellacross':raise SystemExit('NOT DEPLOYED: authenticated account is not thebellacross.')
    wrangler=[node,ROOT/'node_modules/wrangler/bin/wrangler.js']
    who=run(wrangler+['whoami'],check=False)
    accounts=list(dict.fromkeys(re.findall(r'\b[0-9a-f]{32}\b',who.stdout)))
    if who.returncode or accounts!=['1b100d3cb9abc2058a8d9a10833920c0']:raise SystemExit('NOT DEPLOYED: the verified Cloudflare account is unavailable.')
    account=accounts[0];env['CLOUDFLARE_ACCOUNT_ID']=account
    cf_token=json.loads(run(wrangler+['auth','token','--json']).stdout)['token'];sensitive.append(cf_token)
    def cf_api(path,method='GET',body=None,allow=()):
        if method!='GET' and path!='workers/subdomain':raise RuntimeError('Provisioning guard rejected an unexpected Cloudflare mutation.')
        r=requests.request(method,f'https://api.cloudflare.com/client/v4/accounts/{account}/{path}',headers={'Authorization':'Bearer '+cf_token},json=body,timeout=60)
        if method=='GET' and path.startswith('workers/subdomains/'):
            codes={e.get('code') for e in r.json().get('errors',[])}
            if 10032 in codes:return {'available':True}
            if 10031 in codes:return {'available':False}
            if r.ok:return {'available':True}
        if r.status_code in allow:return None
        if not r.ok:raise RuntimeError(f'Cloudflare account operation failed ({r.status_code}).')
        return r.json()['result']
    domain=cf_api('workers/subdomain',allow=[404])
    repository=api('/repos/'+repo,allow=[404]);private_repo=api('/repos/'+storage_repo,allow=[404])
    if repository and repository['private']:raise SystemExit('The website repository must be public for the chosen free Pages/Actions plan.')
    if private_repo and not private_repo['private']:raise SystemExit('Source storage is not private; deployment stopped before uploading anything.')
    if repository and not (ROOT/'.git').exists() and api('/repos/'+repo+'/commits?per_page=1',allow=[409]):raise SystemExit('The target repository contains history. Review it before connecting this checkout.')
    print('Verified: thebellacross GitHub connection and the authorized Cloudflare account.',flush=True)
    print('Prepared: public code/Pages repository, separate private material repository, free Worker with SQLite metadata; no R2 or subscription changes.',flush=True)
    if not args.apply:
        print('Read-only preflight complete. Use --apply to deploy the prepared project.');return
    if not repository:repository=api('/user/repos','POST',{'name':cfg['repository'],'private':False,'description':'Daily generative recordings by CROSS. Source recordings remain private.','auto_init':False,'has_issues':False,'has_wiki':False,'has_projects':False})
    if not private_repo:private_repo=api('/user/repos','POST',{'name':storage_repo.split('/')[1],'private':True,'description':'Private recording inputs and retained data for the CROSS generative music project.','auto_init':True,'has_issues':False,'has_wiki':False,'has_projects':False})
    if api('/repos/'+storage_repo)['private'] is not True:raise RuntimeError('Private repository verification failed.')
    api('/repos/'+storage_repo+'/actions/permissions','PUT',{'enabled':False})
    keychain('STORAGE_REPOSITORY',storage_repo)
    if not domain:
        for name in ('thebellacross','thebellacross-music'):
            available=cf_api('workers/subdomains/'+name)
            if available.get('available'):
                domain=cf_api('workers/subdomain','PUT',{'subdomain':name});break
        if not domain:raise RuntimeError('Choose an available free workers.dev subdomain in the official dashboard.')
    subdomain=domain['subdomain'];worker=f'https://cross-today.{subdomain}.workers.dev'
    cfg['worker_url']=worker;cfg['site_url']=f'https://{cfg["github_owner"]}.github.io/{cfg["repository"]}/'
    (ROOT/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n');save_json(ROOT/'web/public-config.json',{'api':worker,'site_url':cfg['site_url']})
    values={name:keychain(name) or keychain(name,secrets.token_urlsafe(36)) for name in ('ADMIN_TOKEN','SESSION_SECRET','RUN_TOKEN')};sensitive.extend(values.values())
    for name,value in {'RUN_TOKEN':values['RUN_TOKEN'],'STORAGE_TOKEN':token,'STORAGE_REPOSITORY':storage_repo}.items():run([gh,'secret','set',name,'--repo',repo],secret=value)
    run([gh,'variable','set','WORKER_URL','--repo',repo,'--body',worker])
    print('Repositories prepared; private Actions disabled. Deploying the Worker.',flush=True)
    deployment=run(wrangler+['deploy','--config','worker/wrangler.jsonc'])
    if worker not in deployment.stdout:raise RuntimeError('Worker deployment did not return the expected workers.dev URL.')
    run(wrangler+['secret','bulk','--config','worker/wrangler.jsonc'],secret=json.dumps({**values,'GITHUB_TOKEN':token,'STORAGE_REPOSITORY':storage_repo}))
    if not (ROOT/'.git').exists():run(['git','init','-b','main'])
    run(['git','config','user.name',profile['login']]);run(['git','config','user.email',f'{profile["id"]}+{profile["login"]}@users.noreply.github.com'])
    run(['git','add','.gitignore','.github','music','scripts','web','worker','tests','docs','config.json','requirements.txt','package.json','package-lock.json','README.md','THIRD_PARTY.md','Start Preview.command','Open Admin.command','Sync Sounds.command'])
    staged=run(['git','diff','--cached','--name-only']).stdout.splitlines()
    forbidden=('.secrets/','.state/','.cache/','.reference/','.tools/','C_SoundSource/','output/')
    if any(p.startswith(forbidden) for p in staged):raise RuntimeError('Private-file publication guard blocked the commit.')
    for name in run(['git','ls-files']).stdout.splitlines():
        data=(ROOT/name).read_bytes()
        if any(value and value.encode() in data for value in sensitive) or storage_repo.encode() in data:raise RuntimeError('Secret publication guard blocked a staged file.')
    if staged:run(['git','commit','-m',args.message])
    remote=run(['git','remote','get-url','origin'],check=False)
    if remote.returncode:run(['git','remote','add','origin','https://github.com/'+repo+'.git'])
    elif remote.stdout.strip()!='https://github.com/'+repo+'.git':raise RuntimeError('Existing Git remote differs from the authorized repository.')
    tag=run(['git','rev-parse','--verify',cfg['engine_ref']],check=False)
    if not tag.returncode and run(['git','diff','--name-only',cfg['engine_ref'],'HEAD','--','music','requirements.txt','.github/workflows/daily.yml','web/assets/artist/bellacross.jpg']).stdout.strip():raise RuntimeError('Rendering inputs changed. Set a new engine_ref before publishing changes.')
    if tag.returncode:run(['git','tag',cfg['engine_ref']])
    helper='!'+shlex.quote(gh)+' auth git-credential'
    run(['git','-c','credential.helper='+helper,'push','-u','origin','main']);run(['git','-c','credential.helper='+helper,'push','origin',cfg['engine_ref']])
    # Active SQLite objects can retain their earlier code for up to five minutes.
    # Wait for the additive upgrade endpoint; do not reset active imports to speed deployment up.
    deadline=time.monotonic()+360
    while True:
        upgrade=requests.post(worker+'/internal/config/upgrade',headers={'Authorization':'Bearer '+values['RUN_TOKEN']},json={'engine_ref':cfg['engine_ref']},timeout=45)
        if upgrade.ok and upgrade.json().get('engine_ref')==cfg['engine_ref'] and upgrade.json().get('listening_transport')=='private-transport-1':break
        if (not upgrade.ok and upgrade.status_code not in (404,409,500,502,503,504)) or time.monotonic()>=deadline:raise RuntimeError('Worker version promotion failed; existing job snapshots remain unchanged.')
        print('Waiting for the active coordinator to adopt the deployed version.',flush=True);time.sleep(15)
    if api('/repos/'+repo+'/pages',allow=[404]) is None:api('/repos/'+repo+'/pages','POST',{'build_type':'workflow'})
    api('/repos/'+repo+'/actions/workflows/pages.yml/dispatches','POST',{'ref':'main'})
    save_json(ROOT/'.state/deployment.json',{'worker':worker,'admin':worker+'/admin','site':cfg['site_url'],'repository':'https://github.com/'+repo,'backend':'github-free','state':'Pages deployment dispatched; cloud audio validation remains required'})
    print('Worker: '+worker);print('Admin: '+worker+'/admin');print('Repository: https://github.com/'+repo);print('Pages deployment dispatched. Next: verify the live site, synchronize materials and complete cloud generation.')

if __name__=='__main__':main()
