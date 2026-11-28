"""Pitch-class evidence for material pairing, independent of preference labels.

This is a conservative spectral-peak chroma estimate, not chord recognition or
automatic tuning. Native channels contribute energy separately. Untuned/noisy
material is not assigned a key, penalized, or pitch shifted.
"""
import copy
from pathlib import Path
import json
import numpy as np
from .common import digest, save_json, file_hash
from .library import read_clip

VERSION = 'pitch-evidence-1'
FEATURES = ['tonal_overlap', 'tonal_affinity', 'tonal_tension',
            'three_voice_time', 'identity_turnover', 'section_density_change',
            'level_spread', 'peak_crest', 'delay_presence', 'room_presence']


def pitch_frame(audio, rate):
    x = np.asarray(audio, float)
    if x.ndim == 1:
        x = x[:, None]
    size = 1 << int(np.ceil(np.log2(max(2048, rate * .5))))
    x = np.pad(x[:size], ((0, max(0, size - len(x))), (0, 0)))
    power = np.mean(np.abs(np.fft.rfft(x * np.hanning(size)[:, None], axis=0)) ** 2, axis=1)
    hz = np.fft.rfftfreq(size, 1 / rate)
    band = (hz >= 55) & (hz <= min(3500, rate * .45))
    total = float(power[band].sum())
    if total < 1e-12:
        return {'chroma': [0.] * 12, 'confidence': 0.}
    peaks = np.flatnonzero((power[1:-1] > power[:-2]) & (power[1:-1] >= power[2:])) + 1
    peaks = [int(i) for i in peaks if band[i] and power[i] > float(power.max()) * .006]
    peaks = sorted(peaks, key=lambda i: power[i], reverse=True)[:36]
    chroma = np.zeros(12); concentrated = 0.
    for i in peaks:
        left, center, right = np.log(power[i-1:i+2] + 1e-25)
        den = left - 2 * center + right
        offset = float(np.clip(.5 * (left-right) / den, -.5, .5)) if abs(den) > 1e-12 else 0.
        frequency = (i + offset) * rate / size
        midi = 69 + 12 * np.log2(frequency / 440.)
        distance = (np.arange(12) - midi + 6) % 12 - 6
        weight = np.sqrt(power[i]) / max(1., frequency / 500.) ** .25
        chroma += weight * np.exp(-.5 * (distance / .32) ** 2)
        concentrated += power[max(0, i-1):i+2].sum()
    chroma /= max(1e-20, float(chroma.sum()))
    # Broad-band noise can have FFT peaks. Require concentrated energy and a
    # nonuniform pitch-class profile before making any harmonic decision.
    selectivity = max(0., (float(np.linalg.norm(chroma)) - 1 / np.sqrt(12)) / (1 - 1 / np.sqrt(12)))
    confidence = float(np.clip(concentrated / total, 0, 1) * np.clip(selectivity * 2.2, 0, 1))
    return {'chroma': chroma.tolist(), 'confidence': confidence}


def analyze(audio, rate):
    x = np.asarray(audio, float)
    if x.ndim == 1:
        x = x[:, None]
    rows = []; hop = max(1, round(rate * 1.))
    for at in range(0, len(x), hop):
        part = x[at:min(len(x), at + 2 * hop)]
        rms = float(np.sqrt(np.mean(part ** 2)))
        row = pitch_frame(part, rate)
        rows.append({**row, 'start': at / rate, 'end': min(len(x), at + 2 * hop) / rate,
                     'rms': rms, 'peak': float(np.max(np.abs(part)))})
    audible = [r for r in rows if r['rms'] > max(1e-7, max([v['rms'] for v in rows] or [0]) * .02)]
    weights = np.array([r['confidence'] * r['rms'] for r in audible])
    chroma = np.average([r['chroma'] for r in audible], axis=0, weights=weights).tolist() if weights.sum() > 1e-12 else [0.] * 12
    return {'version': VERSION, 'chroma': chroma,
            'confidence': float(np.median([r['confidence'] for r in audible])) if audible else 0.,
            'windows': rows, 'method': 'stereo-energy spectral peaks; A440 pitch classes; no key or instrument label'}


