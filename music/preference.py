"""Contextual pairwise ranking. No labels are inferred from collections or predictions."""
import copy
import numpy as np
from .common import digest
from .plan import rng_for, mutate
from .frequency import EXTRA_FEATURES,ANALYSIS_VERSION,pair_descriptors

from .continuity import FEATURES as CONTINUITY_FEATURES,VERSION as ACTIVITY_VERSION,descriptors as continuity_descriptors

VERSION='relational-bt-4'
STRENGTH_WEIGHTS={'normal':1.,'slight':.5}
LEGACY_FEATURES=['density','rest','entry_spacing','return_spacing','development','duration_spread','foreground_share','role_contrast','band_overlap','pan_separation','tail_occupancy','processing','bit_damage','loop_share','stereo','motion','foreground_noise','conflict_foreground','dense_transients','return_contrast','space_with_overlap','change_with_noise']
FREQUENCY_FEATURES=LEGACY_FEATURES+EXTRA_FEATURES
FEATURES=FREQUENCY_FEATURES+CONTINUITY_FEATURES
FEATURE_COUNTS=(len(LEGACY_FEATURES),len(FREQUENCY_FEATURES),len(FEATURES))

def available_features(report):
    return len(FEATURES) if report.get("continuity",{}).get("version")==ACTIVITY_VERSION else len(FREQUENCY_FEATURES) if report.get("relation_analysis")==ANALYSIS_VERSION else len(LEGACY_FEATURES)
ACTIONS=['delay-entry','earlier-entry','continue','withdraw','depth','space','processing','replace-material','repeat','return-later','swap-sections','frequency-shift','spectral-space','phrase-connect','bridge-gap','sustain-gap','handoff-gap']

def vector(plan,report):
    events=report['events'];duration=plan['duration'];n=max(1,len(events));pe={e['event_id']:e for e in plan['events']};features={e['event_id']:e['processed_features'] for e in events}
    # Time-local overlap is measured AFTER transforms, envelopes and effect tails.
    hop=.5;times=np.arange(0,report.get('duration',duration+3),hop);active=[];conflicts=[];pans=[];contrast=[];noisy=[];transients=[];partials=[];correlations=[]
    for t in times:
        sounding=[]
        for e in events:
            if not e['start']<=t<e['active_until']:continue
            rows=e['feature_frames'];i=min(len(rows)-1,max(0,int((t-e['start'])/.25)));f=rows[i]
            if f['rms']>1e-6:sounding.append((e,f))
        active.append(len(sounding))
        for i,(a,fa) in enumerate(sounding):
            if fa.get('relation_analysis')==ANALYSIS_VERSION:correlations.append(fa['channel_correlation'])
            noisy.append(fa['flatness'] if a['role']=='foreground' else 0.)
            transients.append(fa['flux']*len(sounding))
            for b,fb in sounding[i+1:]:
                ba=np.array(fa['bands']);bb=np.array(fb['bands']);overlap=float(np.dot(ba,bb)/(np.linalg.norm(ba)*np.linalg.norm(bb)+1e-12));conflicts.append(overlap)
                pans.append(abs(pe[a['event_id']]['pan']['start']-pe[b['event_id']]['pan']['start'])/2)
                contrast.append(abs(fa['rms']-fb['rms'])/(fa['rms']+fb['rms']+1e-9))
                if fa.get('relation_analysis')==fb.get('relation_analysis')==ANALYSIS_VERSION:
                    relation=pair_descriptors(fa,fb)
                    if relation:partials.append([*relation,relation[0]*relation[4],relation[1]*float(a['role']=='foreground' or b['role']=='foreground')])
    avg=lambda x:float(np.mean(x)) if len(x) else 0.
    starts=sorted(e['start'] for e in events);intervals=np.diff(starts);returns=[];return_contrast=[]
    for e in events:
        prior=pe.get(e.get('relation_to'))
        if prior:
            returns.append(max(0,e['start']-prior['start'])/duration)
            return_contrast.append(abs(features[e['event_id']]['centroid']-features.get(prior['event_id'],{}).get('centroid',0)))
    section_features=[]
    for s in plan['sections']:
        rows=[features[e['event_id']] for e in events if e['section_id']==s['section_id']]
        section_features.append([avg([f[k] for f in rows]) for k in ['rms','centroid','flatness','flux']])
    development=float(np.mean(np.abs(np.diff(section_features,axis=0)))) if len(section_features)>1 else 0.
    density=avg(active)/8;overlap=avg(conflicts);noise=avg(noisy);tail=avg([e['tail_seconds'] for e in events])/3
    proc=avg([pe[e['event_id']]['transform']['wet']+len(pe[e['event_id']]['transform']['operations'])/4 for e in events])
    bits=avg([sum(o['kind'] in ('bitcrush','fold','overflow','xor','bit-mask','rotate','gray','byte-swap') for o in pe[e['event_id']]['transform']['operations']) for e in events])
    values=[density,avg(np.array(active)==0),avg(intervals)/duration,avg(returns),development,float(np.std([e['duration']/duration for e in events])),sum(e['role']=='foreground' for e in events)/n,avg(contrast),overlap,avg(pans),tail,proc,bits,sum(e['technique'] in ('loop','hits') for e in events)/n,avg([f['side_ratio'] for f in features.values()]),avg([abs(e['pan']['end']-e['pan']['start']) for e in pe.values()]),noise,overlap*noise,avg(transients),avg(return_contrast),overlap*(tail+avg(pans)),development*noise]
    fine=[avg([p[i] for p in partials]) for i in range(5)]+[avg(correlations)]+[avg([p[i] for p in partials]) for i in (5,6)]
    return np.clip(np.nan_to_num(values+fine+continuity_descriptors(report)),-4,4).tolist()

