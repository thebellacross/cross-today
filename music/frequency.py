"""Measured frequency/spatial relationships; none of these is a quality score."""
import numpy as np

ANALYSIS_VERSION='partial-space-1'
EXTRA_FEATURES=['shared_partials','nearby_partials','simple_ratio_proximity','register_distance','band_space_distance','channel_correlation','shared_partials_in_space','foreground_partial_friction']
OPERATION_SUPPORT={'frequency-shift':'independent analytic signal per native channel; shared Hz shift, duration preserved',
                   'spectral-space':'smooth frequency-dependent stereo balance; no mono collapse or event retiming'}

def descriptors(part,rate):
    """8192-point stereo-energy spectrum, not a fundamental/pitch classifier."""
    size=8192;x=np.asarray(part,float)
    if x.ndim==1:x=x[:,None]
    x=np.pad(x[:size],((0,max(0,size-len(x))),(0,0)))
    spectrum=np.fft.rfft(x*np.hanning(size)[:,None],axis=0);power=np.abs(spectrum)**2
    energy=power.mean(axis=1);hz=np.fft.rfftfreq(size,1/rate)
    candidates=np.flatnonzero((energy[1:-1]>energy[:-2])&(energy[1:-1]>=energy[2:]))+1
    candidates=[int(i) for i in candidates if 35<=hz[i]<=min(6000,rate*.45) and energy[i]>max(1e-14,float(energy.max())*.005)]
    chosen=[]
    for i in sorted(candidates,key=lambda i:energy[i],reverse=True):
        if all(abs(hz[i]-hz[j])>12 for j in chosen):chosen.append(i)
        if len(chosen)==8:break
    weights=np.array([energy[i] for i in chosen]);weights/=max(1e-20,float(weights.sum()))
    peaks=[]
    for i,w in zip(chosen,weights):
        left,center,right=np.log(energy[i-1:i+2]+1e-20);den=left-2*center+right
        offset=float(np.clip(.5*(left-right)/den,-.5,.5)) if abs(den)>1e-12 else 0.
        peaks.append([float((i+offset)*rate/size),float(w)])
    bands=[]
    for lo,hi in zip([0,150,500,1500,4500],[150,500,1500,4500,rate/2+1]):
        p=power[(hz>=lo)&(hz<hi)].sum(axis=0);bands.append(float((p[-1]-p[0])/(p[-1]+p[0]+1e-20)))
    corr=float(np.dot(x[:,0],x[:,-1])/(np.linalg.norm(x[:,0])*np.linalg.norm(x[:,-1])+1e-20))
    return {'partial_peaks':peaks,'band_pan':bands,'channel_correlation':corr,'relation_analysis':ANALYSIS_VERSION}

def pair_descriptors(a,b):
    if not a.get('partial_peaks') or not b.get('partial_peaks'):return None
    pa=np.array(a['partial_peaks']);pb=np.array(b['partial_peaks']);fa=pa[:,0,None];fb=pb[None,:,0];weight=pa[:,1,None]*pb[None,:,1]
    distance=np.abs(fa-fb);shared=float(np.sum(weight*np.exp(-.5*(distance/np.maximum(6,.015*np.minimum(fa,fb)))**2)))
    # 18 +/- 12 Hz proximity is an explicitly descriptive band, not a universal
    # roughness or masking model. Neither near peaks nor overlap is penalized.
    nearby=float(np.sum(weight*np.exp(-.5*((distance-18)/12)**2)))
    ratio=np.abs(np.log2(fa/fb));anchors=np.log2([1,6/5,5/4,4/3,3/2,2,3,4])
    proximity=np.min(np.abs(ratio[:,:,None]-anchors),axis=2)
    simple=float(np.sum(weight*np.exp(-.5*(proximity/.025)**2)))
    register=abs(float(np.sum(pa[:,1]*np.log2(pa[:,0]))-np.sum(pb[:,1]*np.log2(pb[:,0]))))/4
    common=np.sqrt(np.array(a['bands'])*np.array(b['bands']));spatial=float(np.sum(common*np.abs(np.array(a['band_pan'])-b['band_pan'])/2)/(common.sum()+1e-12))
    return shared,nearby,simple,register,spatial

def process(x,params,rate):
    """Pad/crop inside the recorded chain position; never extend event timing."""
    wet=float(params.get('wet',1.));kind=params['kind']
    if not 0<=wet<=1:raise ValueError('Frequency operation wet must be within 0–1.')
    if wet==0:return x.copy()
    padding=float(params.get('pad_seconds',.25))
    if not 0<=padding<=2:raise ValueError('Frequency operation padding is outside 0–2 seconds.')
    pad=round(padding*rate);size=1<<(len(x)+2*pad-1).bit_length();padded=np.pad(x,((pad,size-len(x)-pad),(0,0)))
    if kind=='frequency-shift':
        shift=float(params['shift_hz'])
        if not np.isfinite(shift) or abs(shift)>rate/8:raise ValueError('Frequency shift is outside the saved supported range.')
        if shift==0:return x.copy()
        spectrum=np.fft.fft(padded,axis=0);analytic_mask=np.zeros(size);analytic_mask[0]=analytic_mask[size//2]=1;analytic_mask[1:size//2]=2
        frequencies=np.fft.fftfreq(size,1/rate);analytic_mask[(frequencies+shift<0)|(frequencies+shift>rate/2)]=0
        analytic=np.fft.ifft(spectrum*analytic_mask[:,None],axis=0)
        moved=np.real(analytic*np.exp(2j*np.pi*shift*np.arange(size)/rate)[:,None]);y=moved[pad:pad+len(x)]
    elif kind=='spectral-space':
        low,high=map(float,params['crossovers_hz']);pans=np.array(params['band_pans'],float)
        if not 0<low<high<rate/2 or pans.shape!=(3,) or not np.isfinite(pans).all() or np.any(np.abs(pans)>1):raise ValueError('Invalid saved spectral-space parameters.')
        spectrum=np.fft.rfft(padded,axis=0);f=np.fft.rfftfreq(size,1/rate)
        lows=1/(1+(f/low)**4);highs=1-1/(1+(f/high)**4);weights=np.column_stack((lows,1-lows-highs,highs))
        left=weights@np.sqrt(1-np.maximum(0,pans));right=weights@np.sqrt(1+np.minimum(0,pans))
        y=np.fft.irfft(spectrum*np.column_stack((left,right)),n=size,axis=0)[pad:pad+len(x)]
    else:raise ValueError('Unknown frequency operation.')
    return x*(1-wet)+y*wet
