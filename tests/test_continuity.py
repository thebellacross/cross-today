"""Isolated technical fixtures; these labels never describe the owner's taste."""
import copy
import json
import numpy as np
import pytest
from music.common import config,digest,file_hash
from music.library import import_one,write_wav
from music.plan import plan_composition,source_span
from music.renderer import render_plan,render_event
from music.continuity import activity,change,VERSION,descriptors
from music.preference import (proposals,FEATURES,FREQUENCY_FEATURES,rank,train,
                              available_features,scoped_vector)

@pytest.fixture
def gapped(tmp_path):
    rate=8000;t=np.arange(rate*4)/rate
    x=np.column_stack((.2*np.sin(t*400),.15*np.sin(t*600)));x[rate:3*rate]=0
    source=tmp_path/'recorded phrase.wav';write_wav(source,(x*32767).astype('<i2'),rate)
    settings={**{k:v for k,v in config()['import'].items() if k!='preparation'},'sample_rate':rate};cache=tmp_path/'cache';clips=import_one(source,cache,settings)['clips'];snapshot={'clips':clips,'import':settings};snapshot['id']=digest(snapshot)
    g={**config()['generation'],'sample_rate':rate,'form':'baseline','controls':{'structure_randomness':0.,'processing_intensity':0.,'bit_damage':0.,'bus_intervention':0.,'loop_activity':0.,'space_motion':0.,'dropout_probability':0.,'stereo_width':1.}}
    p=plan_composition(snapshot,2,8,g);p['events']=p['events'][:1];e=p['events'][0];e.update(start=0.,duration=8.);e['transform'].update(offset_frame=0,technique='tape');e['source_range']=source_span(clips[0],e['transform']);p['rests']=[];p.pop('plan_id');p['plan_id']=digest(p)
    return snapshot,cache,p,source

def test_activity_keeps_quiet_noise_and_antiphase_and_excludes_edges():
    t=np.arange(8000)/8000;quiet=1e-5*np.sin(t*700);x=np.column_stack((quiet,-quiet))
    m=activity(x,8000);assert m['spans']==[[0.,1.]] and not m['interior_gaps']
    silence=activity(np.zeros((16000,2)),8000);assert not silence['spans'] and not silence['interior_gaps']
    x=np.pad(x,((8000,8000),(0,0)));m=activity(x,8000);assert m['spans']==[[1.,2.]] and not m['interior_gaps']

def test_source_gap_diagnostics_and_exact_replay_without_original_edits(gapped):
    snapshot,cache,p,source=gapped;sha=file_hash(source);audio,report,_=render_plan(p,snapshot,cache)
    assert [g['cause'] for g in report['continuity']['gaps']]==['source-near-silence','source-near-silence']
    v=change(p,'phrase-connect',p['events'][0]['event_id'],99,snapshot,report,None)
    a,r,_=render_plan(v,snapshot,cache);b,again,_=render_plan(json.loads(json.dumps(v)),snapshot,cache)
    assert np.array_equal(a,b) and r==again and not np.array_equal(a,audio);assert file_hash(source)==sha
    assert all(g['seconds']<.8 for g in r['continuity']['gaps']);assert v['events'][0]['start']==0 and v['events'][0]['duration']==8
    assert v['events'][0]['source_range']['pieces'];assert not np.allclose(a[:,0],a[:,1])
    for piece in v['events'][0]['source_range']['pieces']:
        assert piece['absolute_end_frame']-piece['absolute_start_frame']==piece['source_end_frame']-piece['source_start_frame']

def test_bridge_keeps_every_existing_stem_and_rejects_tail_lock(gapped):
    snapshot,cache,p,_=gapped;base,report,stems=render_plan(p,snapshot,cache,True);target=p['events'][0]['event_id']
    v=change(p,'bridge-gap',target,9,snapshot,report,None);audio,r,s=render_plan(v,snapshot,cache,True)
    assert v['events'][:len(p['events'])]==p['events'];assert all(np.array_equal(y,s[eid]) for eid,y in stems.items());assert len(v['events'])>len(p['events'])
    lo,hi=v['decision_log'][-1]['affected_range'];sr=p['sample_rate'];assert np.array_equal(base[:max(0,round(lo*sr)-2)],audio[:max(0,round(lo*sr)-2)]);assert np.array_equal(base[round(hi*sr)+2:],audio[round(hi*sr)+2:])
    with pytest.raises(ValueError):change(p,'bridge-gap',target,9,snapshot,report,{'events':[],'regions':[[0,11]],'relations':[]})

