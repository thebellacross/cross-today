"""Real PCM fixtures; never owner preference labels."""
import copy
import numpy as np
import pytest
from music.common import config,file_hash,digest
from music.library import import_one,write_wav,read_clip
from music.preparation import prepare,DEFAULTS,VERSION
from music.plan import plan_composition,source_span
from music.renderer import render_plan

def test_once_before_segmentation_preserves_names_stereo_and_original_locations(tmp_path,monkeypatch):
    sr=8000;x=np.zeros((sr*60,2),dtype='<i2')
    x[:sr*10]=[3,-3];x[sr*30:sr*35]=[900,-700];x[sr*40:sr*50]=[400,600]
    source=tmp_path/'My Piano Freeze.wav';write_wav(source,x,sr);sha=file_hash(source);cache=tmp_path/'cache'
    settings={**config()['import'],'sample_rate':sr,'segment_seconds':8,'overlap_seconds':0}
    m=import_one(source,cache,settings);prep=m['preparation'];assert prep['version']==VERSION
    assert prep['prepared_frames']==round(25.05*sr) and prep['removed_frames']==len(x)-prep['prepared_frames']
    y,_=read_clip(cache/m['prepared_file'],True);assert np.array_equal(y[:sr*10],x[:sr*10]/32768)
    assert len(m['clips'])==4 and all(c['name']==source.name and c['source_hash']==sha for c in m['clips'])
    assert prep['filename']=='My Piano Freeze - prepared.wav';assert file_hash(source)==sha
    assert m['clips'][1]['source_mapping'][-1]['original_start_frame']>=30*sr-80
    def forbidden(*a,**kw):raise AssertionError('A completed unchanged source must not be scanned or decoded again')
    monkeypatch.setattr('music.preparation.prepare',forbidden);monkeypatch.setattr('music.library.segments',forbidden)
    again=import_one(source,cache,settings);assert again==m
    snapshot={'clips':m['clips'],'import':settings};snapshot['id']=digest(snapshot)
    p=plan_composition(snapshot,36,12,{**config()['generation'],'sample_rate':sr})
    a,r,_=render_plan(p,snapshot,cache);b,_,_=render_plan(copy.deepcopy(p),snapshot,cache)
    assert np.array_equal(a,b) and all('original_ranges' in e['source_range'] for e in p['events'])

def test_short_breaths_quiet_antiphase_and_stream_boundaries(tmp_path):
    sr=8000;x=np.zeros((sr*20,2),dtype='<i2');x[100:sr*2]=[1,-1];x[sr*2+sr//2:sr*4]=[2,-2];x[sr*16:]=[4,-5]
    p=tmp_path/'quiet.wav';write_wav(p,x,sr);out=tmp_path/'out.wav';m=prepare(p,out,sr,2,DEFAULTS)
    y,_=read_clip(out,True);assert np.array_equal(y[:sr*4],x[:sr*4]/32768)
    # The long zero span crosses multiple 65536-frame streaming chunks.
    assert m['removed_frames']==sr*12-160 and m['excluded']==[{'start_frame':sr*4+80,'end_frame':sr*16-80}]
    assert file_hash(p)!=file_hash(out)

def test_old_cache_is_kept_and_disabled_preparation_keeps_source_gaps(tmp_path):
    sr=8000;x=np.zeros((sr*5,2),dtype='<i2');x[:sr]=[200,300];x[-sr:]=[300,200]
    source=tmp_path/'freeze.wav';write_wav(source,x,sr);settings={**config()['import'],'sample_rate':sr};cache=tmp_path/'cache'
    old=import_one(source,cache,{k:v for k,v in settings.items() if k!='preparation'});c=old['clips'][0];old_sha=file_hash(cache/c['cache_file'])
    new=import_one(source,cache,settings);assert c['id']!=new['clips'][0]['id'];assert file_hash(cache/c['cache_file'])==old_sha
    assert old['clips'][0]['seconds']==5 and new['clips'][0]['seconds']==pytest.approx(2.02)

def test_cloud_daily_reuses_completed_prepared_material_without_decoding(tmp_path,monkeypatch):
    import json
    from music.cloud import Cloud
    sr=8000;x=np.zeros((sr*4,2),dtype='<i2');x[:sr]=[100,200];x[-sr:]=[300,400]
    source=tmp_path/'source.wav';write_wav(source,x,sr);sha=file_hash(source)
    monkeypatch.setattr('music.cloud.ROOT',tmp_path)
    class Fixture(Cloud):
        def __init__(self):self.saved={};self.downloads=0;self.states=[]
        def api(self,path,method='GET',data=None,raw=None,missing=False):
            path=path.split('?')[0]
            if '/internal/sources/' in path:self.states.append(data);return {}
            if method=='PUT':self.saved[path]=raw.read() if hasattr(raw,'read') else raw;return {}
            return self.saved.get(path)
        def download_private(self,path,target):self.downloads+=1;target.write_bytes(source.read_bytes())
    cloud=Fixture();cfg=config();cfg['import']['sample_rate']=sr
    job={'id':'preparation-fixture','sources':[{'hash':sha,'name':source.name,'tags':[]}],'config':cfg}
    first=cloud.material_snapshot(job,tmp_path/'first-cache');assert cloud.downloads==1
    assert cloud.states[-1]['preparation']['removed_frames']>0
    def forbidden(*a,**kw):raise AssertionError('Cloud generation attempted to reprocess an unchanged prepared file')
    monkeypatch.setattr('music.cloud.import_one',forbidden)
    second=cloud.material_snapshot(job,tmp_path/'fresh-runner-cache');assert second==first and cloud.downloads==1
    assert any(k.endswith('/prepared.wav') for k in cloud.saved)
