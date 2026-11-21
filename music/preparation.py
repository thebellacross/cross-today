"""One-time, bounded-memory preparation of freeze recordings, before segmentation."""
import subprocess
import wave
from pathlib import Path
import numpy as np
from .common import ffmpeg,file_hash

VERSION='prepared-pcm16-1'
DEFAULTS={'mode':'remove-digital-silence','minimum_gap_seconds':1.,'padding_seconds':.01}

def prepared_name(name):
    return Path(name).stem+' - prepared.wav'

def prepare(path,target,rate,channels,options):
    opts={**DEFAULTS,**options}
    if opts['mode']!='remove-digital-silence':raise ValueError('Unknown material preparation mode.')
    if not .05<=opts['minimum_gap_seconds']<=60 or not 0<=opts['padding_seconds']<=.1:raise ValueError('Invalid preparation thresholds.')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_suffix('.partial.wav')
    minimum=round(opts['minimum_gap_seconds']*rate);pad=round(opts['padding_seconds']*rate);source_at=0;written=0;pending=0;regions=[];excluded=[]
    process=subprocess.Popen([ffmpeg(),'-nostdin','-hide_banner','-loglevel','error','-i',str(path),'-map','0:a:0','-vn','-ac',str(channels),'-ar',str(rate),'-f','s16le','-'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        with wave.open(str(temporary),'wb') as output:
            output.setnchannels(channels);output.setsampwidth(2);output.setframerate(rate)
            def write(raw,start):
                nonlocal written
                count=len(raw)//(2*channels)
                if not count:return
                output.writeframesraw(raw)
                if regions and regions[-1]['source_end_frame']==start:
                    regions[-1]['source_end_frame']+=count;regions[-1]['prepared_end_frame']+=count
                else:regions.append({'source_start_frame':start,'source_end_frame':start+count,'prepared_start_frame':written,'prepared_end_frame':written+count})
                written+=count
            def flush_zero(end,final=False):
                nonlocal pending
                if not pending:return
                start=end-pending
                if pending<minimum:write(bytes(pending*channels*2),start)
                else:
                    left=min(pad,pending) if written else 0;right=min(pad,pending-left) if not final else 0
                    write(bytes(left*channels*2),start);write(bytes(right*channels*2),end-right)
                    excluded.append({'start_frame':start+left,'end_frame':end-right})
                pending=0
            while True:
                raw=process.stdout.read(65536*channels*2)
                if not raw:break
                x=np.frombuffer(raw,dtype='<i2').reshape(-1,channels);silent=np.all(x==0,axis=1)
                edges=np.r_[0,np.flatnonzero(silent[1:]!=silent[:-1])+1,len(x)]
                for a,b in zip(edges[:-1],edges[1:]):
                    a=int(a);b=int(b)
                    if silent[a]:pending+=b-a
                    else:flush_zero(source_at+a);write(raw[a*channels*2:b*channels*2],source_at+a)
                source_at+=len(x)
            flush_zero(source_at,final=True)
        if process.wait()!=0:raise ValueError('Material preparation decoding failed.')
        if not written:raise ValueError('Source is digitally silent; no substitute was used.')
        temporary.replace(target)
        return {'version':VERSION,'policy':opts,'sample_rate':rate,'channels':channels,'original_frames':source_at,'prepared_frames':written,
                'removed_frames':source_at-written,'excluded':excluded,'mapping':regions,'sha256':file_hash(target),
                'criterion':'all decoded PCM16 channels exactly zero; quiet/antiphase content and short rests retained; no normalization'}
    finally:
        process.stdout.close()
        if process.poll() is None:process.terminate();process.wait()
        temporary.unlink(missing_ok=True)

def source_mapping(preparation,start,end):
    rows=[]
    for r in preparation['mapping']:
        a=max(start,r['prepared_start_frame']);b=min(end,r['prepared_end_frame'])
        if b>a:rows.append({'cache_start_frame':a-start,'cache_end_frame':b-start,
                           'original_start_frame':r['source_start_frame']+a-r['prepared_start_frame'],
                           'original_end_frame':r['source_start_frame']+b-r['prepared_start_frame']})
    return rows
