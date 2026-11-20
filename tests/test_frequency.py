"""Synthetic technical measurements. No fixtures are personal preference labels."""
import copy
import numpy as np
import pytest
from music.frequency import process,descriptors,pair_descriptors
from music.features import frames
from music.preference import FEATURES,LEGACY_FEATURES,rank,train

def tone(f,rate=8000,seconds=2):return np.sin(2*np.pi*f*np.arange(round(rate*seconds))/rate)*.1
def peak(x,rate=8000):return np.fft.rfftfreq(len(x),1/rate)[np.argmax(abs(np.fft.rfft(x)))]

def test_frequency_shift_preserves_duration_and_native_channel_relationship():
    x=np.column_stack((tone(440),tone(880)));params={'kind':'frequency-shift','shift_hz':80,'wet':1.}
    y=process(x,params,8000);assert y.shape==x.shape
    assert abs(peak(y[2000:-2000,0])-520)<1 and abs(peak(y[2000:-2000,1])-960)<1
    assert np.array_equal(y,process(x,copy.deepcopy(params),8000));assert np.array_equal(process(x,{**params,'wet':0},8000),x)
    assert np.array_equal(process(x,{**params,'shift_hz':0},8000),x)
    with pytest.raises(ValueError):process(x,{**params,'shift_hz':4000},8000)

def test_spectral_space_moves_bands_without_retiming_or_mono_collapse():
    mono=tone(220)+tone(2500);x=np.column_stack((mono,mono))
    p={'kind':'spectral-space','crossovers_hz':[350,1800],'band_pans':[-.9,0,.9],'wet':1.}
    y=process(x,p,8000);assert y.shape==x.shape
    a=descriptors(x[2000:10000],8000);b=descriptors(y[2000:10000],8000)
    assert a['band_pan'][1]==0 and a['band_pan'][3]==0
    assert b['band_pan'][1]<-.4 and b['band_pan'][3]>.4
    assert np.array_equal(process(x,{**p,'wet':0},8000),x)

def test_fine_features_distinguish_within_band_ratios_and_survive_antiphase():
    def measured(f):return frames(np.column_stack((tone(f),tone(f))),8000,fine=True)[2]
    a,b,c=measured(440),measured(660),measured(685)
    assert pair_descriptors(a,b)[2]>pair_descriptors(a,c)[2]+.2
    antiphase=descriptors(np.column_stack((tone(440),-tone(440))),8000)
    assert abs(antiphase['partial_peaks'][0][0]-440)<1 and antiphase['channel_correlation']<-.99

def test_legacy_model_projection_adds_no_invented_frequency_preferences():
    w=np.arange(len(LEGACY_FEATURES))/100
    model={'algorithm':'relational-bt-1','feature_names':LEGACY_FEATURES,'label_origin':'human','weights':w.tolist(),'families':1,'labels':1,'ensemble':[w.tolist()]}
    before=copy.deepcopy(model);a=np.linspace(0,1,len(LEGACY_FEATURES));b=a[::-1]
    old=rank([{'id':'A','features':a.tolist()},{'id':'B','features':b.tolist()}],model)
    new=rank([{'id':'A','features':[*a,*([4.]*8)]},{'id':'B','features':[*b,*([-4.]*8)]}],model)
    assert new==old and model==before

def test_frequency_feedback_learns_only_measured_human_or_isolated_test_differences():
    a=np.zeros(len(FEATURES));b=a.copy();a[22]=.8
    record={'origin':'simulated','profile_id':'fixture','family_id':'one','choice':'A','features_A':a.tolist(),'features_B':b.tolist()}
    with pytest.raises(ValueError,match='Non-human'):train([record],'fixture',1)
    model=train([record],'fixture',1,allow_simulated=True);assert model['weights'][22]>0 and model['observed_feature_counts'][22]==1
    missing=train([{**record,'available_features_A':22,'available_features_B':22}],'fixture',2,allow_simulated=True)
    assert missing['weights'][22]==0 and missing['observed_feature_counts'][22]==0
    neutral=train([{**record,'choice':'similar'}],'fixture',3,allow_simulated=True);assert neutral['labels']==0
