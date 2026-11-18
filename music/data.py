"""Deterministic arithmetic/data sonification and destructive tape operations.

Algorithms are expressed independently; no machine files are read implicitly.
"""
import math
import numpy as np

FAMILIES={'bytes':2.,'files':2.5,'bytebeat':3.,'automaton':3.,'life':2.,'lfsr':2.,'chaos':2.,'irrational':1.2,'sequence':2.5,'substitution':1.5,'sort':1.5,'impulses':.6}
OPERATIONS=['bitcrush','hold','reverse','gate','sequence-gate','fold','overflow','xor','bit-mask','rotate','gray','byte-swap','shuffle','sort','skip','difference','sum','granulate','lowpass','lowpass']

def normalize(x):
    x=np.nan_to_num(np.asarray(x,dtype=float),nan=0.,posinf=0.,neginf=0.)
    if not x.size:return np.zeros(1)
    x-=np.mean(x)
    return x/max(1e-9,float(np.max(np.abs(x))))

def interpret(raw,rng):
    b=np.frombuffer(raw,dtype=np.uint8);mode=str(rng.choice(['integer','float','bits','nibbles'],p=[4/7,1/7,1/7,1/7]))
    if mode=='bits':return np.unpackbits(b).astype(float)*2-1,mode
    if mode=='nibbles':return np.column_stack((b>>4,b&15)).reshape(-1)/7.5-1,mode
    endian='<' if rng.random()<.5 else '>'
    if mode=='float':
        width=int(rng.choice([2,4]))
        with np.errstate(invalid='ignore',over='ignore'):
            v=np.frombuffer(b[:len(b)//width*width].tobytes(),dtype=endian+'f'+str(width)).astype(float)
        v=np.nan_to_num(v,nan=0.,posinf=0.,neginf=0.);return normalize(np.sign(v)*np.log1p(np.abs(v))),f'float{width*8}'
    width=int(rng.choice([1,2,2,3,4]));signed=rng.random()<.6
    if width==3:
        chunks=b[:len(b)//3*3].reshape(-1,3).astype(np.int64)
        if endian=='>':chunks=chunks[:,::-1]
        v=chunks[:,0]+chunks[:,1]*256+chunks[:,2]*65536
        if signed:v=np.where(v>=2**23,v-2**24,v)
    else:v=np.frombuffer(b[:len(b)//width*width].tobytes(),dtype=endian+('i' if signed else 'u')+str(width)).astype(float)
    return normalize(v),f'{"signed" if signed else "unsigned"}{width*8}'

def sequence(count,rng):
    kind=str(rng.choice(['thue-morse','rudin-shapiro','paperfolding','fibonacci','stern','collatz','recaman','prime-gaps','digit-sums','kolakoski']))
    if kind=='thue-morse':v=[bin(i).count('1')%2 for i in range(count)]
    elif kind=='rudin-shapiro':v=[sum(1 for j in range(len(bin(i))-1) if bin(i)[j:j+2]=='11')%2 for i in range(count)]
    elif kind=='paperfolding':v=[1 if ((i+1)//((i+1)&-(i+1)))%4==1 else 0 for i in range(count)]
    elif kind=='fibonacci':
        v=[];a,b=0,1
        for _ in range(count):a,b=b,(a+b)%65536;v.append(a)
    elif kind=='stern':
        v=[0,1]
        for i in range(2,count):v.append(v[i//2] if i%2==0 else v[i//2]+v[i//2+1])
    elif kind=='recaman':
        v=[0];seen={0}
        for i in range(1,count):a=v[-1]-i;a=a if a>0 and a not in seen else v[-1]+i;v.append(a);seen.add(a)
    elif kind=='collatz':
        v=[];a=int(rng.integers(1000,100000))
        for i in range(count):v.append(a%65536);a=(a//2 if a%2==0 else 3*a+1) if a>1 else i+1023
    elif kind=='prime-gaps':
        limit=max(100,int(count*(math.log(max(count,3))+math.log(max(math.log(max(count,3)),1)))+1000));sieve=np.ones(limit,dtype=bool);sieve[:2]=False
        for i in range(2,int(math.sqrt(limit))+1):
            if sieve[i]:sieve[i*i::i]=False
        v=np.resize(np.diff(np.flatnonzero(sieve)),count)
    elif kind=='kolakoski':
        v=[1,2,2];read=2;symbol=1
        while len(v)<count:v.extend([symbol]*v[read]);symbol=3-symbol;read+=1
    else:v=[sum(map(int,str(i))) for i in range(count)]
    return normalize(np.asarray(v[:count])),kind

def signal(rng,n,kind=None,feed=None):
    names=[k for k in FAMILIES if k!='files' or feed];weights=np.array([FAMILIES[k] for k in names]);kind=kind or str(rng.choice(names,p=weights/weights.sum()))
    hold=int(rng.integers(1,65));count=max(512,min(65536,math.ceil(n/hold)))
    label=kind
    if kind in ('bytes','files'):
        raw=rng.integers(0,256,count*4,dtype=np.uint8).tobytes() if kind=='bytes' else (feed or b'')
        if not raw:raise ValueError('An explicit file feed is required for file-byte data.')
        v,interpretation=interpret(raw,rng);label+=' '+interpretation
    elif kind=='bytebeat':
        t=np.arange(count,dtype=np.uint64);a,b=map(int,rng.integers(3,13,2));form=int(rng.integers(3))
        v=(t*((t>>a)|(t>>b)) if form==0 else (t^(t>>a))*((t>>b)|1) if form==1 else (t&(t>>a))|(t>>b))%256;v=v.astype(float)/127.5-1
    elif kind=='automaton':
        rule=int(rng.choice([18,22,30,54,60,90,110,126,150]));row=rng.integers(0,2,64,dtype=np.uint8);parts=[]
        for _ in range(math.ceil(count/64)):
            parts.extend(row);q=np.roll(row,1)*4+row*2+np.roll(row,-1);row=(rule>>q)&1
        v=np.array(parts,float)*2-1;label+=' '+str(rule)
    elif kind=='life':
        grid=rng.random((32,32))<.3;parts=[];birth,survive=([3],[2,3]) if rng.random()<.5 else ([3,6],[2,3])
        for _ in range(math.ceil(count/1024)):
            parts.extend(grid.reshape(-1));neighbours=sum(np.roll(np.roll(grid.astype(int),a,axis=0),b,axis=1) for a in [-1,0,1] for b in [-1,0,1] if a or b);grid=(~grid&np.isin(neighbours,birth))|(grid&np.isin(neighbours,survive))
        v=np.array(parts,float)*2-1
    elif kind=='lfsr':
        state=int(rng.integers(1,65536));v=np.empty(count)
        for i in range(count):v[i]=state/32767.5-1;state=(state>>1)^(-(state&1)&0xB400)
    elif kind=='chaos':
        choice=int(rng.integers(3));x=float(rng.uniform(.1,.9));y=.1;v=np.empty(count)
        for i in range(count):
            if choice==0:x=(3.7+.29*(.5+.5*math.sin(i*.0001)))*x*(1-x)
            elif choice==1:x=(x+.12-.7/(2*np.pi)*math.sin(2*np.pi*x))%1
            else:x,y=1-1.4*x*x+y,.3*x;x=float(np.clip(x,-1.5,1.5))
            v[i]=x
        v=normalize(v)
    elif kind=='irrational':
        # Fractional rotation yields a deterministic binary coding of an irrational slope.
        alpha=math.sqrt(int(rng.choice([2,3,5,7,11])));v=((np.arange(count)*alpha)%1>.5).astype(float)*2-1
    elif kind=='sequence':v,label=sequence(count,rng)
    elif kind=='substitution':
        word='0';rules=({'0':'01','1':'10'} if rng.random()<.5 else {'0':'01','1':'0'})
        while len(word)<count:word=''.join(rules[c] for c in word)
        v=np.fromiter((int(c)*2-1 for c in word[:count]),float)
    elif kind=='sort':
        row=rng.uniform(-1,1,128);parts=[]
        for i in range(1,128):
            key=row[i];j=i-1
            while j>=0 and row[j]>key:row[j+1]=row[j];j-=1
            row[j+1]=key;parts.extend(row.copy())
        v=np.resize(parts,count)
    else:
        v=np.zeros(count);positions=rng.integers(0,count,max(1,count//40));v[positions]=rng.choice([-1.,1.],len(positions))
    v=np.asarray(v,float)
    if not len(v):v=np.zeros(1)
    position=np.arange(n)/hold
    if n>32000 and rng.random()<.35:
        speeds=np.interp(np.linspace(0,7,n),np.arange(8),2**rng.uniform(-1,1,8));position=np.cumsum(speeds)/hold
    return np.interp(position%len(v),np.arange(len(v)),v),label

def process(x,rng,depth=.3,allowed=None):
    y=x.copy();names=[];pool=allowed or OPERATIONS
    for _ in range(int(rng.binomial(4,min(1,depth*.75)))):
        op=str(rng.choice(pool));names.append(op);n=len(y);block=int(rng.integers(64,4097));integer=np.clip(y*32767,-32768,32767).astype(np.int32)
        if op=='bitcrush':levels=2**int(rng.integers(2,12));y=np.round(y*levels)/levels
        elif op=='hold':step=int(rng.integers(2,80));y=y[(np.arange(n)//step)*step]
        elif op in ('reverse','shuffle','sort','skip','granulate'):
            chunks=[y[i:i+block].copy() for i in range(0,n,block)]
            if op=='reverse':chunks=[a[::-1] if i%2 else a for i,a in enumerate(chunks)]
            elif op=='shuffle':rng.shuffle(chunks)
            elif op=='sort':chunks=[np.sort(a) for a in chunks]
            else:chunks=[chunks[int(rng.integers(len(chunks)))] for _ in chunks]
            y=np.resize(np.concatenate(chunks),n)
        elif op in ('gate','sequence-gate'):
            gates=rng.random(math.ceil(n/block))>.3 if op=='gate' else sequence(math.ceil(n/block),rng)[0]>0;y*=np.repeat(gates,block)[:n]
        elif op=='fold':v=y*float(rng.uniform(2,8));y=2*np.abs((v+1)%4-2)-1
        elif op=='overflow':y=((y*float(rng.uniform(2,8))+1)%2)-1
        elif op=='xor':y=(integer^int(rng.integers(1,32768)))/32768
        elif op=='bit-mask':y=(integer&int(rng.integers(1,65536)))/32768
        elif op=='rotate':shift=int(rng.integers(1,15));u=integer&65535;y=(((u<<shift)|(u>>(16-shift)))&65535)/32767.5-1
        elif op=='gray':u=integer&65535;y=(u^(u>>1))/32767.5-1
        elif op=='byte-swap':u=integer&65535;y=(((u&255)<<8)|(u>>8))/32767.5-1
        elif op=='difference':y=np.diff(y,prepend=y[0])
        elif op=='sum':y=np.cumsum(y-y.mean());y-=np.linspace(y[0],y[-1],n)
        elif op=='lowpass':
            width=int(rng.integers(2,100));cs=np.r_[0,np.cumsum(y)];y=(cs[np.minimum(np.arange(n)+width,n)]-cs[np.arange(n)])/np.minimum(width,n-np.arange(n))
        y=normalize(y)*min(1,max(.001,np.max(np.abs(x))))
    return y,names
