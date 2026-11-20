"""Private listening experiments and immutable model artifacts, executed by Actions."""
import copy
import json
import os
from pathlib import Path
import numpy as np
from .common import ROOT,save_json,digest,file_hash,run_audio
from .plan import plan_composition,seed_for
from .renderer import render_plan,render_event,hashlib_array
from .preference import proposals,vector,select,rank,train,scoped_vector,FEATURES,LEGACY_FEATURES,available_features
from .frequency import ANALYSIS_VERSION

def encode(audio,rate,path,wav=False,output_rate=None):
    path=Path(path);raw=path.with_suffix('.f32');raw.write_bytes(np.asarray(audio,dtype='<f4').tobytes())
    try:run_audio(['-y','-f','f32le','-ar',rate,'-ac',2,'-i',raw,'-map_metadata','-1']+(['-ar',output_rate or rate,'-c:a','pcm_s24le','-fflags','+bitexact'] if wav else ['-c:a','libmp3lame','-b:a','192k','-id3v2_version','0','-write_xing','0'])+[path])
    finally:raw.unlink(missing_ok=True)

def evaluate(plans,snapshot,cache):
    rows=[]
    for p in plans:
        audio,report,_=render_plan(p,snapshot,cache)
        rows.append({'id':p['plan_id'],'plan':p,'report':report,'audio':audio,'features':vector(p,report)})
    return rows

def generate(snapshot,cache,seed,seconds,settings,model=None,profile=None):
    profile=profile or {};settings=copy.deepcopy(settings);settings.setdefault('controls',{}).update(profile.get('rules',{}).get('controls',{}));settings['max_events']=profile.get('rules',{}).get('max_events',100)
    settings['model_version']={'id':model['id'] if model else None,'profile_id':profile.get('id'),'profile_revision':profile.get('revision',0)}
    base=plan_composition(snapshot,seed,seconds,settings,context=profile.get('id','open'))
    from .preference import constrain
    constrain(base,profile.get('rules',{}))
    baseline=evaluate([base],snapshot,cache)[0]
    plans=proposals(base,snapshot,seed,limit=settings.get('candidate_count',3),rules=profile.get('rules',{}),evidence=baseline['report']);rows=[baseline]+evaluate(plans[1:],snapshot,cache);chosen,decision=select(rows,model,seed)
    decision['continuity_rule']=profile.get('rules',{}).get('continuity',{'mode':'off'})
    row=next(r for r in rows if r['id']==chosen);row['report']['selection']=decision
    # No private profile notes, learned weights or feedback labels enter public scores.
    row['report']['model']={'id':model['id'] if model else None,'profile_id':profile.get('id'),'profile_revision':profile.get('revision',0)}
    return row['audio'],row['report']