def test_declared_and_very_quiet_continuations_are_not_automatically_filled(gapped):
    snapshot,cache,p,_=gapped;_,report,_=render_plan(p,snapshot,cache);target=p['events'][0]['event_id']
    p['rests']=[{'start':0.,'end':8.,'reason':'explicit suspension'}]
    _,r,_=render_plan(p,snapshot,cache);assert all(g['declared'] for g in r['continuity']['gaps'])
    with pytest.raises(ValueError):change(p,'bridge-gap',target,9,snapshot,r,None)
    with pytest.raises(ValueError,match='rest'):change(p,'phrase-connect',target,9,snapshot,r,None)
    p['rests']=[]
    for g in report['continuity']['gaps']:g['cause']='quiet-continuation-or-mix'
    with pytest.raises(ValueError):change(p,'bridge-gap',target,9,snapshot,report,None)

def test_explicit_proposal_rule_changes_proposals_but_not_aesthetic_labels(gapped):
    snapshot,cache,p,_=gapped;_,report,_=render_plan(p,snapshot,cache);p['controls']['structure_randomness']=1
    rules={'continuity':{'mode':'propose','min_gap_seconds':.8,'max_additions':1}}
    rows=proposals(p,snapshot,5,rules=rules,evidence=report)
    assert [r['decision_log'][-1].get('action') for r in rows[1:]]==['bridge-gap','phrase-connect']
    assert len(rows[1]['events'])==2
    p['controls']['structure_randomness']=0
    assert all(len(v['events'])==1 for v in proposals(p,snapshot,5,rules=rules,evidence=report))

def test_old_models_project_exactly_and_old_evidence_does_not_learn_gaps():
    w=np.arange(30)/100;model={'algorithm':'relational-bt-2','feature_names':FREQUENCY_FEATURES,'label_origin':'human','weights':w.tolist(),'families':1,'labels':1,'ensemble':[w.tolist()]}
    a=np.ones(30);b=np.zeros(30);before=rank([{'id':'a','features':a.tolist()},{'id':'b','features':b.tolist()}],model)
    after=rank([{'id':'a','features':[*a,*([-4]*6)]},{'id':'b','features':[*b,*([4]*6)]}],model);assert before==after
    a=np.zeros(len(FEATURES));b=a.copy();a[30]=.8
    row={'origin':'simulated','profile_id':'fixture','family_id':'one','choice':'B','features_A':a.tolist(),'features_B':b.tolist()}
    model=train([row],'fixture',1,allow_simulated=True);assert model['weights'][30]<0 and model['observed_feature_counts'][30]==1
    masked=train([{**row,'available_features_A':30,'available_features_B':30}],'fixture',2,allow_simulated=True);assert masked['weights'][30]==0 and masked['observed_feature_counts'][30]==0
    assert available_features({'continuity':{'version':VERSION}})==36;assert available_features({'relation_analysis':'partial-space-1'})==30

def test_scoped_gap_measurements_use_actual_selected_interval(gapped):
    snapshot,cache,p,_=gapped;_,r,_=render_plan(p,snapshot,cache)
    inside=scoped_vector(p,r,{'kind':'range','start':1.,'end':3.})
    sound=scoped_vector(p,r,{'kind':'range','start':3.,'end':3.8})
    assert inside[30]>.9 and sound[30]==0

def test_phrase_remains_replayable_after_duration_and_material_changes(gapped):
    from music.plan import mutate
    snapshot,cache,p,_=gapped;_,r,_=render_plan(p,snapshot,cache);target=p['events'][0]['event_id'];v=change(p,'phrase-connect',target,9,snapshot,r,None)
    short=mutate(v,'withdraw',target,8,snapshot);n=round(short['events'][0]['duration']*p['sample_rate'])
    assert all(x['at_frame']+x['source_end_frame']-x['source_start_frame']<=n for x in short['events'][0]['transform']['phrases'])
    long=mutate(short,'continue',target,8,snapshot);a,_,_=render_plan(short,snapshot,cache);b,_,_=render_plan(long,snapshot,cache);assert not np.array_equal(a,b)
    replaced=mutate(v,'replace-material',target,8,snapshot);render_plan(replaced,snapshot,cache)

@pytest.fixture
def long_gap(gapped):
    snapshot,cache,p,source=gapped
    from music.plan import event
    # Two distinct recorded neighbours, with five seconds of arrangement silence.
    rate=p['sample_rate'];other=source.parent/'second phrase.wav';t=np.arange(rate*4)/rate
    write_wav(other,(np.column_stack((.2*np.sin(t*910),.16*np.sin(t*1050)))*32767).astype('<i2'),rate)
    clips=import_one(other,cache,snapshot['import'])['clips'];snapshot=copy.deepcopy(snapshot);snapshot['clips']+=clips;snapshot['id']=digest(snapshot['clips'])
    p=copy.deepcopy(p);p['duration']=8.;p['snapshot']=snapshot['id']
    p['events']=[event(2,'left','s00',snapshot['clips'][0],0,1,'foreground','tape',p['controls'],snapshot['clips']),
                 event(2,'right','s00',clips[0],6,2,'foreground','tape',p['controls'],snapshot['clips'])]
    for e in p['events']:e['transform']['offset_frame']=0;e['source_range']=source_span(next(c for c in snapshot['clips'] if c['id']==e['source_id']),e['transform'])
    p.pop('plan_id');p['plan_id']=digest(p)
    return snapshot,cache,p,source