def padded(values):
    if len(values) not in FEATURE_COUNTS:raise ValueError('Unknown relation feature schema.')
    out=np.pad(np.asarray(values,float),(0,len(FEATURES)-len(values)))
    if not np.isfinite(out).all():raise ValueError('Non-finite relation features.')
    return out

def fit(x,y,regularization=1.,sample_weight=None):
    x=np.asarray(x,float);y=np.asarray(y,float);w=np.zeros(len(FEATURES))
    if not len(x):return w
    sw=np.ones(len(x)) if sample_weight is None else np.asarray(sample_weight,float)
    if sw.shape!=(len(x),) or not np.isfinite(sw).all() or np.any(sw<=0):raise ValueError('Invalid explicit preference strength.')
    for _ in range(60):
        logits=np.clip(x@w,-30,30);p=1/(1+np.exp(-logits));gradient=x.T@(sw*(p-y))+regularization*w
        hessian=(x.T*(sw*p*(1-p)))@x+regularization*np.eye(len(w));step=np.linalg.solve(hessian,gradient);w-=step
        if np.linalg.norm(step)<1e-8:break
    return w

def train(records,profile,revision,allow_simulated=False):
    valid=[]
    for f in records:
        if f.get('revoked') or f.get('evaluation') or f.get('choice') not in ('A','B'):continue
        if f.get('origin')!='human' and not allow_simulated:raise ValueError('Non-human labels cannot enter a personal profile.')
        if f['profile_id']!=profile:continue
        if f.get('strength','normal') not in STRENGTH_WEIGHTS:raise ValueError('Unknown explicit preference strength.')
        valid.append(f)
    differences=[];observed=np.zeros(len(FEATURES),int)
    for f in valid:
        count=min(f.get('available_features_A',len(f['features_A'])),f.get('available_features_B',len(f['features_B'])))
        if count not in FEATURE_COUNTS:raise ValueError('Unknown observed feature schema.')
        delta=padded(f['features_A'])-padded(f['features_B']);delta[count:]=0;observed[:count]+=1;differences.append(delta)
    x=np.asarray(differences);y=np.array([f['choice']=='A' for f in valid],float);weights_by_record=np.array([STRENGTH_WEIGHTS[f.get('strength','normal')] for f in valid])
    groups=sorted(set(f['family_id'] for f in valid));seed=digest({'revision':revision,'profile':profile,'records':valid});r=rng_for(seed,'bootstrap');weights=fit(x,y,sample_weight=weights_by_record);ensemble=[]
    for _ in range(16):
        draws=r.choice(groups,len(groups),replace=True) if groups else [];indices=[i for group in draws for i,f in enumerate(valid) if f['family_id']==group]
        ensemble.append(fit(x[indices],y[indices],sample_weight=weights_by_record[indices]).tolist() if len(indices) else weights.tolist())
    evaluation={'method':'parent-family holdout; no near-variant cross split','status':'not enough independent families','families':len(groups),'accuracy':None}
    if len(groups)>=4:
        test_groups=set(groups[::4]);tr=[i for i,f in enumerate(valid) if f['family_id'] not in test_groups];te=[i for i,f in enumerate(valid) if f['family_id'] in test_groups];frozen=fit(x[tr],y[tr],sample_weight=weights_by_record[tr]);evaluation.update(status='technical held-out ranking only; artistic evaluation still requires unseen listening',test_families=sorted(test_groups),accuracy=float(np.mean((x[te]@frozen>0)==y[te])))
    model={'schema':1,'algorithm':VERSION,'feature_names':FEATURES,'profile_id':profile,'dataset_revision':revision,'labels':len(valid),'families':len(groups),'weights':weights.tolist(),'ensemble':ensemble,'regularization':1.,'evaluation':evaluation,'label_origin':'simulated-test-only' if allow_simulated else 'human','uncertainty_method':'parent-family grouped bootstrap; unreliable below three independent families'}
    model['strength_policy']={'weights':STRENGTH_WEIGHTS,'meaning':'explicit relative preference strength; weights are an engineering convention, not confidence or absolute satisfaction'};model['effective_label_weight']=float(weights_by_record.sum())
    model['observed_feature_counts']=observed.tolist();model['missing_feature_policy']='Old unmeasured descriptors contribute no evidence; their pairwise differences are masked, never fabricated.'
    model['id']=digest(model);return model

