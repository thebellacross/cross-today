"""Deterministic stereo renderer. Every choice belongs to a saved plan or named seed."""
import math
from pathlib import Path
import numpy as np
from .common import digest,file_hash
from .library import read_clip
from .data import signal
from .engine import spectral
from .features import frames,summary
from .plan import rng_for
from .frequency import process as frequency_process,ANALYSIS_VERSION,OPERATION_SUPPORT
from .continuity import activity,diagnose
from .development import curve,colour,describe

SUPPORT={'tape':'stereo read positions preserved','reverse':'both channels reversed together','varispeed':'shared stereo read trajectory','playhead':'shared stereo read trajectory',
 'loop':'same recorded loop boundaries for both channels','hits':'same pulse mask for both channels','room':'stereo input convolved with explicitly downmixed recorded impulse',
 'mosaic':'stereo grains with shared selection','spectral':'per-channel resynthesis with shared control seed','cross':'per-channel spectral multiplication','freeze':'per-channel magnitude snapshots with shared phase stream','weather':'per-channel spectral stretch with shared phase stream','data':'explicit mono byte sonification, then duplicated','phrase':'recorded one-shot stereo ranges and crossfades; no source silence deletion'}

def stereo(x):return np.column_stack((x,x)) if x.ndim==1 else x.copy()
def read_at(x,positions):return np.column_stack([np.interp(positions%len(x),np.arange(len(x)),x[:,c]) for c in range(2)])
def read_window(x,positions,window):
    a,b=window['start_frame'],window['end_frame'];fade=window['crossfade_frames']
    if not 0<=a<b<=len(x) or not 0<=fade<=(b-a)//2:raise ValueError('Invalid persistent source window.')
    fragment=x[a:b]
    if not window['repeat']:
        y=np.zeros((len(positions),2));valid=(positions>=0)&(positions<len(fragment));y[valid]=read_at(fragment,positions[valid]);return y
    if fade:
        w=np.linspace(0,1,fade)[:,None];fragment=fragment[fade:].copy();fragment[-fade:]=x[b-fade:b]*(1-w)+x[a:a+fade]*w
    return read_at(fragment,positions)
def convolve(x,ir):
    n=len(x)+len(ir)-1;size=1<<(n-1).bit_length()
    return np.column_stack([np.fft.irfft(np.fft.rfft(x[:,c],size)*np.fft.rfft(ir,size),size)[:n] for c in range(2)])

