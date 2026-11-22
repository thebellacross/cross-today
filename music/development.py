"""Long-form relationships. Explicit direction, never inferred preference labels.

Voices retain a source identity across scenes. Scenes describe shared evolution;
they do not truncate voices or reset their read positions. Every curve is saved.
"""
import copy
import numpy as np
from .common import digest

VERSION = 'development-1'
FEATURES = ['persistent_identity', 'audible_layering', 'shared_source_memory',
            'foreground_handover', 'spectral_trajectory', 'spatial_trajectory',
            'slow_change', 'layered_development']


def curve(points, position):
    """C1 smoothstep interpolation, positions measured in event-relative time."""
    p = np.asarray(points, float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all() or np.any(np.diff(p[:, 0]) <= 0):
        raise ValueError('Invalid saved development curve.')
    x = np.asarray(position)
    i = np.clip(np.searchsorted(p[:, 0], x, side='right') - 1, 0, len(p) - 2)
    t = np.clip((x - p[i, 0]) / (p[i + 1, 0] - p[i, 0]), 0, 1)
    return p[i, 1] + (p[i + 1, 1] - p[i, 1]) * t * t * (3 - 2 * t)


def points(values):
    return [[round(i / (len(values) - 1), 6), float(v)] for i, v in enumerate(values)]


def measured(clip, key):
    values = [f[key] for f in clip.get('analysis', []) if f['rms'] > 1e-6]
    return float(np.median(values)) if values else (clip.get('features', [.03])[0] if key == 'rms' else .2)


def arrange(plan, snapshot, settings):
    from .plan import event, rng_for, source_span
    rule = settings.get('development', {})
    if rule.get('mode') != 'evolving':
        return plan
    pace = rule.get('pace', 'slow')
    if pace not in ('slow', 'moderate'):
        raise ValueError('Unknown development pace.')
    seed, duration, controls = plan['seed'], plan['duration'], plan['controls']
    clips = snapshot['clips']; unique = {}
    # A source, not its number of cache segments, gets one place in the cast.
    for c in clips:
        if c['source_hash'] not in unique or c['seconds'] > unique[c['source_hash']]['seconds']:
            unique[c['source_hash']] = c
    pool = sorted(unique.values(), key=lambda c: c['source_hash'])
    random = controls['structure_randomness']
    order = list(rng_for(seed, 'development', 'cast').permutation(len(pool))) if random else list(range(len(pool)))
    cast = [pool[i] for i in order[:min(4, len(pool))]]
    # Time-resolved measurements decide a starting identity; no material is
    # globally penalized for noise, roughness, loudness or spectral overlap.
    cast.sort(key=lambda c: (measured(c, 'flux'), c['source_hash']))
    arcs = ['exchange-and-return', 'gather-and-dissolve', 'changing-perspective']
    arc = str(rng_for(seed, 'development', 'arc').choice(arcs)) if random else arcs[0]
    pivot = float(rng_for(seed, 'development', 'pivot').uniform(.48, .66)) if random else .57
    # Shared narrative positions, with different focus trajectories across arcs.
    boundaries = [0, .16, .34, pivot, .78, 1]
    names = ['emergence', 'coexistence', 'perspective-change', 'reframing', 'release']
    sections = [{'section_id': f'd{i:02}', 'start': a * duration, 'end': b * duration,
                 'process': arc, 'transition': {'kind': 'continuous', 'seconds': 0},
                 'purpose': names[i], 'foreground': None, 'density': None,
                 'variation_rate': 1 / max(1, duration * (b - a))}
                for i, (a, b) in enumerate(zip(boundaries, boundaries[1:]))]
    levels = {
        'exchange-and-return': [[.8, 1, .6, .28, .7, .8], [.22, .6, 1, .8, .35, .2], [.2, .55, .95, .7, .45, .15]],
        'gather-and-dissolve': [[.85, .95, .8, .72, .5, .32], [.25, .55, .85, 1, .6, .22], [.2, .6, 1, .9, .4, .12]],
        'changing-perspective': [[.8, .65, .25, .6, .9, .55], [.2, .8, .95, .4, .25, .65], [.3, .5, .8, 1, .6, .2]],
    }[arc]
    events = []
    maximum = min(len(cast), settings.get('max_events', 100))
    for i, clip in enumerate(cast[:maximum]):
        eid = f'voice-{i:02}'
        # Three interwoven identities and, when material permits, one brief
        # diversion. The opening identity spans the piece instead of restarting.
        start = [0, .12 if pace == 'moderate' else .19, .3 if pace == 'moderate' else .39, pivot][i] * duration
        stop = [1, .97, .91, min(.76, pivot + .1)][i] * duration
        role = 'foreground' if i == 0 else 'countervoice' if i < 3 else 'interruption'
        technique = 'tape'
        q = rng_for(seed, eid, 'development-transform')
        if i > 0 and controls['processing_intensity'] and q.random() < controls['processing_intensity']:
            technique = str(q.choice(['reverse', 'freeze', 'weather', 'mosaic', 'room']))
        if plan['form'] == 'loops' and controls['loop_activity']:
            technique = 'loop' if i != 3 else 'hits'
        if plan['form'] in ('fontana', 'automaton', 'drift') and i == 3:
            stop = min(stop, start + max(.5, duration * .035))
        if not controls['loop_activity']:
            stop = min(stop, start + clip['seconds'])
        e = event(seed, eid, next(s['section_id'] for s in sections if s['start'] <= start < s['end']),
                  clip, start, max(.05, stop - start), role, technique, controls, clips)
        e['motif_id'] = 'identity-' + clip['source_hash'][:12]
        e['action'] = 'persist' if i == 0 else 'interweave' if i < 3 else 'interrupt'
        e['relation_to'] = events[0]['event_id'] if events else None
        e['relations'] = [{'with': v['event_id'], 'kind': 'coexist-and-exchange'} for v in events if v['start'] + v['duration'] > start]
        # Keep the full prepared phrase, including native stereo. The seam is a
        # recorded overlap, not a fresh random source position on each repeat.
        length = clip['end_frame'] - clip['start_frame']
        e['transform']['read_window'] = {'start_frame': 0, 'end_frame': length,
            'crossfade_frames': min(length // 8, round(.08 * clip['sample_rate'])) if controls['loop_activity'] else 0,
            'repeat': bool(controls['loop_activity'])}
        e['transform']['offset_frame'] = 0; e['transform']['speed'] = 1.
        e['transform']['period_frames'] = length
        e['envelope'] = {'attack': min(e['duration'] * .18, duration * (.035 if i == 0 else .06)),
                         'release': min(e['duration'] * .22, duration * .09), 'shape': 'sin2'}
        # An explicit bounded input calibration makes quiet source identities
        # available to the arrangement; the dynamic curves remain independent.
        rms = measured(clip, 'rms')
        e['gain'] = float(np.clip(.035 / max(rms, .002), .12, 3.))
        e['level_calibration'] = {'source_nonzero_frame_rms': rms, 'target_rms': .035, 'max_gain': 3.}
        e['space'].update(wet=.12 * controls['space_motion'], tail_seconds=1.2 if controls['space_motion'] else 0,
                          decay_seconds=1.2, delay_seconds=.137 + .037 * i)
        pan = [-.25, .4, -.6, .1][i]
        motion = controls['space_motion']
        e['pan'] = {'start': pan, 'end': pan + [ .2, -.4, .35, -.1][i] * motion}
        value = levels[i] if i < 3 else [.15, .7, 1, .5, .15, .1]
        tone = controls['processing_intensity']
        # Complementary evolving emphases describe one possible coexistence.
        # They are not pitch correction and no tuning system is assumed.
        tilt = [-1, 1, .35, -.4][i]
        e['automation'] = {'version': VERSION, 'interpolation': 'smoothstep',
            'level': points(value), 'pan': points([pan, pan, pan - .25 * motion, e['pan']['end']]),
            'wet': points([.2 * motion, .08 * motion, .32 * motion, .12 * motion]),
            'bands': [points([1 - tilt * tone, 1, 1 + tilt * tone * .5, 1]),
                      points([1, 1 - tone * .3, 1 + tone * .2, 1]),
                      points([1 + tilt * tone, 1, 1 - tilt * tone * .5, 1])],
            'crossovers_hz': [350., min(1800., settings['sample_rate'] * .35)],
            'band_algorithm': 'windowed-overlap-add-2048-hop1024',
            'tail_policy': 'colour before spatial delay; automation endpoints held during tails'}
        if not motion:
            e['automation']['pan'] = points([pan, pan]); e['automation']['wet'] = points([0, 0])
        e['source_range'] = source_span(clip, e['transform'])
        e['source_range']['read_window'] = copy.deepcopy(e['transform']['read_window'])
        e['decision'].update(origin='explicit-development-direction', trajectory=arc)
        events.append(e)
    for s in sections:
        t = (s['start'] + s['end']) / 2
        active = [e for e in events if e['start'] <= t < e['start'] + e['duration']]
        s['foreground'] = max(active, key=lambda e: float(curve(e['automation']['level'], (t - e['start']) / e['duration'])))['event_id'] if active else None
        s['density'] = len(active) / max(1, len(events))
    plan.update(events=events, sections=sections, process=arc, rests=[],
                ending={'kind': 'fade', 'seconds': min(2., duration * .03)})
    # Existing bus/bit/transform capabilities remain available; no new gate or
    # bus decision is introduced to simulate a dramatic change.
    plan['development'] = {'version': VERSION, 'mode': 'evolving', 'pace': pace,
        'arc': arc, 'pivot': pivot, 'cast': [{'motif_id': e['motif_id'], 'source_hash': e['source_hash'], 'event_id': e['event_id']} for e in events],
        'origin': 'explicit user direction, not learned labels', 'section_boundaries_reset_audio': False,
        'constraints': 'Loop-off limits each identity to one source pass.' if not controls['loop_activity'] else ''}
    plan['decision_log'].append({'origin': 'explicit-development-direction', 'arc': arc,
                                'choice': 'persistent interwoven voices with recorded trajectories'})
    plan.pop('plan_id', None); plan['plan_id'] = digest(plan)
    return plan


def colour(audio, rate, automation):
    bands = automation['bands']
    if all(all(p[1] == 1 for p in c) for c in bands):
        return audio
    # Bounded FFT size: a ten-minute track never requires a ten-minute FFT.
    size, hop = 2048, 1024
    x = np.pad(audio, ((hop, hop), (0, 0))); out = np.zeros_like(x)
    window = np.sqrt(np.hanning(size + 1)[:-1]); norm = np.zeros(len(x))
    f = np.fft.rfftfreq(size, 1 / rate); low, high = automation['crossovers_hz']
    lows = 1 / (1 + (f / low) ** 4); highs = 1 - 1 / (1 + (f / high) ** 4)
    weights = np.column_stack((lows, 1 - lows - highs, highs))
    for at in range(0, len(x) - hop, hop):
        n = min(size, len(x) - at); block = np.pad(x[at:at+n], ((0, size-n), (0, 0)))
        gains = np.array([float(curve(c, at / max(1, len(audio)))) for c in bands])
        transformed = np.fft.irfft(np.fft.rfft(block * window[:, None], axis=0) * (weights @ gains)[:, None], n=size, axis=0)
        out[at:at+n] += transformed[:n] * window[:n, None]; norm[at:at+n] += window[:n] ** 2
    return (out / np.maximum(norm, 1e-12)[:, None])[hop:hop+len(audio)]


def describe(plan, report):
    """Time-ordered actual energies, overlap, perspective and spectral movement.

    These descriptors are neutral; no amount of layering is a quality target.
    """
    duration = plan['duration']; events = report['events']; buckets = []
    for t in np.linspace(0, duration, 33, endpoint=False):
        rows = []
        for e in events:
            idx = int((t - e['start']) / .25)
            if t < e['start'] or not 0 <= idx < len(e['feature_frames']): continue
            f = e['feature_frames'][idx]
            if f['rms'] <= 1e-6: continue
            rows.append((e, f))
        weight = sum(f['rms'] for _, f in rows)
        lead = max(rows, key=lambda p:p[1]['rms'])[0]['source_hash'] if rows else None
        buckets.append({'time': float(t), 'layers': len(rows), 'foreground': lead,
            'centroid': sum(f['centroid'] * f['rms'] for _, f in rows) / max(weight, 1e-12),
            'position': sum(np.mean(f.get('band_pan', [0])) * f['rms'] for _, f in rows) / max(weight, 1e-12),
            'sources': sorted({e['source_hash'] for e, _ in rows})})
    delta = np.abs(np.diff([b['centroid'] for b in buckets])); spatial = np.abs(np.diff([b['position'] for b in buckets]))
    overlap = float(np.mean([b['layers'] >= 2 for b in buckets]))
    leads = [b['foreground'] for b in buckets if b['foreground']]
    switches = sum(a != b for a, b in zip(leads, leads[1:])) / max(1, len(leads)-1)
    memory = [len(set(a['sources']) & set(b['sources'])) / max(1, len(set(a['sources']) | set(b['sources']))) for a,b in zip(buckets,buckets[1:])]
    persistence = max([sum(e['duration'] for e in events if e['source_hash'] == h) / duration for h in {e['source_hash'] for e in events}] or [0])
    values = [min(2., persistence), overlap, float(np.mean(memory)), switches,
              float(np.sum(delta)), float(np.sum(spatial)), float(np.mean(delta < .04)), overlap * float(np.sum(delta))]
    return {'version': VERSION, 'windows': buckets, 'features': values,
            'notice': 'Measured relationships over time; not a musical quality score.'}


def change(parent, action, target, seed, snapshot, locks=None):
    from .plan import finish_mutation
    p = copy.deepcopy(parent); locked = copy.deepcopy(locks or parent['locks']); p['locks'] = locked
    e = next(v for v in p['events'] if v['event_id'] == target)
    if 'automation' not in e:
        raise ValueError('This action requires a plan with persistent voice trajectories.')
    changed = [target]
    if action == 'focus-exchange':
        partners = [v for v in p['events'] if v['event_id'] != target and v['event_id'] not in locked.get('events', []) and
                    'automation' in v and min(e['start']+e['duration'], v['start']+v['duration']) - max(e['start'],v['start']) > parent['duration']*.2]
        if not partners: raise ValueError('No overlapping voice is available for a focus exchange.')
        partner = sorted(partners, key=lambda v:v['event_id'])[0]
        # Reverse complementary emphasis while freezing source, timing, all
        # transform seeds and spatial paths. Every affected voice is audited.
        for v in (e, partner):
            v['automation']['level'] = [[t, 1.15-value] for t,value in v['automation']['level']]
        changed.append(partner['event_id'])
    elif action == 'spectral-evolution':
        if not p['controls']['processing_intensity']: raise ValueError('Frequency processing is disabled.')
        e['automation']['bands'] = [[[t, 2-value] for t,value in b] for b in e['automation']['bands']]
    elif action == 'development-pace':
        for key in ('level', 'pan', 'wet'):
            e['automation'][key] = [[round(t**.65, 8), v] for t,v in e['automation'][key]]
        e['automation']['bands'] = [[[round(t**.65, 8), v] for t,v in b] for b in e['automation']['bands']]
    else: raise ValueError('Unknown development decision.')
    return finish_mutation(parent, p, changed, action, snapshot, locked)
