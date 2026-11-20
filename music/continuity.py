"""Measured activity and explicit phrase connections, never a universal silence penalty.

Thresholds describe near-silence, not whether a pause makes musical sense. Original
PCM and the cache adapter stay unchanged; all cuts live in the composition plan.
"""
import copy
import numpy as np
from .common import digest

VERSION = 'activity-1'
FEATURES = ['interior_gap_fraction', 'long_gap_rate', 'longest_gap_fraction',
            'source_gap_fraction', 'gated_gap_fraction', 'declared_rest_fraction']
DEFAULTS = {'mode': 'propose', 'min_gap_seconds': .8, 'max_additions': 3}


def activity(audio, rate, hop_seconds=.02):
    x = np.asarray(audio, float)
    if x.ndim == 1: x = x[:, None]
    hop = max(1, round(rate * hop_seconds))
    energy = np.mean(x*x, axis=1)
    starts = np.arange(0, len(x), hop)
    rms = np.sqrt(np.add.reduceat(energy, starts) / np.minimum(hop, len(x)-starts)) if len(x) else np.array([])
    # Stereo energy, including antiphase signals. Very quiet recorded textures are
    # retained: no -40 dB gate or loudness normalization is applied to the audio.
    reference = float(np.quantile(rms[rms > 0], .9)) if np.any(rms > 0) else 0.
    threshold = max(1e-7, reference * 10**(-52/20))
    sounding = rms > threshold
    edges = np.flatnonzero(np.diff(np.r_[False, sounding, False]))
    spans = [[round(a*hop/rate, 6), round(min(len(x), b*hop)/rate, 6)] for a, b in zip(edges[::2], edges[1::2])]
    gaps = [[a[1], b[0]] for a, b in zip(spans, spans[1:]) if b[0]-a[1] >= .08-1e-7]
    return {'version': VERSION, 'duration': len(x)/rate, 'hop_seconds': hop/rate,
            'threshold_rms': threshold, 'reference_rms': reference, 'spans': spans,
            'interior_gaps': gaps, 'method': 'stereo RMS, 52 dB below nonzero frame reference; no audio gating'}


def intersects(spans, a, b):
    return any(start < b and end > a for start, end in spans)


def declared_rests(plan):
    return plan.get('rests', [{'start':s['start'], 'end':s['start']+s['transition']['seconds'], 'reason':'legacy planned drop'}
                              for s in plan['sections'] if s['transition']['kind']=='drop'])


def diagnose(audio, rate, plan, events):
    measured = activity(audio, rate)
    gaps = []
    for a, b in measured['interior_gaps']:
        if b-a < .3-1e-7: continue
        mid = (a+b)/2
        active = [e for e in events if e['start'] <= mid < e['active_until']]
        declared = any(r['start'] < b and r['end'] > a for r in declared_rests(plan))
        inputs = [e for e in active if intersects(e.get('input_activity', {}).get('spans', []), mid-.01-e['start'], mid+.01-e['start'])]
        sounding = [e for e in active if intersects(e.get('activity', {}).get('spans', []), mid-.01-e['start'], mid+.01-e['start'])]
        cause = ('declared-rest' if declared else 'arrangement' if not active else
                 'quiet-continuation-or-mix' if sounding else 'processing-or-gate' if inputs else 'source-near-silence')
        gaps.append({'start': a, 'end': b, 'seconds': round(b-a, 6), 'cause': cause,
                     'events': [e['event_id'] for e in active], 'declared': declared})
    return {**measured, 'gaps': gaps, 'notice': 'Measured near-silence; duration and source do not determine musical quality.'}


def descriptors(report, lo=0., hi=None):
    data = report.get('continuity', {})
    hi = report['duration'] if hi is None else hi
    duration = max(.01, hi-lo)
    gaps = [{**g, 'seconds': min(hi, g['end'])-max(lo, g['start'])} for g in data.get('gaps', []) if g['start'] < hi and g['end'] > lo]
    total = sum(g['seconds'] for g in gaps)
    return [total/duration, sum(g['seconds'] >= .8 for g in gaps)*10/duration,
            max([g['seconds'] for g in gaps] or [0])/duration,
            sum(g['seconds'] for g in gaps if g['cause'] == 'source-near-silence')/duration,
            sum(g['seconds'] for g in gaps if g['cause'] == 'processing-or-gate')/duration,
            sum(g['seconds'] for g in gaps if g['declared'])/duration]