def operation(x,p):
    y=x.copy();kind=p['kind'];integer=np.clip(y*32767,-32768,32767).astype(np.int32)
    if kind=='bitcrush':y=np.round(y*p['levels'])/p['levels']
    elif kind=='fold':y=2*np.abs((y*p['amount']+1)%4-2)-1
    elif kind=='overflow':y=((y*p['amount']+1)%2)-1
    elif kind=='xor':y=(integer^p['mask'])/32768
    elif kind=='bit-mask':y=(integer&p['mask'])/32768
    elif kind=='rotate':u=integer&65535;y=(((u<<p['shift'])|(u>>(16-p['shift'])))&65535)/32767.5-1
    elif kind=='gray':u=integer&65535;y=(u^(u>>1))/32767.5-1
    elif kind=='byte-swap':u=integer&65535;y=(((u&255)<<8)|(u>>8))/32767.5-1
    elif kind=='hold':y=y[(np.arange(len(y))//p['step'])*p['step']]
    elif kind=='filter':
        width=max(1,round(1/p['cutoff']));cs=np.vstack((np.zeros((1,2)),np.cumsum(y,axis=0)));at=np.arange(len(y));y=(cs[np.minimum(at+width,len(y))]-cs[at])/np.minimum(width,len(y)-at)[:,None]
    elif kind in ('shuffle','granulate','reverse-blocks'):
        size=p['block'];chunks=[y[i:i+size] for i in range(0,len(y),size)];r=rng_for(p['seed'],'blocks')
        if kind=='shuffle':order=r.permutation(len(chunks));chunks=[chunks[i] for i in order]
        elif kind=='granulate':chunks=[chunks[i] for i in r.integers(0,len(chunks),len(chunks))]
        else:chunks=[a[::-1] if i%2 else a for i,a in enumerate(chunks)]
        joined=np.concatenate(chunks);y=joined[np.arange(len(y))%len(joined)]
    else:raise ValueError('Unknown recorded operation.')
    # Event-local bounded scaling never renormalizes unrelated stems or the whole mix.
    if kind not in ('hold','filter','shuffle','granulate','reverse-blocks'):
        peak=max(1e-9,float(np.max(np.abs(y))));y*=min(1.,max(.02,float(np.max(np.abs(x))))/peak)
    return y

def render_event(e,clips,cache,sr,processed=True):
    clip=clips[e['source_id']];x,rate=read_clip(Path(cache)/clip['cache_file'],native=True)
    if rate!=sr:raise ValueError('Plan/cache rate mismatch.')
    x=stereo(x)
    if e['channel_mode']=='mono':x[:]=x.mean(axis=1)[:,None]
    elif e['channel_mode']!='preserve':raise ValueError('Unknown channel path.')
    p=e['transform'];n=max(1,round(e['duration']*sr));tech=p['technique'];start=p['offset_frame'];positions=start+np.arange(n)*p['speed']
    if not processed and tech!='phrase' and not p.get('read_window'):return read_at(x,start+np.arange(n))
    control=None
    if tech in ('varispeed','playhead','mosaic','spectral','cross','freeze','weather','data'):
        control,_=signal(rng_for(p['control_seed']),n)
    if tech=='reverse':positions=start-np.arange(n)*p['speed']
    if tech=='varispeed':positions=start+np.cumsum(p['speed']*2**(control*.6))
    if tech=='playhead':positions=(control+1)*.5*(len(x)-1)
    dry=read_window(x,positions,p['read_window']) if p.get('read_window') else read_at(x,positions);y=dry.copy();input_audio=dry
    if tech=='phrase':
        y=np.zeros((n,2))
        for piece in p['phrases']:
            a,b,at=(int(piece[k]) for k in ('source_start_frame','source_end_frame','at_frame'))
            if not 0<=a<b<=len(x) or at<0:raise ValueError('Recorded phrase range exceeds the source.')
            fragment=x[a:b].copy();attack=min(len(fragment)//2,piece['fade_in_frames']);release=min(len(fragment)//2,piece['fade_out_frames'])
            if attack:fragment[:attack]*=np.sin(np.linspace(0,np.pi/2,attack))[:,None]**2
            if release:fragment[-release:]*=np.sin(np.linspace(np.pi/2,0,release))[:,None]**2
            length=min(n-at,len(fragment))
            if length>0:y[at:at+length]+=fragment[:length]*piece['gain']
        input_audio=y.copy()
    elif tech in ('loop','hits'):
        period=p['period_frames'];fragment=x[start:start+period]
        if len(fragment)!=period:raise ValueError('Recorded loop range exceeds cached source.')
        y=read_window(x,np.arange(n)*(1+p['phase_creep']),p['read_window']) if p.get('read_window') else read_at(fragment,np.arange(n)*(1+p['phase_creep']));input_audio=y.copy()
        if tech=='hits':y*=np.array(p['hits_mask'])[(np.arange(n)//period)%len(p['hits_mask'])][:,None]
    elif tech in ('spectral','cross','freeze','weather'):
        wet=np.column_stack([spectral(dry[:,i],control,tech,rng_for(p['spectral_seed']),sr) for i in range(2)]);y=(1-p['wet'])*dry+p['wet']*wet
    elif tech=='mosaic':
        size=p['grain_frames'];hop=size//2;r=rng_for(p['grain_seed']);wet=np.zeros_like(y);window=np.hanning(size)
        for at in range(0,n,hop):
            origin=int(r.integers(0,max(1,len(x)-size)));grain=read_at(x,origin+np.arange(size));length=min(size,n-at);wet[at:at+length]+=grain[:length]*window[:length,None]
        y=(1-p['wet'])*dry+p['wet']*wet
    elif tech=='data':
        v,_=signal(rng_for(p['control_seed']),n,kind='files',feed=np.clip(x*32767,-32768,32767).astype('<i2').tobytes());y=(1-p['wet'])*dry+p['wet']*stereo(v)*max(.01,float(np.sqrt(np.mean(x*x))))
    if processed=='input' or not processed:return input_audio
    for op in p['operations']:y=frequency_process(y,op,sr) if op['kind'] in OPERATION_SUPPORT else operation(y,op)
    automation=e.get('automation')
    if automation:y=colour(y,sr,automation)
    attack=min(len(y)//2,round(e['envelope']['attack']*sr));release=min(len(y)//2,round(e['envelope']['release']*sr))
    if attack:y[:attack]*=np.sin(np.linspace(0,np.pi/2,attack))[:,None]**2
    if release:y[-release:]*=np.sin(np.linspace(np.pi/2,0,release))[:,None]**2
    if automation:y*=curve(automation['level'],np.arange(len(y))/max(1,n-1))[:,None]
    if processed=='dry':return y*e['gain']
    if tech=='room':
        irclip=clips[p['ir_clip_id']];impulse,irrate=read_clip(Path(cache)/irclip['cache_file'],native=True)
        if irrate!=sr:raise ValueError('Impulse cache rate mismatch.')
        impulse=stereo(impulse).mean(axis=1)[p['ir_offset_frame']:p['ir_offset_frame']+p['ir_frames']]
        impulse=impulse*np.exp(-np.arange(len(impulse))/max(1,len(impulse)/5));impulse/=max(1e-9,np.linalg.norm(impulse))
        wet=convolve(y,impulse);y=np.pad(y,((0,len(wet)-len(y)),(0,0)))*(1-p['wet'])+wet*p['wet']
    if e['space'].get('spectral'):y=frequency_process(y,e['space']['spectral'],sr)
    mid=y.mean(axis=1);side=(y[:,0]-y[:,1])*.5*e['space']['width'];y=np.column_stack((mid+side,mid-side))
    pan=curve(automation['pan'],np.arange(len(y))/max(1,n-1)) if automation else np.linspace(e['pan']['start'],e['pan']['end'],len(y));y[:,0]*=np.sqrt(1-np.maximum(0,pan));y[:,1]*=np.sqrt(1+np.minimum(0,pan))
    tail=round(e['space']['tail_seconds']*sr);out=np.pad(y,((0,max(0,n+tail-len(y))),(0,0)))
    delay=max(1,round(e['space']['delay_seconds']*sr));decay=max(.001,e['space']['decay_seconds']);wet=e['space']['wet']
    if automation:wet=curve(automation['wet'],np.arange(len(out))/max(1,n-1))[:,None]
    if np.any(wet) and tail:
        source=y.copy();out*=1-wet
        for tap in range(1,min(32,tail//delay+1)):
            at=tap*delay;length=min(len(source),len(out)-at)
            if length<=0:break
            send=wet[:length] if isinstance(wet,np.ndarray) else wet
            out[at:at+length]+=source[:length,::-1 if tap%2 else 1]*send*np.exp(-3*at/sr/decay)
    return out*e['gain']

def render_plan(plan,snapshot,cache,stems=False):
    clips={c['id']:c for c in snapshot['clips']}
    if plan['snapshot']!=snapshot['id']:raise ValueError('Plan must use its saved material snapshot.')
    checked=set()
    for e in plan['events']:
        clip=clips[e['source_id']]
        if clip['cache_sha256']!=e['source']['cache_sha256']:raise ValueError('Source identity differs from the frozen plan.')
        for cid in [e['source_id']]+([e['transform']['ir_clip_id']] if e['transform']['technique']=='room' else []):
            if cid not in checked and file_hash(Path(cache)/clips[cid]['cache_file'])!=clips[cid]['cache_sha256']:raise ValueError('Derived audio checksum differs from the frozen snapshot.')
            checked.add(cid)
    sr=plan['sample_rate'];length=round((plan['duration']+3.)*sr);mix=np.zeros((length,2));reports=[];saved={};material_activity={}
    # Stable summation order is part of replay. Adding an event never rerolls others.
    for lane,e in enumerate(sorted(plan['events'],key=lambda e:e['event_id'])):
        y=render_event(e,clips,cache,sr);start=round(e['start']*sr);size=min(len(y),length-start)
        if size<=0:continue
        mix[start:start+size]+=y[:size];measure=frames(y[:size],sr,fine=True)
        if stems:saved[e['event_id']]=y[:size]
        if e['source_id'] not in material_activity:
            raw,_=read_clip(Path(cache)/clips[e['source_id']]['cache_file'],native=True);material_activity[e['source_id']]=activity(raw,sr)
        reports.append({'event_id':e['event_id'],'section_id':e['section_id'],'start':e['start'],'duration':e['duration'],'tail_seconds':max(0,size/sr-e['duration']),'active_until':(start+size)/sr,'lane':lane,'role':e['role'],'action':e['action'],'relation_to':e['relation_to'],
            'name':e['source']['name'],'tags':e['source']['tags'],'source_hash':e['source_hash'],'clip_id':e['source_id'],'segment_start':e['source']['start_frame']/sr,'segment_end':e['source']['end_frame']/sr,'source_preparation':clip.get('preparation'),'source_time_domain':'prepared' if clip.get('preparation') else 'original','technique':e['transform']['technique'],
            'gain':e['gain'],'pan':e['pan'],'automation':e.get('automation'),'motif_id':e.get('motif_id'),'source_offset_frame':e['transform']['offset_frame'],'speed':1+e['transform']['phase_creep'] if e['transform']['technique'] in ('loop','hits') else e['transform']['speed'],
            'operations':[o['kind'] for o in e['transform']['operations']],'data_family':'seeded control','channel_policy':SUPPORT[e['transform']['technique']], 'processed_features':summary(measure),'feature_frames':measure,'stem_hash':hashlib_array(y[:size]),'activity':activity(y[:size],sr),'input_activity':activity(render_event(e,clips,cache,sr,'input'),sr)})
    for b in plan['buses']:
        a=max(0,round(b['start']*sr));z=min(length,round(b['end']*sr));phase=float(rng_for(b['operation_seed']).uniform(0,2*np.pi));gate=(np.sin(np.arange(z-a)/sr*2*np.pi/b['period']+phase)>0).astype(float);mix[a:z]*=(1-b['wet']+b['wet']*gate)[:,None]
    mix*=plan['master_gain'];end=plan['ending'];n=min(length,round(end['seconds']*sr))
    if end['kind']=='fade':mix[-n:]*=np.linspace(1,0,n)[:,None]
    elif end['kind']=='tape-stop':
        pos=np.cumsum(np.linspace(1,.02,n));pos*=(n-1)/max(1,pos[-1]);mix[-n:]=read_at(mix[-n:],pos)*np.linspace(1,0,n)[:,None]
    clipped=int(np.sum(np.abs(mix)>1));mix=np.clip(mix,-1,1)
    report={'plan_id':plan['plan_id'],'family_id':plan['family_id'],'form':plan['form'],'process':plan['process'],'lanes':len(reports),'sections':plan['sections'],'events':reports,'bends':plan['buses'],'plan':plan,'duration':length/sr,'clipped_samples':clipped,'mix_features':summary(frames(mix,sr)),'relation_analysis':ANALYSIS_VERSION}
    report['continuity']=diagnose(mix,sr,plan,reports);report['material_activity']=material_activity
    report['development_analysis']=describe(plan,report)
    return mix,report,saved

def hashlib_array(x):
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(x,dtype='<f8').tobytes()).hexdigest()
