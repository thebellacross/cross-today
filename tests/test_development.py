"""Technical audio fixtures; none of these judgments is user preference data."""
import copy
import json
import numpy as np
import pytest
from music.common import config,digest
from music.library import import_one,write_wav
from music.plan import plan_composition,CONTROL_DEFAULTS
from music.renderer import render_plan,read_window
from music.development import change,colour,points,VERSION
from music.preference import vector,rank,train,FEATURES,PREVIOUS_FEATURES,available_features,scoped_vector,proposals

@pytest.fixture
def source(tmp_path):
    sr=8000;t=np.arange(sr*2)/sr;clips=[];cache=tmp_path/'cache'
    for i in range(4):
        x=np.column_stack((.13*np.sin(t*(170+i*220)*2*np.pi),.1*np.sin(t*(240+i*230)*2*np.pi)))
        path=tmp_path/f'original {i}.wav';write_wav(path,(x*32767).astype('<i2'),sr)
        clips.extend(import_one(path,cache,{**config()['import'],'sample_rate':sr})['clips'])
    snapshot={'clips':clips};snapshot['id']=digest(snapshot)
    g={**config()['generation'],'sample_rate':sr,'form':'fusion','controls':{**CONTROL_DEFAULTS,'bit_damage':0.,'bus_intervention':0.},'development':{'mode':'evolving','pace':'slow'}}
    return snapshot,cache,g

def test_long_form_has_actual_overlapping_persistent_identities(source):
    snapshot,cache,g=source;p=plan_composition(snapshot,6,120,g)
    assert len(p['events'])==4 and len({e['source_hash'] for e in p['events']})==4
    assert p['events'][0]['start']==0 and p['events'][0]['duration']==120
    assert sum(e['start']<60<e['start']+e['duration'] for e in p['events'])>=3
    assert not p['rests'];assert all(s['transition']['kind']=='continuous' for s in p['sections'])
    assert all(e['source_range']['read_window']==e['transform']['read_window'] for e in p['events'])
    assert len({tuple(v for _,v in e['automation']['level']) for e in p['events']})>=3

def test_saved_curves_replay_and_controlled_focus_preserves_other_stems(source):
    snapshot,cache,g=source;p=plan_composition(snapshot,6,12,g)
    a,report,stems=render_plan(p,snapshot,cache,True)
    again,_,_=render_plan(json.loads(json.dumps(p)),snapshot,cache)
    assert np.array_equal(a,again);assert report['development_analysis']['version']==VERSION
    assert available_features(report)==len(FEATURES);assert len(scoped_vector(p,report,{'kind':'range','start':2.,'end':8.}))==len(FEATURES)
    v=change(p,'focus-exchange','voice-00',77,snapshot)
    from music.development import curve
    for s in v['sections']:
        t=(s['start']+s['end'])/2;active=[e for e in v['events'] if e['start']<=t<e['start']+e['duration']]
        assert s['foreground']==max(active,key=lambda e:float(curve(e['automation']['level'],(t-e['start'])/e['duration'])))['event_id']
    b,other,newstems=render_plan(v,snapshot,cache,True);changed=set(v['decision_log'][-1]['changed_events'])
    assert len(changed)==2 and not np.array_equal(a,b)
    for e in p['events']:
        other_event=next(r for r in v['events'] if r['event_id']==e['event_id'])
        assert e['transform']==other_event['transform'];assert e['start']==other_event['start'];assert e['duration']==other_event['duration']
        if e['event_id'] not in changed:assert np.array_equal(stems[e['event_id']],newstems[e['event_id']])
    assert vector(p,report)!=vector(v,other)
    with pytest.raises(ValueError,match='locked'):change(p,'focus-exchange','voice-00',77,snapshot,{'events':['voice-00'],'regions':[],'relations':[]})
    with pytest.raises(ValueError,match='locked'):change(p,'spectral-evolution','voice-00',77,snapshot,{'events':[],'regions':[[0,5]],'relations':[]})
    assert all(e['start']==p['events'][i]['start'] for row in proposals(p,snapshot,71,evidence=report) for i,e in enumerate(row['events']))

def test_convolution_tail_is_in_the_declared_affected_range(source):
    from music.plan import affected_bounds
    snapshot,cache,g=source;g['controls'].update(processing_intensity=1.,space_motion=0.)
    found=False
    for seed in range(40):
        p=plan_composition(snapshot,seed,10,g)
        for e in p['events']:
            if e['transform']['technique']=='room':
                found=True
                assert e['space']['tail_seconds']>=e['transform']['ir_frames']/g['sample_rate']
                assert affected_bounds(p,[e['event_id']])[1]>=e['start']+e['duration']+e['transform']['ir_frames']/g['sample_rate']
        if found:break
    assert found

def test_old_model_projection_and_no_invented_temporal_evidence():
    w=np.linspace(-.3,.5,36);old={'algorithm':'relational-bt-4','feature_names':PREVIOUS_FEATURES,'label_origin':'human','weights':w.tolist(),'ensemble':[w.tolist()],'families':3,'labels':4}
    a=np.linspace(0,1,36);b=a[::-1];base=[{'id':'a','features':a.tolist()},{'id':'b','features':b.tolist()}]
    extended=[{'id':'a','features':a.tolist()+[2.]*8},{'id':'b','features':b.tolist()+[-2.]*8}]
    assert rank(base,old)==rank(extended,old)
    record={'origin':'simulated','profile_id':'fixture','family_id':'fixture','choice':'A','features_A':extended[0]['features'],'features_B':extended[1]['features'],'available_features_A':36,'available_features_B':36}
    model=train([record],'fixture',1,allow_simulated=True)
    assert model['weights'][36:]==[0.]*8 and model['observed_feature_counts'][36:]==[0]*8
    model=train([{**record,'available_features_A':44,'available_features_B':44}],'fixture',2,allow_simulated=True)
    assert any(model['weights'][36:])

def test_off_controls_and_colour_identity(source):
    snapshot,cache,g=source;g['controls'].update(processing_intensity=0.,space_motion=0.,loop_activity=0.)
    p=plan_composition(snapshot,2,12,g)
    for e in p['events']:
        assert not e['transform']['read_window']['repeat'];assert e['duration']<=e['source']['seconds']
        assert all(v==1 for band in e['automation']['bands'] for _,v in band)
        assert len({v for _,v in e['automation']['pan']})==1
        assert all(v==0 for _,v in e['automation']['wet'])
    x=np.column_stack((np.arange(12),-np.arange(12)))/20
    assert np.array_equal(colour(x,8000,{'bands':[points([1,1])]*3}),x)
    y=read_window(x,np.arange(24),{'start_frame':0,'end_frame':12,'repeat':False,'crossfade_frames':0})
    assert np.array_equal(y[:12],x) and not np.any(y[12:])
