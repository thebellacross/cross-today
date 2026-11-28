"""Phrase-level stories: changing casts, exchanges, convergence and recollection.

Each event is a bounded source phrase. Repetition is explicit and limited; a
scene name never substitutes for a change in the rendered arrangement.
"""
import copy
import numpy as np
from .common import digest
from .development import points, refresh_focus
from .musical import affinity, excerpt
from .mixing import master_settings

VERSION = 'story-1'
ACTIONS = ['more-dialogue', 'earlier-recollection', 'tonal-neighbor',
           'level-balance', 'echo-space', 'room-space', 'gentler-glue']
ARCS = {
    'conversation-and-return': [('arrival', 2), ('question', 3), ('answer', 4), ('distance', 2), ('convergence', 5), ('recollection', 3), ('release', 1)],
    'gathering-and-release': [('arrival', 1), ('opening-out', 3), ('convergence', 5), ('distance', 2), ('answer', 4), ('recollection', 2), ('release', 1)],
    'crossing-perspectives': [('arrival', 2), ('answer', 4), ('distance', 2), ('convergence', 5), ('handover', 3), ('recollection', 2), ('release', 1)],
}


def source_window(clip, evidence, seconds, rng, reference=None):
    length = clip['seconds']; seconds = min(length, seconds)
    windows = evidence.get('windows', [])
    maximum = max([r['rms'] for r in windows] or [0])
    starts = [r['start'] for r in windows if r['rms'] > max(1e-7, maximum * .06) and r['start']+seconds <= length+.001]
    if not starts:
        starts = [0.]
    choices = []
    for start in starts:
        pitch = excerpt(evidence, start, start+seconds)
        score = affinity(reference or {}, pitch)
        choices.append((start, pitch, score))
    if reference and reference.get('confidence', 0) >= .22:
        # Favor, but do not mandate, compatible excerpts; leave expressive tension.
        choices.sort(key=lambda row: row[2] if row[2] is not None else 0., reverse=True)
        choices = choices[:max(1, int(np.ceil(len(choices)*.35)))]
    return choices[int(rng.integers(len(choices)))]


