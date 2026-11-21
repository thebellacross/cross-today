"""Persistent decisions with independent random streams; no audio is rendered here."""
import copy
import hashlib
import math
import numpy as np
from .common import digest,ROOT,file_hash

VERSION='composition-3'
CONTROL_DEFAULTS={'structure_randomness':1.,'processing_intensity':.35,'bit_damage':.2,'bus_intervention':.15,'loop_activity':.6,'space_motion':.35,'dropout_probability':.0,'stereo_width':1.}
PROCESSES=['accumulation','erosion','sustained-density','alternation','interruption','return','transformation','suspension']
TECHNIQUES=['tape','reverse','varispeed','playhead','mosaic','spectral','cross','room','freeze','weather','data','loop','hits']

def seed_for(seed,*path):return int(hashlib.sha256((str(seed)+'/'+'/'.join(map(str,path))).encode()).hexdigest()[:15],16)
def rng_for(seed,*path):return np.random.default_rng(seed_for(seed,*path))
def controls(settings):
    c={**CONTROL_DEFAULTS,**settings.get('controls',{})}
    if any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in c.values()):raise ValueError('Controls must be within 0–1.')
    return c

def source_record(c):return {k:c[k] for k in ('id','source_hash','start_frame','end_frame','sample_rate','cache_sha256','name','tags','seconds','channels','preparation','source_mapping') if k in c}
def source_span(clip,params):
    if clip.get('source_mapping'):
        def original_ranges(a,b):
            return [[m['original_start_frame']+max(a,m['cache_start_frame'])-m['cache_start_frame'],m['original_start_frame']+min(b,m['cache_end_frame'])-m['cache_start_frame']]
                    for m in clip['source_mapping'] if m['cache_start_frame']<b and m['cache_end_frame']>a]
        if params['technique']=='phrase':
            return {'pieces':[{**p,'original_ranges':original_ranges(p['source_start_frame'],p['source_end_frame'])} for p in params['phrases']],
                    'sampling':'explicit pieces from permanently prepared stereo material; original source locations retained'}
        loop=params['technique'] in ('loop','hits');a=params['offset_frame'] if loop else 0;b=a+params['period_frames'] if loop else clip['end_frame']-clip['start_frame']
        return {'cache_start_frame':a,'cache_end_frame':b,'prepared_start_frame':clip['start_frame']+a,'prepared_end_frame':clip['start_frame']+b,
                'original_ranges':original_ranges(a,b),'initial_offset_frame':params['offset_frame'],'sampling':'prepared material cache; source-file gaps removed once at import, original map retained'}
    if params['technique']=='phrase':
        pieces=[{**p,'absolute_start_frame':clip['start_frame']+p['source_start_frame'],'absolute_end_frame':clip['start_frame']+p['source_end_frame']} for p in params['phrases']]
        return {'pieces':pieces,'sampling':'explicit one-shot stereo excerpts; timing, fades and short rests recorded'}
    loop=params['technique'] in ('loop','hits');start=params['offset_frame'] if loop else 0
    end=start+params['period_frames'] if loop else clip['end_frame']-clip['start_frame']
    return {'cache_start_frame':start,'cache_end_frame':end,'absolute_start_frame':clip['start_frame']+start,'absolute_end_frame':clip['start_frame']+end,
            'initial_offset_frame':params['offset_frame'],'sampling':'recorded loop interval' if loop else 'available clip interval; actual trajectory/grains reconstructed from recorded parameters and seeds'}