def phrase_schedule(clip, measured, frames, rng, rate, max_piece_seconds=2.):
    """Explicit one-shot source ranges separated by short, recorded breaths."""
    spans = [(max(0, round(a*rate)), min(clip['end_frame']-clip['start_frame'], round(b*rate)))
             for a, b in measured['spans'] if b-a >= .08]
    if not spans: raise ValueError('No measured sounding fragment available; no substitute was used.')
    pieces = []; at = 0
    while at < frames:
        a, b = spans[int(rng.integers(len(spans)))]
        length = min(b-a, max(1, round(max_piece_seconds*rate)), frames-at)
        # Keep a recorded onset when possible instead of slicing arbitrary silence.
        if length <= 0: break
        pieces.append({'at_frame': at, 'source_start_frame': a, 'source_end_frame': a+length,
                       'fade_in_frames': min(length//4, round(.008*rate)),
                       'fade_out_frames': min(length//4, round(.04*rate)), 'gain': 1.})
        at += length + round(float(rng.uniform(.08, .22))*rate)
        if len(pieces) > 2048: raise ValueError('Phrase schedule exceeds the recorded event budget.')
    return pieces


def change(parent, action, target, seed, snapshot, evidence, locks, rules=None):
    from .plan import rng_for, finish_mutation
    if not evidence or evidence.get('continuity', {}).get('version') != VERSION:
        raise ValueError('Render the parent before proposing a measured phrase connection.')
    p = copy.deepcopy(parent); p['locks'] = copy.deepcopy(locks or parent['locks'])
    e = next((e for e in p['events'] if e['event_id'] == target), None)
    if e is None or target in p['locks'].get('events', []): raise ValueError('Choose an unlocked event.')
    clips = {c['id']: c for c in snapshot['clips']}; clip = clips[e['source_id']]
    measured = evidence.get('material_activity', {}).get(e['source_id'])
    if not measured: raise ValueError('Source activity has not been measured.')
    rng = rng_for(seed, target, action); sr = p['sample_rate']; changed = []
    def finish(trial, changed):
        result=finish_mutation(parent,trial,changed,action,snapshot,p['locks'])
        a,b=result['decision_log'][-1]['affected_range']
        if intersects([[r['start'],r['end']] for r in declared_rests(parent)],a,b):
            raise ValueError('The connection reaches a declared musical rest; it is preserved.')
        return result
    if action == 'phrase-connect':
        original=next(row for row in evidence['events'] if row['event_id']==target)
        minimum=(rules or {}).get('continuity',{}).get('min_gap_seconds',DEFAULTS['min_gap_seconds'])
        if not any(b-a>=minimum for a,b in original.get('activity',{}).get('interior_gaps',[])):
            raise ValueError('This event has no measured internal gap to reconnect; its sustained sound is preserved.')
        e['transform'].update(technique='phrase', speed=1., phase_creep=0.,
                              phrases=phrase_schedule(clip, measured, round(e['duration']*sr), rng, sr))
        e['transform']['offset_frame'] = e['transform']['phrases'][0]['source_start_frame']
        e['action'] = 'continue'; e['decision'] = {'origin': 'explicit measured phrase connection', 'source_analysis': VERSION}
        changed = [target]
    elif action == 'bridge-gap':
        options = {**DEFAULTS, **(rules or {}).get('continuity', {})}
        eligible = [g for g in evidence['continuity']['gaps'] if not g['declared'] and g['cause']!='quiet-continuation-or-mix' and g['seconds'] >= options['min_gap_seconds']]
        eligible = sorted(eligible, key=lambda g: (-g['seconds'], g['start']))
        for gap in eligible:
            if len(changed) >= options['max_additions']: break
            start = max(0., gap['start']-.04); end = min(p['duration'], gap['end']+.06)
            if end-start < .08: continue
            # One response at a time, at most a short phrase. A long rest is not
            # replaced by an endless bed. Remaining pauses stay visible/audible.
            duration = min(end-start, 2.4)
            if gap['seconds'] > duration: start += (gap['seconds']-duration)/2
            new = copy.deepcopy(e)
            new['event_id'] = 'bridge-'+digest({'parent':parent['plan_id'], 'seed':str(seed), 'target':target, 'gap':[gap['start'],gap['end']]})[:16]
            new.update(start=round(start, 6), duration=round(duration, 6), role='countervoice', action='respond', relation_to=target,
                       gain=e['gain']*.8, envelope={'attack':.008, 'release':min(.1, duration/4), 'shape':'sin2'})
            new['section_id'] = next((s['section_id'] for s in p['sections'] if s['start'] <= start < s['end']), e['section_id'])
            new['space'].update(tail_seconds=min(.2, e['space']['tail_seconds']), decay_seconds=min(.2, e['space']['decay_seconds']))
            new['transform'].update(technique='phrase', speed=1., phase_creep=0., wet=0., operations=[],
                                    phrases=phrase_schedule(clip, measured, round(duration*sr), rng, sr, max_piece_seconds=1.4))
            new['transform']['offset_frame'] = new['transform']['phrases'][0]['source_start_frame']
            new['decision'] = {'origin':'measured gap response', 'gap':gap, 'source_analysis':VERSION,
                               'selection':'excerpt from chosen recorded material; no claim of vocal identity'}
            trial = copy.deepcopy(p); trial['events'].append(new)
            try: finish(trial, changed+[new['event_id']])
            except ValueError: continue
            p['events'].append(new); changed.append(new['event_id'])
        if not changed: raise ValueError('No measured, unlocked gap accepts a short response.')
    else: raise ValueError('Unknown continuity action.')
    return finish(p, changed)
