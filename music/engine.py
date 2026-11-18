"""Independent implementation of seeded tape, data, fusion and loop structures.

Behavioural reference: commit recorded in config.json. No upstream source is vendored.
All forms require at least one decoded recording; data may sound or control it.
"""
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from .library import read_clip
from .data import signal as data_signal, process, OPERATIONS

TECHNIQUES = ["mosaic", "spectral", "cross", "playhead", "room", "freeze", "weather"]

def logdraw(rng, a, b):
    return float(np.exp(rng.uniform(np.log(a), np.log(b))))


def fade(x, frames):
    m=min(max(1,frames),len(x)//2)
    if m:
        w=np.sin(np.linspace(0,np.pi/2,m))**2
        x[:m]*=w;x[-m:]*=w[::-1]
    return x

def tape(x, n, speed=1., start=0., control=None):
    velocity=np.full(n,speed) if control is None else speed*2**control
    positions=(start+np.cumsum(velocity))%len(x)
    return np.interp(positions,np.arange(len(x)),x)

def spectral(x, control, kind, rng, sr):
    size=16384 if kind in ('freeze','weather') else 2048; hop=size//4; n=len(x)
    padded=np.pad(x,(size,size)); out=np.zeros_like(padded); denom=np.zeros_like(padded)
    win=np.hanning(size)
    candidates=rng.integers(0,max(1,len(padded)-size),16)
    loud=sorted(candidates,key=lambda p:np.mean(padded[p:p+size]**2),reverse=True)[:int(rng.integers(1,5))]
    snapshots=[np.abs(np.fft.rfft(padded[p:p+size]*win)) for p in loud]
    frozen=snapshots[0]
    phase=rng.uniform(-np.pi,np.pi,len(frozen));freq=np.arange(len(frozen))
    stretch=float(rng.uniform(8,60));rule=int(rng.choice([30,90,110]));band_count=int(rng.choice([12,16,24,32,48,64,96]));cells=rng.integers(0,2,band_count,dtype=np.uint8)
    bins=np.clip(np.searchsorted(np.geomspace(40,min(16000,sr/2),band_count+1),np.fft.rfftfreq(size,1/sr))-1,0,band_count-1)
    mask=np.ones(len(freq));closed=10**(-float(rng.uniform(18,45))/20)
    for pos in range(0,len(padded)-size,hop):
        z=np.fft.rfft(padded[pos:pos+size]*win); c=control[min(n-1,max(0,pos-size))]
        if kind=="freeze":
            location=pos/max(1,len(padded)-size)*(len(snapshots)-1);left=int(location);right=min(left+1,len(snapshots)-1);frozen=snapshots[left]*(1-(location-left))+snapshots[right]*(location-left)
            phase+=2*np.pi*freq*hop/size+rng.normal(0,.002,len(freq))
            z=frozen*np.exp(1j*phase)
        elif kind=="weather":
            slow=int((pos/stretch)%(len(padded)-size));mag=np.abs(np.fft.rfft(padded[slow:slow+size]*win))
            z=mag*np.exp(1j*rng.uniform(-np.pi,np.pi,len(mag)))
        elif kind=="cross":
            mod=np.abs(np.fft.rfft(np.resize(control[max(0,pos-size):max(1,pos-size)+size],size)*win))
            mod=np.convolve(mod,np.ones(13)/13,mode="same");mod/=max(mod.max(),1e-9)
            z*=np.sqrt(mod+.01)
        else:
            q=np.roll(cells,1)*4+cells*2+np.roll(cells,-1);cells=(rule>>q)&1
            mask=.7*mask+.3*(closed+(1-closed)*cells[bins])
            z*=mask
        out[pos:pos+size]+=np.fft.irfft(z)*win;denom[pos:pos+size]+=win*win
    return (out/np.maximum(denom,1e-8))[size:size+n]

def transform(x, n, tech, rng, sr, feed=None, other=None, loop_seconds=None, creep=0.,speed_override=None):
    ctl, family=data_signal(rng,n,feed=feed)
    speed=1. if rng.random()<.3 else 2**float(rng.uniform(-2,1))
    if speed_override is not None:speed=float(speed_override)
    start=float(rng.uniform(0,len(x)))
    if tech=="reverse": x=x[::-1]
    y=tape(x,n,speed,start,ctl*.6 if tech in ("varispeed","playhead") else None)
    if tech=='playhead':
        mode=str(rng.choice(['position','position','speed','direction']))
        if mode=='position':y=np.interp((ctl+1)*.5*(len(x)-1),np.arange(len(x)),x)
        elif mode=='direction':y=np.interp((start+np.cumsum(np.where(ctl>=0,speed,-speed)))%len(x),np.arange(len(x)),x)
    if tech in ("spectral","cross","freeze","weather"):
        y=spectral(y,ctl,tech,rng,sr)
    elif tech=="mosaic":
        y=np.zeros(n);grain=int(rng.choice([512,1024,1024,2048,4096]));hop=grain//2
        material=np.r_[x,other] if other is not None else x
        offsets=np.linspace(0,max(0,len(material)-grain),min(12000,max(1,len(material)//hop))).astype(int)
        corpus=np.array([np.resize(material[i:i+grain],grain) for i in offsets]);window=np.hanning(grain)
        rms=np.log(np.sqrt(np.mean(corpus**2,axis=1))+1e-9);spectra=np.abs(np.fft.rfft(corpus*window,axis=1));centroid=(spectra*np.arange(spectra.shape[1])).sum(axis=1)/(spectra.sum(axis=1)+1e-9)
        features=np.column_stack([rms,centroid]);mean=features.mean(axis=0);std=features.std(axis=0)+1e-9;features=(features-mean)/std
        for i in range(0,n,hop):
            m=min(grain,n-i);fragment=np.resize(ctl[i:i+grain],grain);spectrum=np.abs(np.fft.rfft(fragment*window));target=np.array([np.log(np.sqrt(np.mean(fragment**2))+1e-9),np.dot(spectrum,np.arange(len(spectrum)))/(spectrum.sum()+1e-9)]);nearest=np.argsort(((features-(target-mean)/std)**2).sum(axis=1))[:int(rng.integers(1,min(4,len(features))+1))];chosen=int(rng.choice(nearest))
            y[i:i+m]+=corpus[chosen,:m]*window[:m]
    elif tech=="room":
        impulse_source=other if other is not None else x;length=min(len(impulse_source),int(sr*logdraw(rng,.3,6)))
        positions=rng.integers(0,max(1,len(impulse_source)-length),8);at=max(positions,key=lambda p:np.mean(impulse_source[p:p+length]**2))
        impulse=impulse_source[at:at+length].copy()*np.exp(-np.arange(length)/(length/5))
        impulse/=max(np.linalg.norm(impulse),1e-6)
        fftn=1<<(len(y)+len(impulse)-1).bit_length()
        wet=np.fft.irfft(np.fft.rfft(y,fftn)*np.fft.rfft(impulse,fftn),fftn)[:n]
        y=.5*y+.5*wet
    elif tech=="data":
        raw=(np.clip(x*32767,-32768,32767).astype('<i2')).tobytes()
        y,_=data_signal(rng,n,feed=raw)
    elif tech in ("loop","hits"):
        period=max(64,int(sr*(loop_seconds or logdraw(rng,.004,.4))))
        positions=rng.integers(0,max(1,len(x)-period),8);at=int(max(positions,key=lambda p:np.mean(x[p:p+period]**2)))
        frag=fade(np.resize(x[at:at+period],period).copy(),min(period//8,160))
        y=tape(frag,n,1+creep,0)
        if tech=="hits":
            mask=np.zeros(n);steps=int(rng.choice([8,12,16]));pulses=int(rng.integers(2,steps))
            for i in range(math.ceil(n/period)):
                if (i*pulses)%steps<pulses:
                    length=min(period,n-i*period);mask[i*period:i*period+length]=1
            y*=mask
    return y,{"speed":speed,"source_offset_frame":int(start),"data_family":family,"loop_seconds":loop_seconds,"phase_creep":creep}

def periods(x,sr):
    width=max(1,sr//100);length=len(x)//width
    if length<40:return []
    envelope=np.sqrt(np.mean(x[:length*width].reshape(-1,width)**2,axis=1));envelope-=envelope.mean()
    size=1<<(2*len(envelope)-1).bit_length();spectrum=np.fft.rfft(envelope,size);auto=np.fft.irfft(spectrum*spectrum.conj(),size)[:len(envelope)];auto/=max(auto[0],1e-12)
    peaks=[i for i in range(18,min(600,len(auto)-1)) if auto[i]>.2 and auto[i]>auto[i-1] and auto[i]>=auto[i+1]]
    return [(i/100,float(auto[i])) for i in sorted(peaks,key=lambda i:auto[i],reverse=True)[:5]]

def sparse_plan(form,rng,seconds,lanes,palette):
    slots=[]
    if form=='fontana':
        curves=rng.uniform(0,20,(6,9));count=min(80,max(3,int(seconds/60*rng.uniform(3,12))))
        for j,t in enumerate(sorted(rng.uniform(0,max(.01,seconds-.1),count))):
            y=float(rng.uniform(0,20));d=np.array([abs(y-np.interp(t/max(seconds,.1)*8,np.arange(9),curve))/20 for curve in curves])
            slots.append({'time':float(t),'duration':min(seconds-t,.1*400**d[5]),'lane':j%lanes,'clip':palette[min(len(palette)-1,int(d[0]*len(palette)))],
                          'tech':str(rng.choice(['tape','tape','varispeed','reverse','loop','data'])),'speed':2**(-2+3*d[1]),'gain':10**((-42+35*(1-d[2]))/20),'pan':float(d[3]),'depth':float(d[4]),'fade':.01})
    elif form=='automaton':
        width=max(8,lanes*4);steps=max(24,min(256,int(seconds)));rule=int(rng.choice([30,54,90,110]));row=rng.integers(0,2,width,dtype=np.uint8);grid=[]
        for _ in range(steps):grid.append(row.copy());row=(rule>>(np.roll(row,1)*4+row*2+np.roll(row,-1)))&1
        grid=np.array(grid)
        for lane in range(lanes):
            line=grid[:,lane*4];edges=np.diff(np.r_[0,line,0].astype(int));begins=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
            for start,end in zip(begins,ends):slots.append({'time':start/steps*seconds,'duration':(end-start)/steps*seconds,'lane':lane,'clip':int(rng.choice(palette)),'tech':'tape','depth':float(rng.uniform(.1,.7)),'fade':.02})
    else:
        knots=rng.uniform(.15,1,9)
        for lane in range(lanes):
            t=float(rng.uniform(0,min(seconds/3,3)))
            while t<seconds-.05:
                density=np.interp(t/seconds*8,np.arange(9),knots);duration=min(seconds-t,logdraw(rng,.3,30))
                slots.append({'time':t,'duration':duration,'lane':lane,'clip':int(rng.choice(palette)),'tech':str(rng.choice(['tape','varispeed','reverse'])),'depth':float(rng.uniform(.1,.6)),'fade':min(2,duration/3)})
                t+=duration+logdraw(rng,.2,10)*(1-density)
    if not slots:slots=[{'time':0,'duration':seconds,'lane':0,'clip':palette[0],'tech':'tape','depth':0,'fade':.01}]
    return slots

def loop_plan(rng,seconds,palette,audio,sr):
    def idea(tries,bar=None):
        candidates=[]
        for _ in range(tries):
            clip=int(rng.choice(palette));x=audio(clip);peaks=periods(x,sr);strength=peaks[0][1] if peaks else .05
            if bar is None:
                if peaks and rng.random()<.85:
                    period=peaks[int(rng.integers(len(peaks)))][0];options=[period*m for m in [1,2,4,8] if .7<=period*m<=6];length=float(rng.choice(options)) if options else logdraw(rng,.7,4)
                else:length=logdraw(rng,.7,4)
            else:length=bar*float(rng.choice([.5,1,1,2]))
            feature=np.std(np.abs(x))/(np.mean(np.abs(x))+1e-9);spectrum=np.abs(np.fft.rfft(x[:min(len(x),32768)]))+1e-9;tonality=1-np.exp(np.log(spectrum).mean())/spectrum.mean()
            candidates.append((strength+feature*.2+tonality*.2,clip,length))
        return max(candidates)
    count=int(rng.choice([1,2,3],p=[.5,.35,.15])) if seconds>=100 else int(rng.choice([1,2],p=[.7,.3]))
    first=idea(5);bar=first[2];ideas=[first]+[idea(4,bar) for _ in range(count-1)];strength=np.array([x[0] for x in ideas]);lengths=seconds*strength/strength.sum()
    arc=str(rng.choice(['accumulation','erosion','revelation','acceleration','convergence','opening','arch']));slots=[];at=0.;transitions=[];max_lanes=1
    for section,(score,clip,period) in enumerate(ideas):
        span=float(lengths[section]);extras=int(rng.integers(1,4));max_lanes=max(max_lanes,1+extras)
        for lane in range(extras+1):
            layer='main' if lane==0 else str(rng.choice(['phase','loop2','fused','hits']))
            ci=clip if layer!='loop2' else idea(3,bar)[1];tech='loop' if layer in ('main','phase','loop2') else str(rng.choice(TECHNIQUES)) if layer=='fused' else 'hits'
            cycle=period if layer!='loop2' else period*float(rng.choice([.25,.5,1,2]));creep=float(rng.choice([-1,1])*rng.uniform(.0015,.008)) if layer=='phase' else 0
            start=at+(lane*span/(2*(extras+1)) if arc in ('accumulation','arch') else 0);end=at+span-(lane*span/(2*(extras+1)) if arc in ('erosion','arch') else 0)
            for stage in range(4 if arc in ('acceleration','convergence') else 1):
                stages=4 if arc in ('acceleration','convergence') else 1;duration=(end-start)/stages
                slots.append({'time':start+duration*stage,'duration':duration,'lane':lane,'clip':ci,'tech':tech,'loop_seconds':cycle/2**stage if arc=='acceleration' else cycle,'creep':creep*(1-stage/3) if arc=='convergence' else creep,'depth':0 if layer in ('main','phase','loop2') else .15,'fade':.006,'opening':arc=='opening'})
        if section<count-1:transitions.append(str(rng.choice(['cut','drop','handoff','swell','crossfade'],p=[.3,.2,.2,.1,.2])))
        at+=span
    return slots,arc,max_lanes,{'bar_seconds':bar,'sections':count,'transitions':transitions}

def choose_palette(clips,rng,bounds,pure):
    if pure:return list(range(len(clips)))
    k=min(len(clips),int(rng.integers(bounds[0],bounds[1]+1))); anchor=int(rng.integers(len(clips)))
    if rng.random()<.5:
        return sorted(range(len(clips)),key=lambda i:abs(i-anchor))[:k]
    features=np.array([c['features'] for c in clips]);features=(features-features.mean(axis=0))/(features.std(axis=0)+1e-9)
    return np.argsort(((features-features[anchor])**2).sum(axis=1))[:k].tolist()

def render(clips,cache,seed,seconds,settings,age=0.,pure=False,feed=None):
    if not clips:raise ValueError("No recording materials; synthetic fallback is disabled.")
    rng=np.random.default_rng(seed);sr=settings['sample_rate'];n=int(seconds*sr)
    form=settings['form']; weights=dict(settings['forms'])
    if form=='chance':
        for k,factor in {'baseline':1+1.5*age,'fusion':1-.3*age,'automaton':1-.8*age,'drift':1-.8*age}.items():weights[k]*=factor
        probs=np.array(list(weights.values()),float);form=str(rng.choice(list(weights),p=probs/probs.sum()))
    palette=choose_palette(clips,rng,settings['palette_size'],pure)
    if form=='fusion':lanes=int(rng.choice([1,2,3,4],p=[.47,.46,.05,.02]))
    elif form=='baseline':lanes=int(rng.choice([1,2,3,4,5],p=[.09,.28,.57,.04,.02]))
    else:lanes=int(rng.integers(2,5))
    tw=np.array([1,1,1,1,.6,.6,.6]);main=str(rng.choice(TECHNIQUES,p=tw/tw.sum()))
    secondary=str(rng.choice([t for t in TECHNIQUES if t!=main])) if rng.random()<.5 else main
    p_plain=float(rng.uniform(0,.2));p_same=float(rng.uniform(.7,.95))
    arc=str(rng.choice(['none','accumulation','erosion','revelation','arch'],p=[.35,.2,.15,.15,.15])) if form=='fusion' else 'none'
    output=np.zeros((n,2));events=[];loop_bar=logdraw(rng,.8,4.)
    @lru_cache(maxsize=12)
    def audio(i):
        x,rate=read_clip(Path(cache)/clips[i]['cache_file'])
        if rate!=sr:raise ValueError('Cache sample rate does not match the render profile.')
        return x
    slots=[];form_details={}
    operations=list(rng.choice(OPERATIONS,size=int(rng.integers(2,5)),replace=False)) if not pure else OPERATIONS
    if form in ('fontana','automaton','drift'):slots=sparse_plan(form,rng,seconds,lanes,palette)
    elif form=='loops':slots,arc,lanes,form_details=loop_plan(rng,seconds,palette,audio,sr)
    else:
        if lanes==1 and arc in ('accumulation','arch'):arc='none'
        for lane in range(lanes):
            time=0. if lane==0 else float(rng.uniform(0,min(4,seconds/4)))
            pan=float(rng.uniform(.2,.8)) if lanes>1 else .5
            lane_tech=main if lane==0 else secondary
            if form=='fusion' and arc in ('accumulation','arch'):time+=lane*seconds/(lanes*2)
            end_at=seconds-lane*seconds/(lanes*2) if arc=='arch' else seconds
            while time<end_at-.05:
                i=int(rng.choice(palette));duration=min(end_at-time,logdraw(rng,12,70) if form=='fusion' else logdraw(rng,5,40));tech='tape'
                speed=1. if rng.random()<.7 else 2**float(rng.normal(0,.35))
                if form=='fusion':
                    tech='tape' if rng.random()<p_plain else lane_tech
                    if rng.random()>p_same:tech=str(rng.choice(TECHNIQUES))
                    if arc=='revelation' and time>seconds*.65:tech='tape'
                else:duration=min(duration,max(.1,clips[i]['seconds']/speed))
                xf=min(duration/3,float(rng.uniform(2,8)))
                slots.append({'time':time,'duration':duration,'lane':lane,'clip':i,'tech':tech,'pan':pan,'fade':xf,'depth':float(rng.uniform(0,.2))*(1-.5*age)+(time/seconds*.35 if arc=='erosion' else 0),'speed':speed if tech=='tape' else None})
                if time+duration>=end_at:break
                time+=max(.05,duration-xf)
        if form=='baseline' and rng.random()<.4:
            slots.append({'time':0,'duration':seconds,'lane':lanes,'clip':int(rng.choice(palette)),'tech':str(rng.choice(['freeze','weather'])),'fade':min(6,seconds/3),'gain':.04/math.sqrt(lanes),'depth':0});lanes+=1
    for slot in slots:
        time=slot['time'];duration=slot['duration'];lane=slot['lane'];i=slot['clip'];c=clips[i];tech=slot['tech'];length=max(1,int(duration*sr));start=int(time*sr);length=min(length,n-start)
        if length<=0:continue
        secondary_clip=int(rng.choice(palette)) if tech in ('room','mosaic') else None
        y,params=transform(audio(i),length,tech,rng,sr,feed,other=audio(secondary_clip) if secondary_clip is not None else None,loop_seconds=slot.get('loop_seconds'),creep=slot.get('creep',0),speed_override=slot.get('speed'))
        y,applied=process(y,rng,slot.get('depth',0),operations)
        if slot.get('opening'):
            size=2048
            for at in range(0,len(y),size):
                part=y[at:at+size];cutoff=300*(16000/300)**((time+at/sr)/seconds);freq=np.fft.rfftfreq(len(part),1/sr);y[at:at+len(part)]=np.fft.irfft(np.fft.rfft(part)/(1+(freq/max(cutoff,1))**4),n=len(part))
        fade(y,int(slot.get('fade',.02)*sr))
        gain=slot.get('gain',10**(float(rng.uniform(-20,-11))/20)/math.sqrt(lanes));pan=slot.get('pan',float(rng.uniform(.2,.8)))
        actual_pan=.5+(pan-.5)*(1 if pure else settings['stereo_width'])
        output[start:start+length,0]+=y*gain*math.cos(actual_pan*math.pi/2);output[start:start+length,1]+=y*gain*math.sin(actual_pan*math.pi/2)
        event={"start":round(time,6),"duration":length/sr,"lane":lane,"clip_id":c['id'],"source_hash":c['source_hash'],"name":c['name'],"tags":c['tags'],"segment_start":c['start'],"segment_end":c['end'],"technique":tech,"operations":applied,"gain":gain,"pan":actual_pan,**params}
        if secondary_clip is not None:event['additional_source']={k:clips[secondary_clip][k] for k in ('id','source_hash','name','start','end')}
        events.append(event)
    bends=[]
    if form in ('fusion','baseline'):
        for _ in range(int(round(logdraw(rng,.15,1.2)*seconds/60*(1-.7*age)))):
            start=int(rng.uniform(0,max(1,n-sr)));length=min(n-start,int(logdraw(rng,2,20)*sr));wet=float(rng.uniform(.3,1));operation_seed=int(rng.integers(2**62));envelope=np.hanning(length)*wet
            for channel in range(2):
                changed,ops=process(output[start:start+length,channel],np.random.default_rng(operation_seed),.9,operations);output[start:start+length,channel]*=(1-envelope);output[start:start+length,channel]+=changed*envelope
            bends.append({'start':start/sr,'duration':length/sr,'operations':ops,'wet':wet})
    # Data also acts as control and occasionally a quiet audible voice, over real recordings.
    control,kind=data_signal(rng,n,feed=feed)
    if form=='automaton':output*=((control>.0)*.8+.2)[:,None]
    elif form=='drift':output*=((control+2)/3)[:,None]
    if form=='fusion' and rng.random()<.4*(1-.6*age):
        output+=control[:,None]*10**(-40/20)*np.hanning(n)[:,None]
    if settings['garble'] and rng.random()<settings['garble']:
        begin=int(rng.uniform(.1,.7)*n);size=min(n-begin,max(1,int(sr*logdraw(rng,.1,1.5))))
        output[begin:begin+size]*=(control[begin:begin+size]>.2)[:,None]
    peak=float(np.max(np.abs(output)))
    if peak<1e-10:raise ValueError('Selected sources produced silence; publication stopped.')
    # Maintain headroom without turning every quiet recording into a loud master.
    output*=min(4.,10**(settings['peak_db']/20)/peak)
    for ch in range(2):fade(output[:,ch],min(int(sr*.025),n//5))
    ending=str(rng.choice(['fade','tape-stop','hard']))
    if ending=='fade':
        m=min(n//3,8*sr);output[-m:]*=np.linspace(1,0,m)[:,None]
    elif ending=='tape-stop':
        m=min(n//4,3*sr);positions=np.cumsum(np.linspace(1,.02,m));positions*= (m-1)/positions[-1]
        for ch in range(2):output[-m:,ch]=np.interp(positions,np.arange(m),output[-m:,ch])*np.linspace(1,0,m)
    score={"form":form,"main_technique":main if form=='fusion' else None,"arc":arc,"lanes":lanes,"palette":[clips[i]['id'] for i in palette],"pure":pure,"age":age,"data_family":kind,"ending":ending,"events":events,"bends":bends,**form_details}
    return np.clip(output,-1,1),score