def processing(seed,eid,c):
    r=rng_for(seed,eid,'operations');ops=[]
    if c['processing_intensity']>0 and r.random()<c['processing_intensity']:
        kind=str(r.choice(['shuffle','granulate','reverse-blocks','hold','filter']))
        ops.append({'kind':kind,'seed':str(seed_for(seed,eid,'editing')),'block':int(r.choice([128,512,1024,4096])),'step':int(r.integers(2,60)),'cutoff':float(r.uniform(.02,.4))})
    r=rng_for(seed,eid,'bit-operations')
    if c['bit_damage']>0 and r.random()<c['bit_damage']:
        ops.append({'kind':str(r.choice(['bitcrush','fold','overflow','xor','bit-mask','rotate','gray','byte-swap'])), 'amount':float(r.uniform(2,8)), 'levels':2**int(r.integers(2,12)), 'shift':int(r.integers(1,15)), 'mask':int(r.integers(1,32768)), 'seed':str(seed_for(seed,eid,'bit'))})
    return ops

def event(seed,eid,section,clip,start,duration,role,tech,c,clips):
    r=rng_for(seed,eid,'transform');sr=clip['sample_rate'];length=clip['end_frame']-clip['start_frame'];period=min(length,max(16,int(sr*float(r.uniform(.06,2.5)))))
    audible=[min(max(0,length-period),round(f['t']*sr)) for f in clip.get('analysis',[]) if f['rms']>1e-6]
    at=int(r.choice(audible)) if audible else int(r.integers(0,max(1,length-period+1)));speed=1. if tech in ('tape','loop','hits') else float(r.choice([.5,1,1,1,1.5,2]))
    ir=clips[int(rng_for(seed,eid,'ir-material').integers(len(clips)))];irlen=min(ir['end_frame']-ir['start_frame'],int(sr*float(r.uniform(.1,1.5))))
    steps=int(r.choice([8,12,16]));pulses=int(r.integers(2,steps));mask=[int((i*pulses)%steps<pulses) for i in range(steps)]
    rs=rng_for(seed,eid,'space');tail=round(float(rs.uniform(.1,1.5)),6) if c['space_motion'] else 0.
    pan=float(rs.uniform(-.75,.75));motion=float(rs.uniform(-.3,.3))*c['space_motion']
    params={'technique':tech,'speed':speed,'offset_frame':at,'period_frames':period,'phase_creep':float(r.uniform(-.006,.006))*c['loop_activity'] if tech=='loop' else 0.,
            'control_seed':str(seed_for(seed,eid,'control')),'spectral_seed':str(seed_for(seed,eid,'spectral')),'grain_seed':str(seed_for(seed,eid,'grains')),
            'grain_frames':int(r.choice([512,1024,2048])),'hits_mask':mask,'ir_clip_id':ir['id'],'ir_offset_frame':int(r.integers(0,max(1,ir['end_frame']-ir['start_frame']-irlen+1))),'ir_frames':irlen,
            'wet':float(r.uniform(.25,.8)) if tech!='tape' else 0.,'operations':processing(seed,eid,c)}
    if tech=='phrase':params['phrases']=[{'at_frame':0,'source_start_frame':at,'source_end_frame':at+min(period,round(duration*sr)),'fade_in_frames':round(.008*sr),'fade_out_frames':round(.04*sr),'gain':1.}]
    if tech=='room':tail=max(tail,irlen/sr)
    return {'event_id':eid,'section_id':section,'source_id':clip['id'],'source_hash':clip['source_hash'],'source':source_record(clip),
            'start':round(start,6),'duration':round(duration,6),'source_range':source_span(clip,params),
            'action':'enter','role':role,'relation_to':None,'channel_mode':'preserve','envelope':{'attack':min(.04,duration/8),'release':min(.3,duration/5),'shape':'sin2'},
            'gain':float(r.uniform(.12,.24)) if role=='foreground' else float(r.uniform(.06,.16)),
            'pan':{'start':pan,'end':max(-1.,min(1.,pan+motion))},'space':{'width':c['stereo_width'],'wet':float(rs.uniform(0,.35))*c['space_motion'],'delay_seconds':float(rs.uniform(.04,.22)),'decay_seconds':tail,'tail_seconds':tail},
            'transform':params,'decision':{'origin':'seeded-plan','seed':str(seed_for(seed,eid)),'contextual_role':True}}

