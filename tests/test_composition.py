"""Technical fixtures only. Generated labels never enter the owner's profile."""
import copy
import json
import numpy as np
import pytest
from music.common import config,digest,file_hash
from music.library import import_one,write_wav,read_clip
from music.plan import plan_composition,mutate,CONTROL_DEFAULTS,event
from music.renderer import render_plan,render_event,SUPPORT
from music.preference import vector,train,rank,select,FEATURES,proposals

@pytest.fixture
def materials(tmp_path):
    sr=8000;t=np.arange(sr*3)/sr;audio=np.column_stack((np.sin(t*412)*.16,np.sin(t*927)*.11));source=tmp_path/'stereo.wav';write_wav(source,(audio*32767).astype('<i2'),sr)
    settings={**config()['import'],'sample_rate':sr};cache=tmp_path/'cache';m=import_one(source,cache,settings);snapshot={'clips':m['clips'],'import':settings};snapshot['id']=digest(snapshot)
    g={**config()['generation'],'sample_rate':sr,'form':'fusion','controls':{**{k:0. for k in CONTROL_DEFAULTS},'stereo_width':1.}}
    return snapshot,cache,g,source

def test_cache_migration_preserves_legacy_and_stereo(materials):
    snapshot,cache,g,source=materials;original=file_hash(source);new=snapshot['clips'][0];x,_=read_clip(cache/new['cache_file'],True);assert x.ndim==2 and not np.allclose(x[:,0],x[:,1])
    legacy=import_one(source,cache,{k:v for k,v in snapshot['import'].items() if k!='channels'});mono=legacy['clips'][0];y,_=read_clip(cache/mono['cache_file']);assert y.ndim==1 and mono['id']!=new['id']
    assert file_hash(source)==original and file_hash(cache/new['cache_file'])==new['cache_sha256'];assert new['analysis'] and new['adapter']=='pcm16-native-3'

def test_serialized_plan_replays_and_locks_are_sample_exact(materials):
    snapshot,cache,g,_=materials;p=plan_composition(snapshot,111,12,g);base,report,stems=render_plan(p,snapshot,cache,True)
    copied=json.loads(json.dumps(p));replay,again,_=render_plan(copied,snapshot,cache);assert np.array_equal(base,replay) and report==again
    target=p['events'][-1]['event_id'];protected=p['events'][0]['event_id'];locks={'events':[protected],'regions':[[0,.1]],'relations':[]};variant=mutate(p,'delay-entry',target,9,snapshot,locks)
    changed,r,other=render_plan(variant,snapshot,cache,True);assert not np.array_equal(base,changed);assert np.array_equal(stems[protected],other[protected])
    for a,b in zip(p['events'],variant['events']):
        if a['event_id']!=target:assert a==b and np.array_equal(stems[a['event_id']],other[a['event_id']])
    lo,hi=variant['decision_log'][-1]['affected_range'];assert np.array_equal(base[:max(0,int(lo*g['sample_rate'])-2)],changed[:max(0,int(lo*g['sample_rate'])-2)])
    assert np.array_equal(base[int(hi*g['sample_rate'])+2:],changed[int(hi*g['sample_rate'])+2:])
    with pytest.raises(ValueError,match='locked'):mutate(p,'delay-entry',target,9,snapshot,{'events':[],'regions':[[0,15]],'relations':[]})
    with pytest.raises(ValueError,match='locked'):mutate(p,'delay-entry',protected,9,snapshot,locks)

def test_off_controls_and_independent_streams(materials):
    snapshot,cache,g,_=materials;p=plan_composition(snapshot,77,10,g)
    assert not p['buses'];assert all(e['transform']['technique']=='tape' and not e['transform']['operations'] and not e['space']['wet'] and e['pan']['start']==e['pan']['end'] for e in p['events'])
    repeated=mutate(p,'repeat',p['events'][0]['event_id'],101,snapshot);assert repeated['events'][:-1]==p['events']
    with pytest.raises(ValueError,match='disabled'):mutate(p,'processing',p['events'][0]['event_id'],10,snapshot)

