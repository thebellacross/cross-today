"""Audio and arrangement invariants, not synthetic personal preference labels."""
import copy
import json
import numpy as np
import pytest
from music.common import config, digest
from music.library import import_one, write_wav
from music.plan import plan_composition, affected_bounds
from music.renderer import render_plan
from music.musical import pitch_frame, affinity, materials, VERSION
from music.mixing import gain_stage, master, master_settings, sends
from music.story import change
from music.preference import FEATURES, DEVELOPED_FEATURES, rank, train, proposals, vector


@pytest.fixture
def recordings(tmp_path):
    sr = 8000; t = np.arange(6*sr)/sr; clips=[]; cache=tmp_path/'cache'
    for i, hz in enumerate([261.6256, 329.6276, 391.9954, 523.2511, 277.1826, 196., 440.]):
        envelope = .5+.5*np.sin(t*1.3+i)**2
        x=np.column_stack((np.sin(t*hz*2*np.pi),np.sin(t*hz*2*np.pi+.3)))*envelope[:,None]*[.002,.08,.7,.04,.09,.2,.006][i]
        path=tmp_path/f'material-{i}.wav';write_wav(path,(x*32767).astype('<i2'),sr)
        clips.extend(import_one(path,cache,{**config()['import'],'sample_rate':sr})['clips'])
    s={'clips':clips};s['id']=digest(s)
    g={**config()['generation'],'sample_rate':sr,'form':'fusion','max_events':100,
       'development':{'mode':'story','pace':'moderate'}}
    return s,cache,g,materials(s,cache)


def test_pitch_evidence_handles_noise_stereo_phase_and_musical_intervals():
    sr=8000;t=np.arange(sr)/sr
    def tone(hz):
        a=np.sin(t*hz*2*np.pi)
        return pitch_frame(np.column_stack((a,-a)),sr)
    c=tone(261.6256);g=tone(391.9954);db=tone(277.1826)
    noise=pitch_frame(np.random.default_rng(5).normal(0,.1,(sr,2)),sr)
    assert c['confidence']>.8 and np.argmax(c['chroma'])==0
    assert affinity(c,g)>affinity(c,db)+.5
    assert noise['confidence']<.22 and affinity(c,noise) is None
    assert pitch_frame(np.zeros((sr,2)),sr)['confidence']==0


def test_story_changes_actual_cast_and_density_without_whole_track_loops(recordings):
    s,cache,g,analysis=recordings
    fingerprints=set()
    for seed in range(8):
        p=plan_composition(s,seed,180,g,analysis=analysis)
        assert len(p['sections'])>=6 and len(p['events'])>12
        assert max(e['duration'] for e in p['events'])<60
        assert len({e['source_hash'] for e in p['events']})>=5
        leads=[next(e['source_hash'] for e in p['events'] if e['event_id']==section['foreground']) for section in p['sections'] if section['foreground']]
        assert len(set(leads))>=3
        assert any(e['action']=='return' and e['relation_to'] for e in p['events'])
        density=[sum(e['start']<=t<e['start']+e['duration'] for e in p['events']) for t in np.arange(180)]
        assert max(density)>=3 and min(density)<=1
        fingerprints.add((p['process'],tuple(leads)))
    assert len(fingerprints)>4


def test_level_staging_preserves_internal_dynamic_shape_and_limits_gain():
    sr=8000;t=np.arange(sr*2)/sr;x=np.column_stack([np.sin(t*300*2*np.pi)]*2)*.001
    x[sr:]*=.25
    y,r=gain_stage(x,sr,{'target_dbfs':-23.,'min_gain_db':-24.,'max_gain_db':18.})
    assert r['gain_db']==18.
    assert np.isclose(np.sqrt(np.mean(y[:sr]**2))/np.sqrt(np.mean(y[sr:]**2)),4.)
    assert np.array_equal(gain_stage(x*0,sr,{'target_dbfs':-23.,'min_gain_db':-24.,'max_gain_db':18.})[0],x*0)


