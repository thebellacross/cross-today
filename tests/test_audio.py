import copy
import json
import wave
from pathlib import Path
import numpy as np
import pytest
from music.common import config,digest,file_hash,run_audio
from music.library import import_one,read_clip,write_wav
from music.engine import render,TECHNIQUES,transform

def recording(tmp_path):
    rate=32000;t=np.arange(rate*2)/rate
    stereo=np.column_stack((np.sin(2*np.pi*317*t)*.2,np.sin(2*np.pi*491*t)*.1));p=tmp_path/'original.wav';write_wav(p,np.int16(stereo*32767),rate);return p

def test_adapter_stereo_noise_formats_and_incremental(tmp_path):
    p=recording(tmp_path);original=file_hash(p);settings=config()['import'];cache=tmp_path/'cache'
    for ext,codec in [('aif','pcm_s16be'),('mp3','libmp3lame'),('m4a','aac'),('flac','flac')]:
        other=tmp_path/('test.'+ext);run_audio(['-y','-i',p,'-c:a',codec,other]);m=import_one(other,cache,settings);x,sr=read_clip(cache/m['clips'][0]['cache_file'],native=True);assert sr==32000 and len(x)>60000
    m=import_one(p,cache,settings);clip=cache/m['clips'][0]['cache_file'];mtime=clip.stat().st_mtime_ns
    m2=import_one(p,cache,settings);assert m==m2 and clip.stat().st_mtime_ns==mtime and file_hash(p)==original
    with wave.open(str(p))as w:assert w.getnchannels()==2
    noise=tmp_path/'noise.wav';write_wav(noise,np.random.default_rng(4).integers(-100,100,64000,dtype=np.int16),32000);assert import_one(noise,cache,settings)['clips']

def test_segment_identity_and_silent_rejection(tmp_path):
    p=recording(tmp_path);s=dict(config()['import'],segment_seconds=.5,overlap_seconds=.1);m=import_one(p,tmp_path/'cache',s)
    assert m['clips'][1]['start_frame']==12800 and m['clips'][0]['id']!=m['clips'][1]['id']
    bad=tmp_path/'empty.wav';write_wav(bad,np.zeros(3200,dtype=np.int16),32000)
    with pytest.raises(ValueError):import_one(bad,tmp_path/'cache',s)
    with pytest.raises(ValueError):import_one(p,tmp_path/'cache',s,expected_hash='0'*64)

@pytest.mark.parametrize('form',['chance','fusion','loops','baseline','fontana','automaton','drift'])
def test_forms_are_deterministic_and_use_real_recordings(tmp_path,form):
    p=recording(tmp_path);m=import_one(p,tmp_path/'cache',{k:v for k,v in config()['import'].items() if k!='channels'});g=dict(config()['generation'],form=form)
    a,score=render(m['clips'],tmp_path/'cache',901,2.5,g);b,s2=render(m['clips'],tmp_path/'cache',901,2.5,g)
    assert np.array_equal(a,b) and score==s2 and np.isfinite(a).all() and np.max(np.abs(a))>0
    assert score['events'] and all(e['source_hash']==file_hash(p) for e in score['events'])
    with pytest.raises(ValueError):render([],tmp_path,901,2,g)

@pytest.mark.parametrize('tech',TECHNIQUES+['reverse','varispeed','loop','hits','data'])
def test_sound_treatments_are_finite(tech):
    x=np.sin(np.arange(20000)*.04)*.1;y,p=transform(x,12000,tech,np.random.default_rng(1),32000)
    assert y.shape==(12000,) and np.isfinite(y).all()
