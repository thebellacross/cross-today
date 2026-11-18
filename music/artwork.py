import colorsys
import numpy as np
from PIL import Image, ImageFilter

def analyze(x, sr):
    x=x.mean(axis=1) if x.ndim>1 else x
    window=2048
    positions=np.linspace(0,max(0,len(x)-window),min(900,max(32,len(x)//512))).astype(int)
    frames=np.array([np.pad(x[p:p+window],(0,max(0,window-len(x[p:p+window])))) for p in positions])*np.hanning(window)
    power=np.abs(np.fft.rfft(frames,axis=1))**2+1e-12
    frequencies=np.fft.rfftfreq(window,1/sr);band=(frequencies>=60)&(frequencies<=min(5500,sr/2-1));b=power[:,band]
    center=np.median((b*frequencies[band]).sum(axis=1)/b.sum(axis=1))
    rms=np.sqrt(np.mean(frames**2,axis=1))+1e-9
    values=[(np.log(max(center,1))-np.log(650))/(np.log(2000)-np.log(650)),(20*np.log10(np.sqrt(np.mean(x*x))+1e-9)+31)/10,
            (np.median(np.exp(np.mean(np.log(b),axis=1))/np.mean(b,axis=1))-.03)/.37,(np.std(rms)/np.mean(rms)-.55)/1.15]
    edges=np.geomspace(60,min(5500,sr/2-1),57)
    bands=np.array([power[:,(frequencies>=lo)&(frequencies<hi)].mean(axis=1) if np.any((frequencies>=lo)&(frequencies<hi)) else np.full(len(power),1e-12) for lo,hi in zip(edges[:-1],edges[1:])]).T
    bands=10*np.log10(bands+1e-12);low,high=np.percentile(bands,[8,99.5]);bands=np.clip((bands-low)/max(high-low,1e-9),0,1)
    return np.clip(values,0,1),bands

def palette(mood):
    bright,energy,noise,motion=map(float,mood)
    hue=(215+265*bright)%360;sat=np.clip((.28+.65*energy)*(1-.5*noise),.12,.95);light=.4+.14*bright-.06*(1-energy);spread=15+130*motion
    specifications=[(hue,sat,light),(hue+spread,.9*sat,light+.08),(hue-.6*spread,.8*sat,light-.03),(hue,.25+.3*sat,.17+.05*bright),(hue,.45*(1-.6*noise),.975)]
    return ['#'+''.join(f'{round(v*255):02x}' for v in colorsys.hls_to_rgb((h%360)/360,np.clip(l,.08,.99),s)) for h,s,l in specifications]

def cover(rings,durations,colors,output,avatar=None,size=2400):
    total=sum(durations);turns=float(np.clip(3.1*np.sqrt(total/60),10,26))
    grid_y,grid_x=np.mgrid[:size,:size];dx=(grid_x+.5)/size-.5;dy=(grid_y+.5)/size-.5
    radius=np.hypot(dx,dy);angle=(np.arctan2(dx,-dy)/(2*np.pi))%1
    spacing=(.47-.11)/(turns+.9);coordinate=(.47-radius)/spacing-angle;loop=np.floor(coordinate);across=coordinate-loop;time=loop+angle
    rgb=lambda h:np.array([int(h[j:j+2],16) for j in (1,3,5)])
    paper=rgb(colors[-1]);ink0=rgb(colors[3]);base=.95*paper+.05*ink0
    pixels=np.broadcast_to(paper,(size,size,3)).astype(float).copy()
    groove=(time>=0)&(time<=turns)&(across<.9)&(radius>=.11)&(radius<=.47)
    pixels[groove]=base;offset=0.
    for i,(ring,duration) in enumerate(zip(rings,durations)):
        span=turns*duration/total;mask=groove&(time>=offset)&(time<offset+span)
        pos=np.clip(((time[mask]-offset)/span*len(ring)).astype(int),0,len(ring)-1)
        band=np.clip(((.9-across[mask])/.9*ring.shape[1]).astype(int),0,ring.shape[1]-1)
        strength=ring[pos,band]**1.6
        pixels[mask]=base+(rgb(colors[i%4])-base)*strength[:,None];offset+=span
    image=Image.fromarray(np.uint8(np.clip(pixels,0,255)))
    if avatar and avatar.exists():
        from PIL import ImageDraw,ImageOps
        side=int(size*.155);face=ImageOps.fit(Image.open(avatar).convert('RGB'),(side,side));mask=Image.new('L',(side,side));ImageDraw.Draw(mask).ellipse((0,0,side-1,side-1),fill=255);image.paste(face,((size-side)//2,(size-side)//2),mask)
    image=image.resize((1200,1200),Image.Resampling.LANCZOS)
    image.save(output/'cover.png');image.resize((350,350),Image.Resampling.LANCZOS).save(output/'cover-small.jpg',quality=92)
    image.resize((975,975)).crop((0,320,975,500)).filter(ImageFilter.GaussianBlur(18)).save(output/'banner.jpg',quality=92)
    return turns