def test_master_catches_peaks_without_hard_clip_or_limiter_latency():
    sr=8000;x=np.zeros((sr*2,2));x[4000]=[4.,-2.];x[8000:]=np.column_stack([np.sin(np.arange(sr)*2*np.pi*330/sr)]*2)*.03
    y,r=master(x,sr,master_settings())
    assert y.shape==x.shape and np.isfinite(y).all()
    assert np.max(np.abs(y))<=10**(-1.8/20)+1e-7
    assert abs(np.argmax(abs(y[:,0]))-4000)<4
    assert np.sqrt(np.mean(y[10000:]**2))>1e-4 and r['hard_clipped_samples']==0
    assert not np.any(y==1) and not np.any(y==-1)


def test_real_delay_and_room_tails_are_contained():
    sr=8000;x=np.zeros((800,2));x[0,0]=1
    y=sends(x,sr,{'delay':{'seconds':.1,'taps':3,'feedback':.5,'wet':.2}},.3)
    assert y[800,1]==pytest.approx(.2) and y[1600,0]==pytest.approx(.1)
    room=sends(x,sr,{'reverb':{'seconds':.3,'predelay_seconds':.02,'wet':.2,'seed':'4'}},.3)
    assert len(room)==3200 and np.any(room[800:]) and np.max(np.abs(room[-1]))==0


def test_saved_story_replays_and_single_decisions_preserve_other_stems(recordings):
    s,cache,g,analysis=recordings;p=plan_composition(s,7,24,g,analysis=analysis)
    a,report,stems=render_plan(p,s,cache,True)
    again,_,_=render_plan(json.loads(json.dumps(p)),s,cache)
    assert np.array_equal(a,again) and report['clipped_samples']==0
    assert report['musical_analysis']['version']==VERSION
    assert len(vector(p,report))==len(FEATURES)
    target=p['events'][1]['event_id'];v=change(p,'level-balance',target,8,s)
    b,_,other=render_plan(v,s,cache,True)
    assert not np.array_equal(a,b)
    for eid in stems:
        if eid!=target:assert np.array_equal(stems[eid],other[eid])
    assert affected_bounds(v,[target])==[0,27.]
    with pytest.raises(ValueError,match='locked'):
        change(p,'level-balance',target,8,s,{'events':[],'regions':[[22,23]],'relations':[]})
    candidates=proposals(p,s,7,actions=['gentler-glue'],limit=2,evidence=report)
    assert len(candidates)==2 and candidates[1]['events']==p['events']
    assert candidates[1]['mastering']!=p['mastering']


def test_previous_models_keep_rank_and_new_features_need_actual_evidence():
    n=len(DEVELOPED_FEATURES);w=np.linspace(-.3,.4,n)
    model={'algorithm':'relational-bt-5','feature_names':DEVELOPED_FEATURES,'label_origin':'human','weights':w.tolist(),'ensemble':[w.tolist()],'families':3,'labels':4}
    a=np.linspace(0,1,n).tolist();b=a[::-1]
    old=[{'id':'a','features':a},{'id':'b','features':b}]
    new=[{'id':'a','features':a+[1.]*10},{'id':'b','features':b+[-1.]*10}]
    assert rank(old,model)==rank(new,model)
    f={'origin':'simulated','profile_id':'fixture','family_id':'fixture','choice':'A','features_A':new[0]['features'],'features_B':new[1]['features'],'available_features_A':44,'available_features_B':44}
    fitted=train([f],'fixture',1,allow_simulated=True)
    assert fitted['weights'][44:]==[0.]*10 and fitted['observed_feature_counts'][44:]==[0]*10
    with pytest.raises(ValueError,match='Non-human'):
        train([f],'fixture',1)


def test_retry_manifest_only_contains_fresh_declared_assets(recordings,tmp_path):
    from music.studio import experiment
    from music.common import file_hash
    s,cache,g,analysis=recordings;folder=tmp_path/'experiment'
    request={'seed':'7','profile':{'id':'fixture','rules':{'development':g['development']}},
             'seconds':8,'actions':['level-balance'],'scope':{'kind':'whole'}}
    settings={**config(),'generation':g}
    first=experiment(s,cache,folder,request,settings)
    (folder/'stale.mp3').write_bytes(b'old failed attempt')
    second=experiment(s,cache,folder,request,settings)
    assert first==second
    assert 'result.json' not in second['files'] and 'stale.mp3' not in second['files']
    assert all(file_hash(folder/name)==meta['sha256'] for name,meta in second['files'].items())