def materials(snapshot, cache):
    """Derived measurements are cached by PCM hash; immutable snapshots stay intact."""
    result = {}; root = Path(cache) / '.musical-analysis' / VERSION
    for clip in snapshot['clips']:
        path = root / (clip['cache_sha256'] + '.json')
        if path.exists():
            value = json.loads(path.read_text())
        else:
            source = Path(cache) / clip['cache_file']
            if file_hash(source) != clip['cache_sha256']:
                raise ValueError('Musical analysis requires the frozen source bytes.')
            audio, rate = read_clip(source, native=True)
            value = analyze(audio, rate); value['pcm_sha256'] = clip['cache_sha256']
            save_json(path, value)
        if value.get('version') != VERSION or value.get('pcm_sha256') != clip['cache_sha256']:
            raise ValueError('Musical analysis cache does not match the source.')
        result[clip['id']] = value
    return result


def excerpt(evidence, start, end):
    rows = [r for r in evidence.get('windows', []) if r['start'] < end and r['end'] > start and r['rms'] > 1e-7]
    if not rows:
        return {k: evidence.get(k, [0.] * 12 if k == 'chroma' else 0.) for k in ('chroma', 'confidence')}
    weights = np.array([r['rms'] for r in rows])
    return {'chroma': np.average([r['chroma'] for r in rows], weights=weights, axis=0).tolist(),
            'confidence': float(np.average([r['confidence'] for r in rows], weights=weights))}


def affinity(a, b):
    if min(a.get('confidence', 0), b.get('confidence', 0)) < .22:
        return None
    # A soft pairing preference, never a universal definition of musical beauty.
    # Shared notes, thirds and fifths are favored; seconds/tritones remain possible.
    weights = np.array([1., -.65, .05, .48, .55, .65, -.55, .8, .48, .4, -.1, -.5])
    intervals = (np.arange(12)[:, None] - np.arange(12)[None, :]) % 12
    weights = (weights[intervals] + weights[(-intervals) % 12]) * .5
    return float(np.asarray(a['chroma']) @ weights @ np.asarray(b['chroma']))


def describe(plan, report):
    values = []; layer_counts = []; leads = []; affinities = []; tonal = 0; pairs = 0
    for t in np.arange(0, report['duration'], .5):
        sounding = []
        for e in report['events']:
            i = int((t-e['start']) / .25)
            if t < e['start'] or not 0 <= i < len(e['feature_frames']):
                continue
            f = e['feature_frames'][i]
            if f['rms'] > 1e-5:
                sounding.append((e, f))
        layer_counts.append(len(sounding))
        leads.append(max(sounding, key=lambda x: x[1]['rms'])[0]['source_hash'] if sounding else None)
        for i, (_, a) in enumerate(sounding):
            for _, b in sounding[i+1:]:
                pairs += 1
                score = affinity(a.get('pitch', {}), b.get('pitch', {}))
                if score is not None:
                    tonal += 1; affinities.append(score)
        if sounding:
            levels = [20 * np.log10(max(1e-9, f['rms'])) for _, f in sounding]
            values.append(max(levels) - min(levels))
    sections = [np.mean([n for t, n in zip(np.arange(0, report['duration'], .5), layer_counts) if s['start'] <= t < s['end']] or [0]) for s in plan['sections']]
    events = plan['events']; avg = lambda x: float(np.mean(x)) if len(x) else 0.
    dynamics = report.get('mastering',{}).get('dynamics',[])
    crest = avg([r['crest'] for r in dynamics if r['rms']>1e-7]) if dynamics else report.get('mix_features', {}).get('crest', 0)
    desc = [tonal/max(1, pairs), avg(affinities), avg([max(0., -a) for a in affinities]),
            avg(np.array(layer_counts) >= 3), sum(a != b for a, b in zip(leads, leads[1:]))/max(1, len(leads)-1),
            avg(np.abs(np.diff(sections)))/5, avg(values)/24,
            crest/12,
            avg([bool(e.get('effects', {}).get('delay')) for e in events]),
            avg([bool(e.get('effects', {}).get('reverb')) for e in events])]
    return {'version': VERSION, 'features': desc, 'audible_three_voice_fraction': desc[3],
            'mean_tonal_affinity': avg(affinities), 'tonal_pairs_measured': tonal,
            'notice': 'Measured pitch-class and arrangement relationships, not a quality score.'}
