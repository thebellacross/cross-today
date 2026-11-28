"""Recorded gain staging, stereo effects and a gentle peak-protected master.

Legacy plans never enter this chain. Processing is deterministic with the pinned
FFmpeg binary. Measurements and all settings travel with the composition plan.
"""
import subprocess
import numpy as np
from .common import ffmpeg

VERSION = 'mix-chain-1'


def active_rms(x, rate):
    hop = max(1, round(rate * .2))
    rms = np.array([np.sqrt(np.mean(part * part)) for part in np.array_split(x, max(1, int(np.ceil(len(x)/hop))))])
    active = rms[rms > max(1e-8, float(rms.max(initial=0)) * .015)]
    return float(np.percentile(active, 65)) if len(active) else 0.


def filter_audio(x, rate, chain):
    data = np.asarray(x, dtype='<f8')
    result = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'f64le', '-ar', str(rate), '-ac', '2', '-i', 'pipe:0',
        '-af', chain, '-ar', str(rate), '-ac', '2', '-f', 'f64le', 'pipe:1'],
        input=data.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    if result.returncode:
        raise ValueError('The saved mixing chain could not be rendered.')
    y = np.frombuffer(result.stdout, dtype='<f8').reshape(-1, 2).copy()
    if not np.isfinite(y).all():
        raise ValueError('Mixing produced non-finite audio.')
    if abs(len(y)-len(x)) > 2:
        raise ValueError('The compensated mixing chain changed the event duration.')
    return np.pad(y, ((0, max(0, len(x)-len(y))), (0, 0)))[:len(x)]


def gain_stage(x, rate, settings):
    measured = active_rms(x, rate)
    target = 10 ** (settings['target_dbfs'] / 20)
    gain_db = float(np.clip(20 * np.log10(target / max(measured, 1e-12)),
                            settings['min_gain_db'], settings['max_gain_db'])) if measured > 1e-8 else 0.
    y = x * 10 ** (gain_db / 20)
    # One gain for the whole phrase, not an AGC that pumps up every quiet moment.
    return y, {'algorithm': VERSION, 'active_rms_dbfs': 20*np.log10(max(measured, 1e-12)),
               'gain_db': gain_db, 'target_dbfs': settings['target_dbfs'],
               'bounded': gain_db in (settings['min_gain_db'], settings['max_gain_db'])}


def insert_effects(x, rate, settings):
    y = x.copy()
    if settings.get('saturation'):
        s = settings['saturation']; drive = s['drive']; wet = s['wet']
        y = (1-wet)*y + wet*np.tanh(y*drive)/drive
    if settings.get('chorus'):
        s = settings['chorus']; positions = np.arange(len(y), dtype=float)
        # Linked L/R rate, distinct phase; no mono downmix or channel swapping.
        wet = np.zeros_like(y)
        for channel in range(2):
            delay = rate*(s['delay_seconds']+s['depth_seconds']*np.sin(2*np.pi*s['rate_hz']*positions/rate+channel*np.pi*.5))
            wet[:, channel] = np.interp(positions-delay, positions, y[:, channel], left=0, right=0)
        y = (1-s['wet'])*y+s['wet']*wet
    return y


def sends(x, rate, settings, tail_seconds):
    length = len(x)+round(tail_seconds*rate); out = np.pad(x, ((0, length-len(x)), (0, 0)))
    if settings.get('delay'):
        s = settings['delay']; step = round(s['seconds']*rate)
        for tap in range(1, s['taps']+1):
            at = step*tap; n = min(len(x), length-at)
            if n > 0:
                out[at:at+n] += x[:n, ::-1 if tap % 2 else 1]*s['wet']*s['feedback']**(tap-1)
    if settings.get('reverb'):
        s = settings['reverb']; n = max(2, round(s['seconds']*rate))
        r = np.random.default_rng(int(s['seed'])); ir = r.normal(0, 1, (n, 2))
        t = np.arange(n)/rate; ir *= np.exp(-6.9*t[:, None]/s['seconds'])
        ir[:round(s['predelay_seconds']*rate)] = 0
        # Finite, darkening, decorrelated stereo room: actual convolution tail.
        ir[1:] = .55*ir[1:]+.45*ir[:-1]
        ir /= np.maximum(1e-12, np.linalg.norm(ir, axis=0))[None, :]
        size = 1 << (len(x)+n-2).bit_length()
        wet = np.fft.irfft(np.fft.rfft(x, n=size, axis=0)*np.fft.rfft(ir, n=size, axis=0), n=size, axis=0)
        out[:min(length, len(x)+n-1)] += wet[:min(length, len(x)+n-1)]*s['wet']
    # Tails end smoothly within their declared footprint.
    if tail_seconds:
        fade = min(round(.04*rate), round(tail_seconds*rate))
        if fade: out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out


def master(x, rate, settings):
    y, calibration = gain_stage(x, rate, settings['level'])
    c = settings['compressor']; limiter = settings['limiter']
    chain = f"highpass=f=25,acompressor=threshold={10**(c['threshold_dbfs']/20)}:ratio={c['ratio']}:attack={c['attack_ms']}:release={c['release_ms']}:knee={c['knee']}:makeup=1:link=maximum:detection=rms:mix={c['mix']}"
    if not c['mix']:
        chain = 'anull'
    if limiter['enabled']:
        chain += f",aresample={rate*4},alimiter=limit={10**(limiter['ceiling_dbfs']/20)}:attack={limiter['attack_ms']}:release={limiter['release_ms']}:level=false:latency=true,aresample={rate}"
    out = filter_audio(y, rate, chain)
    # Resampling can create tiny new peaks. A single final attenuation preserves
    # the dynamics; it is not hard clipping. Leave headroom for MP3 encoding.
    ceiling = 10**(limiter['ceiling_dbfs']/20)
    correction = min(1., ceiling/max(1e-12, float(np.max(np.abs(out))))) if limiter['enabled'] else 1.
    out *= correction
    hop = max(1, round(rate*.25)); dynamics = []
    for at in range(0,len(out),hop):
        part = out[at:at+hop]; rms = float(np.sqrt(np.mean(part**2))); peak = float(np.max(np.abs(part)))
        dynamics.append({'time':at/rate,'rms':rms,'peak':peak,'crest':peak/max(1e-12,rms)})
    return out, {'version': VERSION, 'level': calibration, 'filter': chain,
                 'input_peak_dbfs': 20*np.log10(max(1e-12, float(np.max(np.abs(x))))),
                 'output_peak_dbfs': 20*np.log10(max(1e-12, float(np.max(np.abs(out))))),
                 'final_attenuation_db': 20*np.log10(correction),
                 'limiter_oversampling': 4, 'hard_clipped_samples': 0, 'dynamics':dynamics}


def master_settings(glue=.45):
    return {'version': VERSION, 'level': {'target_dbfs': -20., 'min_gain_db': -12., 'max_gain_db': 12.},
            'compressor': {'threshold_dbfs': -19., 'ratio': 1.7, 'attack_ms': 28.,
                           'release_ms': 180., 'knee': 2.8, 'mix': glue},
            'limiter': {'enabled': True, 'ceiling_dbfs': -1.8, 'attack_ms': 5., 'release_ms': 90.}}