def experiment(snapshot,cache,folder,request,settings,model=None,parent=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);seed=int(request['seed']);profile=request['profile'];g=copy.deepcopy(settings['generation']);g.setdefault('controls',{}).update(profile.get('rules',{}).get('controls',{}));g['max_events']=profile.get('rules',{}).get('max_events',100)
    g['engine_ref']=settings['engine_ref'];g['model_version']={'id':model['id'] if model else None,'profile_id':profile['id'],'profile_revision':profile.get('revision',0)}
    parent=parent or plan_composition(snapshot,seed,request.get('seconds',36),g,context=profile['id'])
    parent=copy.deepcopy(parent);origin_id=parent.get('plan_id');parent.setdefault('origin_replay',copy.deepcopy(parent.get('replay')))
    # A new operation can require a newer renderer than the inherited source
    # plan. Preserve its origin while making the exported plan replayable with
    # the engine that actually rendered these bytes.
    parent['replay']={'engine_ref':settings['engine_ref'],'engine_hash':digest({f.name:file_hash(f) for f in sorted((ROOT/'music').glob('*.py'))}),'numpy':np.__version__,'configuration':g,'model_version':g['model_version'],'parent_plan_id':origin_id}
    parent['output_sample_rate']=request.get('wave_rate',parent.get('output_sample_rate',48000));parent['locks']=request.get('locks',parent['locks']);parent.pop('plan_id',None);parent['plan_id']=digest(parent)
    actions=request.get('actions') or None
    frozen=evaluate([parent],snapshot,cache)[0]
    plans=proposals(parent,snapshot,seed,locks=parent['locks'],actions=actions,limit=3,rules=profile.get('rules',{}),targets=request.get('targets'),evidence=frozen['report'])
    if len(plans)<2:raise ValueError('No allowed variation remains. Change a decision or the explicit locks.')
    evaluated=[frozen]+evaluate(plans[1:],snapshot,cache);rows=[];heard=set()
    for row in evaluated:
        audio_id=hashlib_array(row['audio'])
        if audio_id not in heard:rows.append(row);heard.add(audio_id)
    if len(rows)<2:raise ValueError('No audible sample difference: choose another event or decision; no preference label was created.')
    baseline=rows[0]
    for row in rows:
        frozen={e['event_id']:e for e in baseline['report']['events']};now={e['event_id']:e for e in row['report']['events']};locks=parent['locks']
        for eid in locks.get('events',[]):
            if eid not in now or now[eid]['stem_hash']!=frozen[eid]['stem_hash']:raise RuntimeError('Locked event audio changed; comparison rejected.')
        for start,end in locks.get('regions',[]):
            a=round(start*parent['sample_rate']);b=round(end*parent['sample_rate'])
            if not np.array_equal(baseline['audio'][a:b],row['audio'][a:b]):raise RuntimeError('Locked audio region changed; comparison rejected.')
        changed=set(row['plan']['decision_log'][-1].get('changed_events',[])) if row['plan'].get('parent_id') else set()
        unmodified=[eid for eid in frozen if eid not in changed and eid in now]
        if any(frozen[eid]['stem_hash']!=now[eid]['stem_hash'] for eid in unmodified):raise RuntimeError('An unmodified event rerolled; comparison rejected.')
        row['report']['lock_verification']={'events':locks.get('events',[]),'regions':locks.get('regions',[]),'unmodified_stems':unmodified,'passed':True,'domain':'raw pre-audition-normalization audio'}
    for row in rows:row['features']=scoped_vector(row['plan'],row['report'],request.get('scope'))
    chosen,decision=select(rows,model,seed)
    # A static gain per version controls overall level, with one shared peak-safe ceiling.
    # It never compresses within-version dynamics. These audition gains are explicit.
    rms=[float(np.sqrt(np.mean(r['audio']**2))) for r in rows];target=min([v for v in rms if v>1e-9] or [.01]);gains=[min(4,target/max(v,1e-9)) for v in rms]
    peak=max(float(np.max(np.abs(r['audio'])))*gain for r,gain in zip(rows,gains));safety=min(1,.85/max(peak,1e-9));gains=[gain*safety for gain in gains]
    candidates=[];stem_files={};clips={c['id']:c for c in snapshot['clips']}
    save_json(folder/'snapshot.json',snapshot)
    for i,(row,gain) in enumerate(zip(rows,gains)):
        p=row['plan'];prefix=f'c{i}';audio=row['audio'];report=row['report'];report['replay']={'engine_ref':settings['engine_ref'],'code_hash':digest({f.name:file_hash(f) for f in sorted((ROOT/'music').glob('*.py'))}),'model_id':model['id'] if model else None,'config':g,'runtime':{'numpy':np.__version__,'python':__import__('platform').python_version()}}
        save_json(folder/(prefix+'-plan.json'),p);encode(audio,p['sample_rate'],folder/(prefix+'.wav'),True,p['output_sample_rate']);encode(audio*gain,p['sample_rate'],folder/(prefix+'.mp3'))
        stem_map={}
        for j,e in enumerate(p['events']):
            names={}
            for mode in ('wet','dry','source'):
                sound=render_event(e,clips,cache,p['sample_rate'],processed={'wet':True,'dry':'dry','source':False}[mode]);name=f'{prefix}-e{j}-{mode}.mp3';encode(sound,p['sample_rate'],folder/name);checksum=file_hash(folder/name)
                if checksum in stem_files:(folder/name).unlink();name=stem_files[checksum]
                else:stem_files[checksum]=name
                names[mode]=name
            stem_map[e['event_id']]=names
        report.update(stems=stem_map,audition_gain=gain,audition_method='static broadband RMS match with shared peak ceiling; no compression; raw WAV retained',model=decision,source_snapshot=snapshot['id'])
        save_json(folder/(prefix+'-report.json'),report)
        candidates.append({'id':row['id'],'family_id':p['family_id'],'parent_id':p.get('parent_id'),'prefix':prefix,'features':row['features'],'audio_hash':file_hash(folder/(prefix+'.wav')),'audition_hash':file_hash(folder/(prefix+'.mp3')),'snapshot':snapshot['id'],'duration':len(audio)/p['sample_rate'],'changes':p['decision_log'][-1] if p.get('parent_id') else {'origin':'frozen parent'},'audition_gain':gain})
    result={'runtime':{'python':__import__('platform').python_version(),'platform':__import__('platform').platform(),'numpy':np.__version__},'source_hashes':sorted(set(c['source_hash'] for c in snapshot['clips'])),'candidates':candidates,'decision':decision,'suggested':chosen,'snapshot':snapshot['id'],'engine_ref':settings['engine_ref'],'files':{p.name:{'sha256':file_hash(p),'bytes':p.stat().st_size} for p in folder.iterdir() if p.is_file()}}
    save_json(folder/'result.json',result);return result

