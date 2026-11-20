import argparse
import datetime
import json
import re
import subprocess
import sys
import platform
import shutil
import zipfile
from pathlib import Path
import numpy as np
from . import ENGINE_VERSION
from .common import ROOT,config,digest,file_hash,save_json,run_audio,ffmpeg
from .engine import render
from .artwork import analyze,palette,cover

def title_for(score,rng,index):
    names=list(dict.fromkeys(e['name'] for e in score['events']))
    tokens=[]
    for name in names:
        stem=re.sub(r'\[[^\]]*\]|\([^)]*\)',' ',Path(name).stem)
        tokens.extend(w for w in re.findall(r'[^\W\d_]+',stem,flags=re.UNICODE) if len(w)>1 and w.lower() not in {'audio','freeze','wav','aif','the'})
    tokens=list(dict.fromkeys(tokens))
    take=[str(t) for t in rng.choice(tokens,size=min(2,len(tokens)),replace=False)] if tokens else ['Fragment']
    process=score.get('main_technique') or score['form']
    return ' '.join(take+[process.title(),f'{index:02d}'])

def download_archives(output,extension,limit=1024**3):
    """Independent ZIP volumes stay comfortably below GitHub's per-asset limit."""
    common=[output/name for name in ('cover.png','credits.txt','score.json','provenance.json')]
    overhead=sum(p.stat().st_size for p in common)+65536
    groups=[[]];size=overhead
    for audio in sorted(output.glob('*.'+extension)):
        if groups[-1] and size+audio.stat().st_size>limit:groups.append([]);size=overhead
        groups[-1].append(audio);size+=audio.stat().st_size
    downloads={}
    for index,group in enumerate(groups,1):
        suffix=f'-{index:02d}' if len(groups)>1 else ''
        name=f'album-{extension}{suffix}.zip'
        with zipfile.ZipFile(output/name,'w',compression=zipfile.ZIP_STORED) as z:
            for p in sorted(group+common):
                entry=zipfile.ZipInfo(p.name,date_time=(1980,1,1,0,0,0));entry.external_attr=0o644<<16;z.writestr(entry,p.read_bytes())
        label=extension.upper()+(f' {index}/{len(groups)}' if len(groups)>1 else '')
        downloads[label]=name
    return downloads

