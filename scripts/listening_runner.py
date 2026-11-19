"""Run an immutable listening engine with separately versioned network recovery.

The engine checkout is never edited. Only idempotent service operations can be
repeated; a rejected quota reservation waits without purchasing capacity.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

import requests

ADAPTER_VERSION='private-transport-2'

def install_pinned_score_reader(cloud,task):
    if not task.get('parent_daily'):return
    previous=cloud.download_generated;album=task['parent_daily']['album']
    def read(job_id,name,meta):
        if job_id!=album or name!='score.json':return previous(job_id,name,meta)
        data=cloud.api(f'/internal/studio/tasks/{task["id"]}/daily-score')
        if not isinstance(data,bytes) or len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:raise RuntimeError('Pinned score checksum mismatch.')
        return data
    cloud.download_generated=read

def install_transport(cloud,task_id,engine_ref,workflow_commit,deadline_seconds=6000):
    original=cloud.api;deadline=time.monotonic()+deadline_seconds
    audit={'version':ADAPTER_VERSION,'workflow_commit':workflow_commit,'engine_ref':engine_ref,'network_retries':0,'quota_wait_seconds':0}
    def call(path,method='GET',data=None,raw=None,missing=False):
        task_endpoint=path in [f'/internal/studio/tasks/{task_id}/{action}' for action in ('claim','ready','failed')]
        repeatable=method in ('GET','HEAD') or (method=='POST' and (path=='/internal/storage/register' or task_endpoint))
        failures=0
        while True:
            payload=data
            if path==f'/internal/studio/tasks/{task_id}/ready' and method=='POST':
                payload=copy.deepcopy(data);payload['result']['transport_adapter']=dict(audit)
            try:return original(path,method,payload,raw=raw,missing=missing)
            except (requests.exceptions.ConnectionError,requests.exceptions.Timeout,requests.exceptions.ChunkedEncodingError):
                if not repeatable or failures>=3 or time.monotonic()>=deadline:raise
                audit['network_retries']+=1;time.sleep(2**failures);failures+=1
            except Exception as error:
                limited=getattr(error,'status',None)==429 or getattr(error,'safe_detail','')=='Private service POST returned HTTP 429'
                if path!='/internal/storage/write' or not limited or time.monotonic()>=deadline:raise
                delay=min(60,max(5,getattr(error,'retry_after',0) or 60));audit['quota_wait_seconds']+=delay
                print('Private storage quota is temporarily full; waiting with unchanged inputs.',flush=True);time.sleep(delay)
    cloud.api=call
    return audit

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--engine-root',type=Path,required=True);parser.add_argument('--engine-ref',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[0-9a-f-]{36}',args.job) or not re.fullmatch(r'engine-v\d+',args.engine_ref):raise SystemExit('Invalid frozen listening task.')
    root=args.engine_root.resolve();cfg=json.loads((root/'config.json').read_text())
    if cfg['engine_ref']!=args.engine_ref or cfg['github_owner']+'/'+cfg['repository']!='thebellacross/cross-today':raise SystemExit('Frozen engine checkout does not match the authorized task.')
    sys.path.insert(0,str(root));os.chdir(root)
    from music.cloud import Cloud,failure_diagnostic
    from music.studio import cloud_task
    from music.common import ROOT
    if ROOT.resolve()!=root:raise SystemExit('Unexpected engine module location.')
    cloud=Cloud();audit=install_transport(cloud,args.job,args.engine_ref,os.environ.get('GITHUB_SHA','local'))
    task=cloud.api('/internal/studio/task/'+args.job)
    if task['config']['engine_ref']!=args.engine_ref:raise SystemExit('Task version changed; refusing to render.')
    install_pinned_score_reader(cloud,task)
    try:cloud_task(cloud,args.job)
    except Exception as error:
        print('Diagnostic: '+failure_diagnostic(error),flush=True)
        raise SystemExit('Listening task incomplete; frozen inputs and completed assets remain retained.')
    print('Network adapter completed: '+json.dumps(audit,sort_keys=True),flush=True)

if __name__=='__main__':main()