def cloud_task(cloud,task_id):
    task=cloud.api(f'/internal/studio/tasks/{task_id}/claim','POST',{'run':cloud.run})
    if task.get('done'):return
    folder=ROOT/'output'/'studio'/task_id;folder.mkdir(parents=True,exist_ok=True)
    try:
        if task['kind']=='train':
            records=task['feedback'];loaded={}
            for f in records:
                if f.get('revoked') or f['choice'] not in ('A','B'):continue
                origin=cloud.api('/internal/studio/task/'+f['task'])
                for label,cid in zip(('A','B'),f['order']):
                    candidate=next(c for c in origin['result']['candidates'] if c['id']==cid);key=f['task']+'/'+candidate['prefix']
                    if key not in loaded:
                        blob=cloud.api('/internal/permanent/lab/'+key+'-report.json');loaded[key]=json.loads(blob) if isinstance(blob,bytes) else blob
                    report=loaded[key];f['features_'+label]=scoped_vector(report['plan'],report,f.get('scope'))
                    f['available_features_'+label]=available_features(report)
            model=train(records,task['profile']['id'],task['dataset_revision']);save_json(folder/'model.json',model);save_json(folder/'training.json',{'records':records,'dataset_revision':task['dataset_revision'],'model':model['id'],'evaluation':model['evaluation']})
            files={}
            for name in ('model.json','training.json'):
                cloud.private_put(f'lab/{task_id}/{name}',folder/name);files[name]={'sha256':file_hash(folder/name),'bytes':(folder/name).stat().st_size}
            result={'model':model,'files':files}
        else:
            cache=ROOT/'.cache/audio';parent=None;expected_parent_hash=None
            if task.get('parent_daily'):
                origin=task['parent_daily'];manifest=task['source_manifest'];blob=cloud.api('/internal/permanent/snapshots/'+origin['album']+'.json');snapshot=json.loads(blob) if isinstance(blob,bytes) else blob
                score=json.loads(cloud.download_generated(origin['album'],'score.json',manifest['assets']['score.json']));track=next(t for t in score['tracks'] if t['n']==origin['track']);parent=track.get('plan')
                if not parent:raise ValueError('Legacy summary has no composition plan')
                expected_parent_hash=manifest['assets'][next(t for t in manifest['tracks'] if t['n']==origin['track'])['wav']]['sha256'];task['wave_rate']=48000;cloud.restore_snapshot(snapshot,cache)
            elif task.get('parent'):
                origin=task['parent'];parent_task=cloud.api('/internal/studio/task/'+origin['task']);expected_parent_hash=next(c['audio_hash'] for c in parent_task['result']['candidates'] if c['id']==origin['candidate']);blob=cloud.api(f'/internal/permanent/lab/{origin["task"]}/snapshot.json');snapshot=json.loads(blob) if isinstance(blob,bytes) else blob
                blob=cloud.api(f'/internal/permanent/lab/{origin["task"]}/{origin["prefix"]}-plan.json');parent=json.loads(blob) if isinstance(blob,bytes) else blob;task['wave_rate']=parent.get('output_sample_rate',32000)
                cloud.restore_snapshot(snapshot,cache)
            else:snapshot=cloud.material_snapshot(task,cache)
            result=experiment(snapshot,cache,folder,task,task['config'],task.get('model'),parent)
            if expected_parent_hash and result['candidates'][0]['audio_hash']!=expected_parent_hash:raise ValueError('Cross-runtime replay mismatch')
            for name in result['files']:cloud.private_put(f'lab/{task_id}/{name}',folder/name)
            cloud.private_put(f'lab/{task_id}/result.json',folder/'result.json')
        cloud.api(f'/internal/studio/tasks/{task_id}/ready','POST',{'run':cloud.run,'result':result});print('Private listening task completed.',flush=True)
    except Exception as error:
        reason='Storage temporarily limited' if getattr(error,'status',None)==429 else 'Cross-runtime replay mismatch' if str(error)=='Cross-runtime replay mismatch' else 'No audible sample difference' if str(error).startswith('No audible sample difference') else 'No allowed variation' if str(error).startswith('No allowed variation') else ''
        cloud.api(f'/internal/studio/tasks/{task_id}/failed','POST',{'run':cloud.run,'reason':reason,'retry_after':getattr(error,'retry_after',0)});raise
