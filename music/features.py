"""Descriptive, time-resolved measurements. No descriptor is an aesthetic error."""
import numpy as np

def frames(audio, rate, hop_seconds=.25, fine=False, musical=False):
    x=np.asarray(audio,float)
    if x.ndim==1:x=x[:,None]
    mono=x.mean(axis=1);hop=max(1,round(rate*hop_seconds));size=min(2048,max(32,len(x)))
    frequency=np.fft.rfftfreq(size,1/rate);edges=[0,150,500,1500,4500,rate/2+1]
    result=[];previous=None
    for at in range(0,len(x),hop):
        part=x[at:at+hop];window=np.pad(mono[at:at+size],(0,max(0,size-len(mono[at:at+size]))))*np.hanning(size)
        spectrum=np.abs(np.fft.rfft(window))+1e-12;power=spectrum*spectrum;norm=power/power.sum()
        rms=float(np.sqrt(np.mean(part*part)));bands=[float(norm[(frequency>=lo)&(frequency<hi)].sum()) for lo,hi in zip(edges[:-1],edges[1:])]
        side=float(np.sqrt(np.mean(((part[:,0]-part[:,-1])*.5)**2)))
        result.append({'t':round(at/rate,6),'rms':rms,'centroid':float(np.dot(frequency,norm)/max(rate/2,1)),
                       'flatness':float(np.exp(np.log(spectrum).mean())/spectrum.mean()),'flux':float(np.maximum(norm-(previous if previous is not None else norm),0).sum()),
                       'crest':float(np.max(np.abs(part))/(rms+1e-9)),'side_ratio':side/(rms+1e-9),'bands':bands})
        if fine:
            from .frequency import descriptors
            result[-1].update(descriptors(x[at:at+8192],rate))
        if musical:
            from .musical import pitch_frame
            result[-1]['pitch']=pitch_frame(x[at:at+max(8192,round(rate*.52))],rate)
        previous=norm
    return result

def summary(rows):
    if not rows:return dict(rms=0.,centroid=0.,flatness=0.,flux=0.,crest=0.,side_ratio=0.,bands=[0.]*5)
    return {k:np.mean([r[k] for r in rows],axis=0).tolist() for k in ('rms','centroid','flatness','flux','crest','side_ratio','bands')}