@pytest.mark.parametrize('tech',list(SUPPORT))
def test_stereo_transform_replay_and_exact_source_offsets(materials,tech):
    snapshot,cache,g,_=materials;clips={c['id']:c for c in snapshot['clips']};clip=snapshot['clips'][0];e=event(71,'test','s0',clip,0,1,'foreground',tech,CONTROL_DEFAULTS,snapshot['clips']);e['transform']['operations']=[]
    a=render_event(e,clips,cache,8000);b=render_event(json.loads(json.dumps(e)),clips,cache,8000);assert np.array_equal(a,b);assert a.shape[1]==2 and np.isfinite(a).all()
    if tech=='tape':
        e['pan']={'start':0,'end':0};e['space'].update(width=1.,wet=0.,tail_seconds=0);e['gain']=1.;e['envelope'].update(attack=0,release=0);e['transform'].update(speed=1.,offset_frame=321);y=render_event(e,clips,cache,8000);x,_=read_clip(cache/clip['cache_file'],True);assert np.array_equal(y[:100],x[321:421])

def test_relational_features_change_when_same_material_changes_role(materials):
    snapshot,cache,g,_=materials;p=plan_composition(snapshot,42,14,g);a,report,_=render_plan(p,snapshot,cache);v=mutate(p,'depth',p['events'][0]['event_id'],3,snapshot);b,r,_=render_plan(v,snapshot,cache)
    assert p['events'][0]['source_hash']==v['events'][0]['source_hash'];assert vector(p,report)!=vector(v,r)

def test_simulated_learning_is_separate_grouped_and_reversible():
    records=[]
    for i in range(8):
        a=np.zeros(len(FEATURES));b=a.copy();a[0]=.4;a[17]=.8 if i%2 else -.8
        records.append({'id':str(i),'origin':'simulated','profile_id':'fixture','family_id':'family-'+str(i//2),'choice':'A' if i%2 else 'B','features_A':a.tolist(),'features_B':b.tolist()})
    with pytest.raises(ValueError,match='Non-human'):train(records,'fixture',1)
    model=train(records,'fixture',1,allow_simulated=True);assert model['weights'][17]>0 and model['label_origin']=='simulated-test-only';assert model['evaluation']['families']==4
    with pytest.raises(ValueError,match='simulated'):rank([{'id':'a','features':records[0]['features_A']}],model)
    empty=train([dict(f,revoked=True) for f in records],'fixture',2,allow_simulated=True);assert empty['labels']==0 and not any(empty['weights']);assert model['weights'][17]>0
    extras=[dict(records[0],choice=c) for c in ['both','neither','unknown','technical']];excluded=train(extras,'fixture',3,allow_simulated=True);assert excluded['labels']==0

def test_grouped_bootstrap_ranking_changes_in_opposite_contexts():
    records=[];pairs=[]
    for family in range(6):
        for context in (-1,1):
            a=np.zeros(len(FEATURES));b=a.copy();a[0]=.2;a[17]=context*.8
            records.append({'origin':'simulated','profile_id':'test','family_id':str(family),'choice':'A' if context==1 else 'B','features_A':a.tolist(),'features_B':b.tolist()});pairs.append([{'id':'A','features':a.tolist()},{'id':'B','features':b.tolist()}])
    model=train(records,'test',1,allow_simulated=True)
    assert rank(pairs[0],model,allow_simulated=True)[0]['id']=='B';assert rank(pairs[1],model,allow_simulated=True)[0]['id']=='A'
    assert rank(pairs[0],None)[0]['id']=='A';assert model['families']==6 and model['evaluation']['test_families']
    assert all(r['bootstrap_logit_sd'] is not None for r in rank(pairs[1],model,allow_simulated=True))