def create_album(snapshot,cache,output,seed,day,number=0,settings=None,short=None,final_override=None,preference=None):
    cfg=settings or config();g=dict(cfg['generation']);g['engine_ref']=cfg.get('engine_ref');g['output_sample_rate']=48000;rng=np.random.default_rng(seed)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if not snapshot.get('clips'):raise ValueError('No valid sound materials; album not generated.')
    if not 0<g['track_seconds'][0]<=g['track_seconds'][1] or not 1<=g['tracks'][0]<=g['tracks'][1]<=30:raise ValueError('Invalid track duration or count range.')
    feed=None
    if g.get('feed'):
        feed=Path(g['feed']).read_bytes()
        g['feed']={'sha256':file_hash(g['feed']),'bytes':len(feed)}
    counts=list(range(g['tracks'][0],g['tracks'][1]+1));weights=np.asarray(g.get('track_count_weights',[1]*len(counts)),float)
    if len(weights)!=len(counts):weights=np.ones(len(counts))
    count=int(rng.choice(counts,p=weights/weights.sum())) if not short else 3
    pure=bool(rng.random()<g['pure_day_probability']);tracks=[];scores=[];moods=[];rings=[];durations=[]
    if g.get('daily_parameters') and g.get('renderer')!='composition':
        g['palette_size']=[3,int(rng.choice([8,20,60,180],p=[.55,.25,.13,.07]))]
        g['garble']=float(rng.choice([0,.15,.35,.6]))
    if pure:g['form']='fontana'
    version_hash=digest({p.name:file_hash(p) for p in sorted((ROOT/'music').glob('*.py'))})
    retained_engine=ROOT/'.state/engines'/version_hash
    retained_engine.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'music').glob('*.py'):
        if not (retained_engine/source.name).exists():shutil.copy2(source,retained_engine/source.name)
    for index in range(1,count+1):
        duration=float(short or 0)
        if g['track_seconds'][0]==g['track_seconds'][1]:duration=float(g['track_seconds'][0])
        while not short and not g['track_seconds'][0]<=duration<=g['track_seconds'][1]:duration=float(np.exp(rng.normal(np.log(g.get('median_seconds',210)),.7)))
        track_seed=int(rng.integers(0,2**62))
        if g.get('renderer')=='composition':
            from .studio import generate
            pref=preference or {};samples,score=generate(snapshot,cache,track_seed,duration,g,pref.get('model'),pref.get('profile'))
            # Context descriptions and fitted weights remain in private profiles.
            score['plan']['context']=pref.get('profile',{}).get('id','open')
            for event in score['events']:event.pop('feature_frames',None)
        else:samples,score=render(snapshot['clips'],cache,track_seed,duration,g,age=0 if pure else min(number/180,1),pure=pure,feed=feed)
        name=title_for(score,rng,index);score.update({'n':index,'title':name,'seed':str(track_seed),'duration':len(samples)/g['sample_rate']})
        wav=output/f'{index:02d}.wav';mp3=output/f'{index:02d}.mp3'
        # Float PCM transport avoids quantising the final stereo master down to the source cache's 16 bits.
        raw=output/f'.{index:02d}.f32';raw.write_bytes(np.asarray(samples,dtype='<f4').tobytes())
        try:
            run_audio(['-y','-f','f32le','-ar',g['sample_rate'],'-ac',2,'-i',raw,'-ar',48000,'-c:a','pcm_s24le','-fflags','+bitexact',wav])
            run_audio(['-y','-i',wav,'-c:a','libmp3lame','-b:a','320k','-map_metadata','-1','-id3v2_version','3','-metadata',f'title={name}','-metadata',f'artist={cfg["artist"]}',mp3])
        finally:raw.unlink(missing_ok=True)
        mood,ring=analyze(samples,g['sample_rate']);moods.append(mood);rings.append(ring);durations.append(len(samples)/g['sample_rate'])
        tracks.append({'n':index,'title':name,'duration':durations[-1],'src':mp3.name,'wav':wav.name,'seed':str(track_seed),'form':score['form']})
        scores.append(score)
        print(f'Rendered {index}/{count}: {score["form"]}, {durations[-1]:.1f}s',flush=True)
    colors=palette(np.average(moods,axis=0,weights=durations));turns=cover(rings,durations,colors,output,ROOT/'web/assets/artist/bellacross.jpg')
    number=int(number);catalog=f'{cfg["series"]["catalog_prefix"]}{number:03d}'
    # Titles are derived from supplied filenames and processes, not invented prior works.
    title=' '.join(tracks[0]['title'].split()[:-1])
    for track in tracks:
        temporary=output/(str(track['n'])+'.tagged.mp3')
        run_audio(['-y','-i',output/track['src'],'-i',output/'cover.png','-map','0:a','-map','1:v','-c:a','copy','-c:v','mjpeg','-id3v2_version','3','-metadata',f'album={catalog} {title}','-metadata',f'date={day}','-metadata:s:v','title=Album cover','-metadata:s:v','comment=Cover (front)',temporary])
        temporary.replace(output/track['src'])
    odds=max(1,cfg['series']['last_odds']+1-number)
    final=bool(cfg['series']['random_end'] and rng.integers(odds)==0) if final_override is None else bool(final_override)
    album={'schema':1,'id':f'album-{day}','day':day,'catalog':catalog,'number':number,'title':title,'artist':cfg['artist'],'project_name':cfg['project_name'],
           'seed':str(seed),'snapshot':snapshot['id'],'engine':ENGINE_VERSION,'engine_hash':version_hash,'tracks':tracks,'duration':sum(durations),'palette':colors,'turns':turns,'cover':'cover.png','cover_small':'cover-small.jpg','banner':'banner.jpg',
           'score':'score.json','downloads':{'WAV':'album-wav.zip','MP3':'album-mp3.zip'},'credits':cfg['credits'],'final':final,'last_odds':odds,
           'rules':{'timezone':cfg['timezone'],**cfg['schedule'],**cfg['series']},'implementation':'Independent implementation; behavioural reference recorded in provenance.'}
    public_clips=[{k:v for k,v in c.items() if k not in ('cache_file','features','analysis')} for c in snapshot['clips']]
    provenance={'schema':1,'seed':str(seed),'snapshot':snapshot['id'],'sources':public_clips,'config':{k:v for k,v in cfg.items() if k not in ('worker_url','site_url')},'generation':g,'final':final,'engine':ENGINE_VERSION,'engine_hash':version_hash,'reference':cfg['reference'],
                'runtime':{'python':sys.version.split()[0],'platform':platform.system()+' '+platform.machine(),'numpy':np.__version__,'ffmpeg':subprocess.check_output([ffmpeg(),'-version'],text=True).splitlines()[0]}}
    provenance['config']['generation']=g
    save_json(output/'score.json',{'album':album['id'],'tracks':scores})
    save_json(output/'provenance.json',provenance)
    log=[cfg['artist']+' · '+catalog+' '+title,'seed: '+str(seed),'']
    for s in scores:
        log += [f'{s["n"]:02d} {s["title"]} [{s["form"]}]']
        for e in s['events']:
            label=e['name'].replace('[','(').replace(']',')')
            log.append(f'{e["start"]:.3f}s +{e["duration"]:.3f}s radio [{label}] source={e["source_hash"]} segment={e["segment_start"]:.3f}-{e["segment_end"]:.3f} {e["technique"]}')
    (output/'score.txt').write_text('\n'.join(log));(output/'credits.txt').write_text(cfg['credits']+'\n'+catalog+' '+title+'\n'+f'Seed: {seed}\nEngine: {ENGINE_VERSION}\n'+ '\n'.join(f'{t["n"]:02d}. {t["title"]}' for t in tracks))
    album['downloads']={}
    for extension in ('wav','mp3'):album['downloads'].update(download_archives(output,extension))
    album['assets']={p.name:{'sha256':file_hash(p),'bytes':p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file() and p.name!='album.json'}
    save_json(output/'album.json',album)
    return album

def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshot',default='.state/snapshot.json');p.add_argument('--cache',default='.cache/audio');p.add_argument('--out',required=True);p.add_argument('--seed',type=int,required=True);p.add_argument('--day',required=True);p.add_argument('--number',type=int,default=0);p.add_argument('--short',type=float)
    a=p.parse_args();create_album(json.loads(Path(a.snapshot).read_text()),a.cache,a.out,a.seed,datetime.date.fromisoformat(a.day).isoformat(),a.number,short=a.short)

if __name__=='__main__':main()