def plan_composition(snapshot,seed,seconds,settings,context='open',family=None):
    clips=snapshot['clips']
    if not clips:raise ValueError('No source recordings.')
    c=controls(settings);r=rng_for(seed,'work');process=str(rng_for(seed,'work','process').choice(PROCESSES)) if rng_for(seed,'work','exploration').random()<c['structure_randomness'] else 'alternation'
    form=settings.get('form','chance')
    if form=='chance':
        names=list(settings['forms']);weights=np.array(list(settings['forms'].values()),float);form=str(rng_for(seed,'work','form').choice(names,p=weights/weights.sum())) if c['structure_randomness'] else 'baseline'
    count=1 if process=='sustained-density' else max(2,min(6,int(seconds/25)+1));count=min(count,max(1,settings.get('max_events',100)//2));sections=[];events=[];palette=rng_for(seed,'palette').choice(len(clips),size=min(len(clips),8),replace=False).tolist()
    for k in range(count):
        sid=f's{k:02d}';a=seconds*k/count;b=seconds*(k+1)/count;rs=rng_for(seed,sid);density=.6+c['structure_randomness']*float(rs.uniform(-.35,.35))
        if process=='accumulation':density=.2+.75*(k+1)/count
        elif process=='erosion':density=.95-.7*k/count
        elif process=='sustained-density':density=.9
        elif process=='suspension':density=.2 if k%2 else .65
        n=max(2,int((b-a)/12*(1+3*density)));n=min(n,20,max(1,(settings.get('max_events',100)-len(events))//(count-k)))
        transition=(str(rs.choice(['cut','crossfade','drop','handoff','swell'])) if c['structure_randomness'] else 'handoff') if k else 'start'
        section={'section_id':sid,'start':a,'end':b,'density':density,'transition':{'kind':transition,'seconds':min(2.,(b-a)/8)},'foreground':None,'process':process,'variation_rate':float(rs.uniform(.15,.9))*c['structure_randomness'],'rest_fraction':1-density};sections.append(section)
        for j in range(n):
            eid=f'{sid}-e{j:02d}';q=rng_for(seed,eid,'placement');clip=clips[palette[int(rng_for(seed,eid,'material').integers(len(palette)))]]
            t=a+(b-a)*j/n+float(q.uniform(0,.12))*c['structure_randomness']*(b-a)/n
            if process=='interruption' and j%3==2:t=max(a,t-.1*(b-a))
            # The saved variation rate controls how long material persists:
            # faster sections hand over sooner, without prescribing lower density.
            persistence=(12+c['structure_randomness']*float(q.uniform(-7,12)))/(1+section['variation_rate'])
            duration=min(seconds-t,persistence*(1+density))
            if form in ('fontana','automaton','drift'):duration=min(duration,5+c['structure_randomness']*float(q.uniform(-4.5,5)))
            duration=max(.05,duration);role='foreground' if j%3==0 else (['background','countervoice'][j%2] if not c['structure_randomness'] else str(q.choice(['background','countervoice'])))
            tech='tape'
            if c['loop_activity'] and (form=='loops' or q.random()<c['loop_activity']*.3):tech=str(q.choice(['loop','hits']))
            elif c['processing_intensity'] and q.random()<c['processing_intensity']:
                tech=str(q.choice(['reverse','varispeed','playhead','mosaic','spectral','cross','room','freeze','weather','data']))
            e=event(seed,eid,sid,clip,t,duration,role,tech,c,clips)
            if j==0:section['foreground']=eid
            if j and (process in ('return','transformation') or j%3==0):
                prior=events[-1];e['relation_to']=prior['event_id'];e['action']='return' if process=='return' else 'respond'
                if process=='return':
                    e['source_id']=prior['source_id'];e['source_hash']=prior['source_hash'];e['source']=copy.deepcopy(prior['source']);e['source_range']=copy.deepcopy(prior['source_range']);e['transform']=copy.deepcopy(prior['transform'])
            if process=='alternation':e['duration']=min(e['duration'],max(.05,(b-a)/n*.9))
            if process=='transformation':e['transform']['wet']*=k/max(count-1,1)
            events.append(e)
    # Transitions are actual event envelope/timing decisions, not decorative labels.
    for left,right in zip(sections,sections[1:]):
        boundary=right['start'];span=right['transition']['seconds'];kind=right['transition']['kind']
        before=[e for e in events if e['section_id']==left['section_id']];after=[e for e in events if e['section_id']==right['section_id']]
        for e in before:
            limit=boundary if kind in ('cut','handoff') else boundary-span if kind=='drop' else boundary+span
            e['duration']=max(.05,min(e['duration'],limit-e['start']));e['envelope']['release']=min(e['duration']/2,span if kind in ('crossfade','swell') else .02)
        if kind=='drop':
            for e in after:e['start']=min(seconds-.05,e['start']+span);e['duration']=min(e['duration'],seconds-e['start'])
        if kind in ('crossfade','swell'):
            for e in after[:2]:e['envelope']['attack']=min(span,e['duration']/2)
        if kind=='handoff' and before and after:after[0]['relation_to']=before[-1]['event_id'];after[0]['action']='respond'
    buses=[]
    for section in sections:
        q=rng_for(seed,section['section_id'],'bus')
        if c['bus_intervention'] and q.random()<c['bus_intervention']:
            buses.append({'bus_id':'bus-'+section['section_id'],'start':section['start'],'end':section['end'],'operation_seed':str(seed_for(seed,section['section_id'],'bus')),'kind':'amplitude-gate','period':float(q.uniform(.08,.8)),'wet':c['bus_intervention']*.6})
    if c['dropout_probability'] and rng_for(seed,'dropout').random()<c['dropout_probability']:
        buses.append({'bus_id':'dropout','start':seconds*.4,'end':seconds*.43,'operation_seed':str(seed_for(seed,'dropout')),'kind':'amplitude-gate','period':.08,'wet':.9})
    family=family or digest({'seed':str(seed),'snapshot':snapshot['id']})[:24]
    p={'schema':2,'planner':VERSION,'seed':str(seed),'family_id':family,'parent_id':None,'snapshot':snapshot['id'],'context':context,'sample_rate':settings['sample_rate'],'duration':float(seconds),
       'form':form,'process':process,'controls':c,'sections':sections,'events':events,'buses':buses,'ending':{'kind':str(rng_for(seed,'work','ending').choice(['fade','hard','tape-stop'] if c['bus_intervention'] else ['fade','hard'])) if c['structure_randomness'] else 'fade','seconds':min(3.,seconds/10)},'master_gain':.7,
       'rests':[{'start':s['start'],'end':s['start']+s['transition']['seconds'],'reason':'planned drop transition'} for s in sections if s['transition']['kind']=='drop'],'locks':{'events':[],'regions':[],'relations':[]},'decision_log':[{'choice':'process','value':process,'stream':'work','origin':'unbiased exploration; no personal evidence'}], 'output_sample_rate':settings.get('output_sample_rate',settings['sample_rate'])}
    p['replay']={'engine_ref':settings.get('engine_ref'),'engine_hash':digest({f.name:file_hash(f) for f in sorted((ROOT/'music').glob('*.py'))}),'numpy':np.__version__,'configuration':settings,'model_version':settings.get('model_version')}
    p['plan_id']=digest(p);return p

def affected_bounds(plan,changed):
    rows=[e for e in plan['events'] if e['event_id'] in changed]
    if not rows:return []
    lo=min(e['start'] for e in rows);hi=max(e['start']+e['duration']+e['space']['tail_seconds'] for e in rows)
    again=True
    while again:
        again=False
        for b in plan['buses']:
            if lo<b['end'] and hi>b['start'] and (b['start']<lo or b['end']>hi):lo=min(lo,b['start']);hi=max(hi,b['end']);again=True
    finish=plan['duration']+3.;tail_start=finish-plan['ending']['seconds']
    if plan['ending']['kind']=='tape-stop' and hi>tail_start:lo=min(lo,tail_start);hi=max(hi,finish)
    return [lo,hi]

def mutate(parent,action,target,seed,snapshot,locks=None):
    p=copy.deepcopy(parent);p['locks']=copy.deepcopy(locks or parent['locks']);locked=p['locks'];changed=[];changes=[]
    if action=='swap-sections':
        if len(p['sections'])<2:raise ValueError('This plan has only one section.')
        first,second=p['sections'][:2]
        for e in p['events']:
            if e['section_id'] in (first['section_id'],second['section_id']):
                old=e['start'];e['start']+=second['end']-second['start'] if e['section_id']==first['section_id'] else -(first['end']-first['start']);changed.append(e['event_id']);changes.append({'event':e['event_id'],'parameter':'start','before':old,'after':e['start']})
        d1=first['end']-first['start'];d2=second['end']-second['start'];second.update(start=0.,end=d2);first.update(start=d2,end=d2+d1);p['sections'][:2]=[second,first]
    else:
        e=next((e for e in p['events'] if e['event_id']==target),None)
        if not e:raise ValueError('Choose an existing event.')
        if target in locked.get('events',[]):raise ValueError('That event is locked.')
        changed=[target];r=rng_for(seed,target,action);before=copy.deepcopy(e)
        if action=='delay-entry':e['start']=min(p['duration']-.1,e['start']+min(8.,p['duration']*.12));e['duration']=min(e['duration'],p['duration']-e['start'])
        elif action=='earlier-entry':e['start']=max(0.,e['start']-min(8.,p['duration']*.12))
        elif action=='continue':e['duration']=min(p['duration']-e['start'],e['duration']*1.5)
        elif action=='withdraw':e['duration']=max(.1,e['duration']*.6)
        elif action=='depth':e['role']='background' if e['role']=='foreground' else 'foreground';e['gain']*=.7 if e['role']=='background' else 1.3;e['space']['wet']=min(.7,e['space']['wet']+.25) if p['controls']['space_motion'] else 0.
        elif action=='space':e['pan']={'start':-e['pan']['start'],'end':-e['pan']['end']};e['space']['width']=max(0.,1.-e['space']['width'])
        elif action=='processing':
            if not p['controls']['processing_intensity']:raise ValueError('Processing is disabled by explicit control.')
            e['transform']['wet']=1.-e['transform']['wet'];e['transform']['technique']='weather' if e['transform']['technique']=='tape' else 'tape'
        elif action=='frequency-shift':
            if not p['controls']['processing_intensity']:raise ValueError('Frequency processing is disabled by explicit control.')
            e['transform']['operations'].append({'kind':'frequency-shift','shift_hz':float(r.choice([-80,-40,40,80])),'wet':.85,'pad_seconds':.25,'operation_seed':str(seed_for(seed,target,action)), 'algorithm':'analytic-shift-1','tail_policy':'contained before event envelope'})
        elif action=='spectral-space':
            if not p['controls']['space_motion']:raise ValueError('Spatial processing is disabled by explicit control.')
            direction=float(r.choice([-1,1]));e['space']['spectral']={'kind':'spectral-space','crossovers_hz':[350.,1800.],'band_pans':[-.85*direction,0.,.85*direction],'wet':1.,'pad_seconds':.25,'operation_seed':str(seed_for(seed,target,action)),'algorithm':'spectral-balance-1','tail_policy':'contained in current dry/convolution span before spatial delay'}
        elif action=='replace-material':
            clip=snapshot['clips'][int(r.integers(len(snapshot['clips'])))];e['source_id']=clip['id'];e['source_hash']=clip['source_hash'];e['source']=source_record(clip);length=clip['end_frame']-clip['start_frame'];e['transform']['period_frames']=min(length,e['transform']['period_frames']);e['transform']['offset_frame']=min(e['transform']['offset_frame']%length,length-e['transform']['period_frames']);e['source_range']={'cache_start_frame':e['transform']['offset_frame'],'cache_end_frame':length,'absolute_start_frame':clip['start_frame']+e['transform']['offset_frame'],'sampling':'periodic read'}
        elif action=='return-later':
            returns=[a for a in p['events'] if a.get('relation_to')==target]
            if not returns:raise ValueError('No return refers to this event; choose an event with a response or return.')
            changed=[]
            for a in returns:a['start']=min(p['duration']-.1,a['start']+min(6,p['duration']*.1));a['duration']=min(a['duration'],p['duration']-a['start']);changed.append(a['event_id'])
        elif action=='repeat':
            new=copy.deepcopy(e);new['event_id']='variation-'+digest({'parent':parent['plan_id'],'seed':str(seed),'target':target})[:16];new['action']='return';new['relation_to']=target;new['start']=min(p['duration']-.1,e['start']+e['duration']+2);new['duration']=min(new['duration'],p['duration']-new['start']);p['events'].append(new);changed=[new['event_id']]
        else:raise ValueError('Unknown structural change.')
    return finish_mutation(parent,p,changed,action,snapshot,locked)

def finish_mutation(parent,p,changed,action,snapshot,locked):
    originals={e['event_id']:e for e in parent['events']};clips={c['id']:c for c in snapshot['clips']}
    for e in p['events']:
        if e['event_id'] in changed:
            clip=clips[e['source_id']];params=e['transform']
            if params['technique']=='phrase':
                size=clip['end_frame']-clip['start_frame'];n=round(e['duration']*p['sample_rate']);pieces=copy.deepcopy(params['phrases'])
                if action=='continue' and pieces:
                    cycle=max(v['at_frame']+v['source_end_frame']-v['source_start_frame'] for v in pieces)+round(.12*p['sample_rate'])
                    original=copy.deepcopy(pieces)
                    for offset in range(cycle,n,cycle):pieces.extend({**v,'at_frame':v['at_frame']+offset} for v in original)
                kept=[]
                for v in pieces:
                    if v['at_frame']>=n:continue
                    length=v['source_end_frame']-v['source_start_frame'];a=v['source_start_frame']%size if action=='replace-material' else v['source_start_frame'];b=min(size,a+length,a+n-v['at_frame'])
                    if b>a:kept.append({**v,'source_start_frame':a,'source_end_frame':b})
                params['phrases']=kept
                if not kept:raise ValueError('No phrase remains in the changed event.')
                params['offset_frame']=kept[0]['source_start_frame']
            e['source_range']=source_span(clip,params)
    # A return changes its responding events; a repeat creates a new event.
    # Audit those actual events instead of logging the unchanged target as changed.
    changes=[{'event':e['event_id'],'action':action,'before':copy.deepcopy(originals.get(e['event_id'])),'after':copy.deepcopy(e)} for e in p['events'] if e['event_id'] in changed]
    if set(changed)&set(locked.get('events',[])):raise ValueError('The change would move a locked event.')
    for relation in locked.get('relations',[]):
        if set(relation)&set(changed):raise ValueError('The change would alter a locked relationship.')
    bounds=[b for b in (affected_bounds(parent,changed),affected_bounds(p,changed)) if b]
    footprint=[min(b[0] for b in bounds),max(b[1] for b in bounds)] if bounds else [0,p['duration']]
    for a,b in locked.get('regions',[]):
        if footprint[0]<b and footprint[1]>a:raise ValueError('The effect tail or bus dependency reaches a locked audio region.')
    p['parent_id']=parent['plan_id'];p['decision_log']=parent['decision_log']+[{'origin':'controlled mutation','action':action,'changed_events':changed,'changes':changes,'affected_range':footprint,'tail_and_bus_closure':True}]
    p.pop('plan_id',None);p['plan_id']=digest(p);return p