def rank(candidates,model,allow_simulated=False):
    compatible=not model or (model['algorithm'] in (VERSION,'relational-bt-3') and model['feature_names']==FEATURES) or (model['algorithm']=='relational-bt-2' and model['feature_names']==FREQUENCY_FEATURES) or (model['algorithm']=='relational-bt-1' and model['feature_names']==LEGACY_FEATURES)
    if model and (not compatible or (model.get('label_origin')!='human' and not allow_simulated)):raise ValueError('Incompatible or simulated personal model.')
    w=padded(model['weights']) if model else np.zeros(len(FEATURES));result=[];base=padded(candidates[0]['features'])
    for c in candidates:
        v=padded(c['features']);z=float((v-base)@w);prob=float(1/(1+np.exp(-np.clip(z,-30,30))))
        variance=float(np.std([np.dot(v-base,padded(a)) for a in model['ensemble']])) if model and model['families']>=3 else None
        result.append({'id':c['id'],'score':float(v@w),'preference_vs_first':prob,'bootstrap_logit_sd':variance})
    return sorted(result,key=lambda x:x['score'],reverse=True)

def select(candidates,model,seed,exploration=.2):
    ranking=rank(candidates,model);r=rng_for(seed,'model-selection');explore=not model or not model['labels'] or r.random()<exploration
    if explore:
        weights=np.array([1+(row['bootstrap_logit_sd'] or 0) for row in ranking]);selected=ranking[int(r.choice(len(ranking),p=weights/weights.sum()))]
    else:selected=ranking[0]
    return selected['id'],{'model_id':model['id'] if model else None,'personal_labels':model['labels'] if model else 0,'exploration':bool(explore),'ranking':ranking,'seed':str(seed),'probability_is_not_confidence':True,'feature_schema':VERSION,'trained_feature_count':len(model['feature_names']) if model else 0,'legacy_projection':bool(model and model['algorithm']!=VERSION)}

def constrain(plan,rules):
    """Explicit bounds remain independent of fitted weights. Reject, don't silently repair."""
    for name,value in rules.get('controls',{}).items():
        if plan['controls'].get(name)!=value:raise ValueError('Candidate changed an explicit control.')
    for e in plan['events']:
        if 'stereo_width' in rules.get('controls',{}) and e['space']['width']!=rules['controls']['stereo_width']:raise ValueError('The explicit width rule would be changed.')
        if rules.get('max_events') and len(plan['events'])>rules['max_events']:raise ValueError('Candidate exceeds the explicit event limit.')
        if rules.get('preserve_channels') and (e['channel_mode']!='preserve' or e['space']['width']!=1.):raise ValueError('A channel lock was violated.')
    return plan