def make_phrase(plan, clip, eid, section, start, seconds, role, settings, analysis, reference=None, action='enter'):
    from .plan import event, rng_for, seed_for, source_span
    seed = plan['seed']; c = plan['controls']; sr = plan['sample_rate']; r = rng_for(seed, eid, 'phrase')
    # Never turn a sub-second sample into an uninterrupted ten-minute loop.
    window_seconds = min(seconds, clip['seconds'], float(r.uniform(6, 22)))
    at, pitch, relation = source_window(clip, analysis.get(clip['id'], {}), window_seconds, r, reference)
    repeats = bool(c['loop_activity'] and window_seconds < seconds)
    seconds = min(seconds, window_seconds * (3 if repeats else 1), plan['duration']-start)
    seconds = max(.03, seconds)
    e = event(seed, eid, section['section_id'], clip, start, seconds, role, 'tape', c, [clip])
    a = round(at*sr); b = min(clip['end_frame']-clip['start_frame'], a+max(1, round(window_seconds*sr)))
    e['transform'].update(offset_frame=0, speed=1., wet=0., operations=[],
        read_window={'start_frame': a, 'end_frame': b, 'repeat': repeats,
                     'crossfade_frames': min((b-a)//10, round(.035*sr)) if repeats else 0})
    # Only the supporting/returning phrases receive occasional reversible colour.
    if role != 'foreground' and c['processing_intensity'] and r.random() < c['processing_intensity']*.55:
        e['transform'].update(technique='reverse', offset_frame=b-a-1)
    e['gain'] = 1.
    targets = {'foreground': -23., 'countervoice': -28., 'background': -33., 'interruption': -29.}
    e['mixing'] = {'target_dbfs': targets[role], 'min_gain_db': -24., 'max_gain_db': 18.}
    e['envelope'] = {'attack': min(.6, seconds*.12), 'release': min(1.8, seconds*.22), 'shape': 'sin2'}
    pan = 0. if role == 'foreground' else float(r.uniform(-.72, .72))
    e['pan'] = {'start': pan, 'end': float(np.clip(pan+r.uniform(-.25,.25)*c['space_motion'], -.85, .85))}
    e['space'].update(wet=0., tail_seconds=0., decay_seconds=0., width=c['stereo_width'])
    e['automation'] = {'version': VERSION, 'interpolation': 'smoothstep',
        'level': points([.78, 1., .87, .62] if role == 'foreground' else [.4, .86, 1., .45]),
        'pan': points([pan, e['pan']['end']]), 'wet': points([0, 0]),
        'bands': [points([1.,1.]) for _ in range(3)], 'crossovers_hz': [350., min(1800.,sr*.35)]}
    e['effects'] = {}; motion = c['space_motion']; processing = c['processing_intensity']
    if motion and (role != 'foreground' or section['purpose'] in ('distance','release','recollection')):
        if r.random() < .65:
            delay = float(r.choice([.1875,.25,.375,.5])); taps = 4
            e['effects']['delay'] = {'seconds': delay, 'taps': taps, 'feedback': .42, 'wet': .32*motion}
            e['space']['tail_seconds'] = delay*taps
        if r.random() < .7:
            decay = float(r.uniform(.6, 1.8))
            e['effects']['reverb'] = {'seconds': decay, 'predelay_seconds': .018, 'wet': .24*motion,
                                      'seed': str(seed_for(seed, eid, 'room'))}
            e['space']['tail_seconds'] = max(e['space']['tail_seconds'], decay)
    if processing and action == 'return':
        e['effects']['chorus'] = {'delay_seconds': .018, 'depth_seconds': .003,
                                 'rate_hz': .37, 'wet': .3*processing}
    if processing and role == 'countervoice' and r.random() < .35:
        e['effects']['saturation'] = {'drive': 2., 'wet': .4*processing}
    e['motif_id'] = 'identity-'+clip['source_hash'][:12]
    e['action'] = action; e['pitch_evidence'] = pitch
    e['harmonic_relation'] = {'affinity': relation if reference else None,
                              'method': 'pitch-class pairing; no retuning or key assertion'}
    e['source_range'] = source_span(clip, e['transform'])
    e['decision'].update(origin='explicit-story-direction', phrase_window_seconds=(b-a)/sr,
                         maximum_passes=3, source_level_target=targets[role])
    return e


def arrange(plan, snapshot, settings, analysis=None):
    from .plan import rng_for
    analysis = analysis or {}; rule = settings.get('development', {})
    if rule.get('mode') != 'story':
        return plan
    seed = plan['seed']; duration = plan['duration']; random = plan['controls']['structure_randomness']
    r = rng_for(seed, 'story'); clips = snapshot['clips']; by_source = {}
    for clip in clips:
        by_source.setdefault(clip['source_hash'], []).append(clip)
    identities = sorted(by_source)
    if random:
        identities = list(r.permutation(identities))
    # Keep a recognizable cast, but use different real excerpts/segments of it.
    cast = identities[:min(len(identities), 7)]
    arc = str(r.choice(list(ARCS))) if random else 'conversation-and-return'
    base = ARCS[arc]; budget = int(settings.get('max_events', 100))
    count = max(2, min(14, round(duration/(24 if rule.get('pace') == 'slow' else 18)), max(2, budget//3)))
    if duration < 30: count = min(count, 4)
    stages = [base[min(len(base)-1, round(i*(len(base)-1)/max(1,count-1)))] for i in range(count)]
    weights = r.uniform(.75, 1.25, count) if random else np.ones(count)
    boundaries = np.r_[0, np.cumsum(weights/weights.sum()*duration)]; boundaries[-1] = duration
    sections = []; events = []; first = {}; last_lead = None
    for i, (purpose, density) in enumerate(stages):
        a, b = map(float, boundaries[i:i+2]); length = b-a
        section = {'section_id':f'n{i:02d}', 'start':a, 'end':b, 'purpose':purpose,
            'process':arc, 'transition':{'kind':'handoff' if i%2 else 'crossfade', 'seconds': min(1.2,length*.08)},
            'foreground':None, 'density':density/5, 'variation_rate':1/max(1,length)}
        sections.append(section)
        if len(events) >= budget: continue
        lead_id = cast[0] if purpose in ('arrival','recollection','release') else cast[(i+1)%len(cast)]
        if lead_id == last_lead and len(cast)>1 and purpose not in ('recollection','release'):
            lead_id = cast[(cast.index(lead_id)+1)%len(cast)]
        last_lead = lead_id
        pool = by_source[lead_id]; lead_clip = pool[int(r.integers(len(pool))) if random else i%len(pool)]
        lead_length = min(32., duration*.28, length*.78)
        lead = make_phrase(plan, lead_clip, f'n{i:02d}-lead', section, a, lead_length, 'foreground', settings, analysis,
                           action='return' if lead_id in first else 'enter')
        lead['relation_to'] = first.get(lead_id)
        first.setdefault(lead_id, lead['event_id']); events.append(lead)
        # The second phrase is a response, often a different source rather than
        # an endlessly repeated background. Dense scenes admit 3–5 identities.
        voices = min(5, len(cast), max(1, density), budget-len(events)+1)
        used = {lead_id}
        for j in range(1, voices):
            available = [c for c in clips if c['source_hash'] in cast and c['source_hash'] not in used] or [c for c in clips if c['source_hash'] != lead_id] or [lead_clip]
            if random:
                available = [available[k] for k in r.permutation(len(available))]
            tension = bool(random and purpose == 'convergence' and r.random()<.22)
            if not tension:
                available.sort(key=lambda c: affinity(lead['pitch_evidence'], analysis.get(c['id'], {})) or 0., reverse=True)
            # Several compatible choices remain; names/instruments are never guessed.
            pick = min(len(available), 3) if random else 1
            clip = available[int(r.integers(pick))] if random else available[0]
            used.add(clip['source_hash'])
            start = a+length*([0., .22, .08, .36, .5][j])
            span = min(28., length*([0., .72, .83, .53, .44][j]), duration*.24)
            role = 'countervoice' if j in (1,3) else 'background'
            e = make_phrase(plan, clip, f'n{i:02d}-v{j}', section, start, span, role, settings, analysis,
                            None if tension else lead['pitch_evidence'], 'return' if clip['source_hash'] in first else 'respond')
            e['relation_to'] = first.get(clip['source_hash'], lead['event_id'])
            e['harmonic_relation']['intentional_tension_allowed'] = tension
            first.setdefault(clip['source_hash'], e['event_id']); events.append(e)
        # Cover a long scene with another phrase rather than lengthening a tiny
        # loop. The exit/re-entry remains visible and audibly meaningful.
        if b-max(e['start']+e['duration'] for e in events if e['section_id']==section['section_id']) > max(2.,length*.18) and len(events)<budget:
            at = max(a+length*.5, max(e['start']+e['duration'] for e in events if e['section_id']==section['section_id'])-.6)
            clip = by_source[cast[(i+2)%len(cast)]][0]
            e = make_phrase(plan, clip, f'n{i:02d}-reply', section, at, min(25.,b-at), 'countervoice', settings, analysis, lead['pitch_evidence'], 'respond')
            e['relation_to'] = lead['event_id']; events.append(e)
    plan.update(events=events, sections=sections, process=arc, rests=[],
                ending={'kind':'fade', 'seconds':min(2.,duration*.03)}, master_gain=1.)
    plan['mastering'] = master_settings()
    plan['development'] = {'version': VERSION, 'mode':'story', 'pace':rule.get('pace','moderate'), 'arc':arc,
        'cast':[{'source_hash':h,'motif_id':'identity-'+h[:12]} for h in cast],
        'origin':'explicit user direction; no inferred preference labels',
        'section_boundaries_reset_audio':False,
        'constraints':'Bounded phrases, limited repeats, changing leads, sparse/dense contrast and audible returns.'}
    plan['musical_analysis'] = {'version':'pitch-evidence-1', 'materials':analysis,
        'limits':'Pitch evidence is approximate. Environmental and uncertain sounds stay untuned; no chord labels are asserted.'}
    refresh_focus(plan)
    plan['decision_log'].append({'origin':'explicit-story-direction','arc':arc,
                                'choice':'phrase exchanges, changing casts, related tonal excerpts and controlled tension'})
    plan.pop('plan_id',None); plan['plan_id'] = digest(plan)
    return plan


def change(parent, action, target, seed, snapshot, locks=None):
    from .plan import rng_for, finish_mutation
    p = copy.deepcopy(parent); locked = copy.deepcopy(locks or parent['locks']); p['locks'] = locked
    if p.get('development', {}).get('mode') != 'story':
        raise ValueError('This comparison needs a new phrase-story plan.')
    e = next(v for v in p['events'] if v['event_id'] == target); changed = [target]
    section = next(s for s in p['sections'] if s['section_id'] == e['section_id'])
    analysis = p['musical_analysis']['materials']; clips = snapshot['clips']
    if action in ('more-dialogue','tonal-neighbor'):
        peers = [v for v in p['events'] if v['event_id'] != target and min(v['start']+v['duration'],e['start']+e['duration'])>max(v['start'],e['start'])]
        reference = (max(peers,key=lambda v:v['role']=='foreground') if peers else e)['pitch_evidence']
        used = {e['source_hash'], *(v['source_hash'] for v in peers)}
        available = [c for c in clips if c['source_hash'] not in used and
                     (action != 'tonal-neighbor' or c['seconds'] >= e['duration']/(3 if p['controls']['loop_activity'] else 1))]
        available.sort(key=lambda c:affinity(reference,analysis.get(c['id'],{})) if affinity(reference,analysis.get(c['id'],{})) is not None else -1,reverse=True)
        if not available: raise ValueError('Another source is needed for a material relationship comparison.')
        clip = available[0]
        if action=='tonal-neighbor':
            if reference.get('confidence',0)<.22 or analysis.get(clip['id'],{}).get('confidence',0)<.22:
                raise ValueError('The material has insufficient pitch evidence for this comparison.')
            new = make_phrase(p,clip,target,section,e['start'],e['duration'],e['role'],{},analysis,reference,e['action'])
            # Hold timing, envelopes, roles and space. Only the audible material
            # and its static input calibration change.
            for key in ('duration','envelope','automation','pan','space','effects','mixing','relation_to'):
                new[key] = copy.deepcopy(e[key])
            new['transform']['read_window']['repeat'] = bool(p['controls']['loop_activity'])
            if not p['controls']['loop_activity'] and new['duration']>clip['seconds']:
                raise ValueError('Replacement is too short while looping is disabled.')
            p['events'][p['events'].index(e)] = new
        else:
            if not p['controls']['structure_randomness']:raise ValueError('Structure changes are disabled.')
            eid = 'dialogue-'+digest({'parent':parent['plan_id'],'target':target,'seed':str(seed)})[:12]
            start = min(section['end']-.1,e['start']+min(3.,e['duration']*.25))
            new = make_phrase(p,clip,eid,section,start,min(e['duration']*.6,section['end']-start),
                              'countervoice',{},analysis,reference,'respond')
            new['relation_to'] = target; p['events'].append(new); changed = [eid]
    elif action=='earlier-recollection':
        if not p['controls']['structure_randomness']:raise ValueError('Structure changes are disabled.')
        if e['action']!='return':raise ValueError('Select a returning phrase.')
        e['start'] = max(0.,e['start']-min(8.,p['duration']*.08))
    elif action=='level-balance':
        e['mixing']['target_dbfs'] += -3 if e['role']=='foreground' else 3
    elif action in ('echo-space','room-space'):
        if not p['controls']['space_motion']:raise ValueError('Spatial processing is disabled.')
        if action=='echo-space':
            e['effects']['delay'] = {'seconds':.375,'taps':4,'feedback':.45,'wet':.18}
            e['space']['tail_seconds'] = max(e['space']['tail_seconds'],1.5)
        else:
            e['effects']['reverb'] = {'seconds':1.6,'predelay_seconds':.025,'wet':.16,'seed':str(seed)}
            e['space']['tail_seconds'] = max(e['space']['tail_seconds'],1.6)
    elif action=='gentler-glue':
        p['mastering']['compressor']['mix'] *= .35
        changed = []
        if locked.get('regions'):raise ValueError('Master compression changes the locked mix region.')
    else:raise ValueError('Unknown story comparison.')
    if {v['source_hash'] for v in p['events']} != {v['source_hash'] for v in parent['events']}:
        p['development']['cast']=[{'source_hash':h,'motif_id':'identity-'+h[:12]}
                                  for h in dict.fromkeys(v['source_hash'] for v in p['events'])]
    return finish_mutation(parent,p,changed,action,snapshot,locked)