@pytest.mark.parametrize('action,count',[('sustain-gap',1),('handoff-gap',2)])
def test_long_connections_use_neighbours_replay_and_keep_original_audio(long_gap,action,count):
    snapshot,cache,p,source=long_gap;original=file_hash(source);base,report,stems=render_plan(p,snapshot,cache,True)
    assert max(g['seconds'] for g in report['continuity']['gaps'])>=5
    v=change(p,action,'left',99,snapshot,report,None)
    audio,again,new_stems=render_plan(v,snapshot,cache,True)
    replay,replayed,_=render_plan(json.loads(json.dumps(v)),snapshot,cache,True)
    assert np.array_equal(audio,replay) and again==replayed
    assert v['events'][:2]==p['events'] and len(v['events'])==2+count
    assert all(np.array_equal(y,new_stems[eid]) for eid,y in stems.items())
    assert all(g['seconds']<.4 for g in again['continuity']['gaps'])
    assert [e['relation_to'] for e in v['events'][2:]]==(['left'] if count==1 else ['left','right'])
    assert all(e['decision']['neighbours']==['left','right'] for e in v['events'][2:])
    assert file_hash(source)==original
    lo,hi=v['decision_log'][-1]['affected_range'];sr=p['sample_rate']
    assert np.array_equal(base[:max(0,round(lo*sr)-2)],audio[:max(0,round(lo*sr)-2)])
    assert np.array_equal(base[round(hi*sr)+2:],audio[round(hi*sr)+2:])

@pytest.mark.parametrize('action',['sustain-gap','handoff-gap'])
def test_connections_respect_target_region_locks_and_declared_space(long_gap,action):
    snapshot,cache,p,_=long_gap;_,r,_=render_plan(p,snapshot,cache)
    for kw in [{'locks':{'events':['right'],'regions':[],'relations':[]}},
               {'locks':{'events':[],'regions':[[1,6]],'relations':[]}},
               {'locks':None,'targets':['unrelated']},
               {'locks':None,'scope':{'kind':'range','start':2,'end':5}}]:
        with pytest.raises(ValueError):change(p,action,'left',99,snapshot,r,**kw)
    for g in r['continuity']['gaps']:g['declared']=True
    with pytest.raises(ValueError):change(p,action,'left',99,snapshot,r,None)
    for g in r['continuity']['gaps']:g.update(declared=False,cause='quiet-continuation-or-mix')
    with pytest.raises(ValueError):change(p,action,'left',99,snapshot,r,None)

def test_explicit_slight_preference_is_weighted_and_old_model_remains_exact():
    a=np.zeros(len(FEATURES));a[0]=1.;b=np.zeros(len(FEATURES))
    row={'origin':'simulated','profile_id':'fixture','family_id':'one','choice':'A','features_A':a.tolist(),'features_B':b.tolist()}
    normal=train([row],'fixture',1,allow_simulated=True)
    slight=train([{**row,'strength':'slight'}],'fixture',2,allow_simulated=True)
    assert 0<slight['weights'][0]<normal['weights'][0]
    assert normal['effective_label_weight']==1 and slight['effective_label_weight']==.5
    for choice in ['both','neither','similar','unknown','technical']:
        assert train([{**row,'choice':choice,'strength':'slight'}],'fixture',3,allow_simulated=True)['labels']==0
    with pytest.raises(ValueError):train([{**row,'strength':'very'}],'fixture',3,allow_simulated=True)
    assert train([{**row,'revoked':True}],'fixture',4,allow_simulated=True)['labels']==0
    candidates=[{'id':'a','features':a.tolist()},{'id':'b','features':b.tolist()}]
    from music.preference import PREVIOUS_FEATURES
    old={**normal,'algorithm':'relational-bt-3','feature_names':PREVIOUS_FEATURES,'weights':normal['weights'][:36],'ensemble':[w[:36] for w in normal['ensemble']]}
    assert rank(candidates,old,True)==rank(candidates,normal,True)

def test_audition_only_removes_shared_exact_zero_suffix():
    from music.studio import audition_end
    a=np.zeros((1000,2));b=a.copy();a[:100]=.1;b[200:300]=.1
    rows=[{'audio':a,'plan':{'rests':[]}},{'audio':b,'plan':{'rests':[]}}]
    assert audition_end(rows,100)==350
    # Very quiet tails and intentional silence stay intact, irrespective of RMS.
    b[899]=1e-20;assert audition_end(rows,100)==1000
    b[899]=0;rows[0]['plan']['rests']=[{'start':3,'end':10}]
    assert audition_end(rows,100)==1000