def proposals(parent,snapshot,seed,locks=None,actions=None,limit=3,rules=None,targets=None,evidence=None,scope=None):
    rows=[parent];r=rng_for(seed,'proposal-order')
    requested_targets=targets
    if actions is None:
        automatic=ACTIONS if parent['controls']['structure_randomness'] else ['processing','space','frequency-shift','spectral-space']
        if (rules or {}).get('continuity',{}).get('mode')=='off':automatic=[a for a in automatic if a not in ('bridge-gap','phrase-connect','sustain-gap','handoff-gap')]
        actions=list(r.permutation(automatic))
        if parent['controls']['structure_randomness'] and (rules or {}).get('continuity',{}).get('mode')=='propose':
            preferred=['handoff-gap','sustain-gap','bridge-gap','phrase-connect'] if evidence and any(g['seconds']>2.4 and not g['declared'] and g['cause']!='quiet-continuation-or-mix' for g in evidence.get('continuity',{}).get('gaps',[])) else ['bridge-gap','phrase-connect']
            actions=preferred+[a for a in actions if a not in preferred]
    targets=[e['event_id'] for e in parent['events'] if (targets is None or e['event_id'] in targets) and e['event_id'] not in (locks or parent['locks']).get('events',[])]
    for action in actions:
        for target in list(r.permutation(targets)):
            try:
                if action in ('phrase-connect','bridge-gap','sustain-gap','handoff-gap'):
                    from .continuity import change
                    p=change(parent,action,target,seed,snapshot,evidence,locks,rules,targets=requested_targets,scope=scope)
                else:p=mutate(parent,action,target,seed,snapshot,locks)
                p=constrain(p,rules or {})
            except ValueError:continue
            if p['events']==parent['events']:continue
            rows.append(p);break
        if len(rows)>=limit:break
    return rows

def scoped_vector(plan,report,scope=None):
    scope=scope or {'kind':'whole'}
    if scope.get('kind')=='whole':return vector(plan,report)
    selected=[e for e in report['events'] if e['event_id'] in scope.get('events',[])]
    if scope.get('kind') in ('event','relationship'):
        if not selected:raise ValueError('Select the event or sound combination before confirming feedback.')
        lo=min(e['start'] for e in selected);hi=max(e['active_until'] for e in selected)
    else:
        lo=float(scope.get('start',0));hi=float(scope.get('end',0))
        if scope.get('kind')=='section':
            section=next((s for s in plan['sections'] if s['start']<=lo<s['end']),None)
            if section:lo=section['start'];hi=section['end']
    if not 0<=lo<hi<=report['duration']+.01:raise ValueError('Feedback time range is invalid.')
    p=copy.deepcopy(plan);r=copy.deepcopy(report);p['duration']=hi-lo;p['events']=[];r['events']=[];r['duration']=hi-lo
    for e in report['events']:
        if e['active_until']<=lo or e['start']>=hi:continue
        row=copy.deepcopy(e);row['start']=max(lo,e['start'])-lo;row['duration']=max(.0,min(hi,e['start']+e['duration'])-max(lo,e['start']));row['active_until']=min(hi,e['active_until'])-lo;row['tail_seconds']=max(0,row['active_until']-row['start']-row['duration'])
        first=max(0,int((lo-e['start'])/.25));last=min(len(e['feature_frames']),int(np.ceil((hi-e['start'])/.25)));row['feature_frames']=copy.deepcopy(e['feature_frames'][first:last]);
        if not row['feature_frames']:continue
        from .features import summary
        row['processed_features']=summary(row['feature_frames']);r['events'].append(row);original=copy.deepcopy(next(v for v in plan['events'] if v['event_id']==e['event_id']));original['start']=row['start'];original['duration']=row['duration'];p['events'].append(original)
    p['sections']=[{**s,'start':max(lo,s['start'])-lo,'end':min(hi,s['end'])-lo} for s in p['sections'] if s['end']>lo and s['start']<hi]
    v=vector(p,r);v[len(FREQUENCY_FEATURES):]=continuity_descriptors(report,lo,hi)
    return np.clip(v,-4,4).tolist()
