"""Content addressed PCM16 adapter; originals are opened read-only, never rewritten."""
import argparse
import json
import sqlite3
import subprocess
import wave
from pathlib import Path
import numpy as np
from .common import ROOT, config, digest, file_hash, save_json, run_audio, public_name, ffmpeg

EXTENSIONS = {".wav", ".aiff", ".aif", ".mp3", ".m4a", ".flac"}
ADAPTER_VERSION = "pcm16-mono-2"
NATIVE_ADAPTER_VERSION = "pcm16-native-3"

def adapter_version(settings):
    return NATIVE_ADAPTER_VERSION if settings.get("channels")=="preserve" else ADAPTER_VERSION

def decode(path, rate):
    raw = run_audio(["-i", path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", rate, "-f", "s16le", "-"])
    return np.frombuffer(raw, dtype="<i2")

def segments(path,rate,segment,overlap,minimum,channels=1):
    """Decode a long source with bounded memory and exact PCM frame boundaries."""
    command=[ffmpeg(),'-nostdin','-hide_banner','-loglevel','error','-i',str(path),'-map','0:a:0','-vn','-ac',str(channels),'-ar',str(rate),'-f','s16le','-']
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    buffer=b'';start=0;eof=False;frame_bytes=2*channels
    try:
        while True:
            # One frame of lookahead prevents a duplicate trailing overlap segment.
            while len(buffer)<segment*frame_bytes+frame_bytes and not eof:
                data=process.stdout.read(segment*frame_bytes+frame_bytes-len(buffer))
                if not data:eof=True
                buffer+=data
            frames=min(segment,len(buffer)//frame_bytes)
            if frames<minimum:break
            yield start,start+frames,np.frombuffer(buffer[:frames*frame_bytes],dtype='<i2').reshape(frames,channels) if channels>1 else np.frombuffer(buffer[:frames*frame_bytes],dtype='<i2')
            if eof:break
            step=segment-overlap;buffer=buffer[step*frame_bytes:];start+=step
        if process.wait()!=0:raise ValueError('Audio decoding failed; check the source format and integrity.')
    finally:
        process.stdout.close()
        if process.poll() is None:process.terminate();process.wait()

def write_wav(path, data, rate):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1 if data.ndim == 1 else data.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(data, dtype="<i2").tobytes())

def read_clip(path, native=False):
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() not in ((1,2) if native else (1,)) or w.getsampwidth() != 2:
            raise ValueError("The recording channel requires mono PCM16 WAV.")
        x=np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.
        if w.getnchannels()==2:x=x.reshape(-1,2)
        return x,w.getframerate()

def import_one(path, cache, settings, name=None, tags=None, expected_hash=None):
    path, cache = Path(path), Path(cache)
    sha = file_hash(path)
    if expected_hash and sha != expected_hash:
        raise ValueError("Source checksum mismatch; import rejected.")
    profile = dict(settings, adapter=adapter_version(settings))
    if profile["gather"] != 0 or profile["half_life"] != 0 or not profile["keep_static"]:
        raise ValueError("Local materials require gather=0, half_life=0 and keep_static=true.")
    key = digest({"source": sha, "profile": profile})
    directory = cache / key
    manifest_path = directory / "manifest.json"
    label = public_name(name or path.name)
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        if all((cache / c["cache_file"]).exists() for c in m["clips"]):
            for c in m["clips"]:
                c["name"], c["tags"] = label, tags or []
                actual=file_hash(cache/c['cache_file'])
                if c.get('cache_sha256') and c['cache_sha256']!=actual:break
                c['cache_sha256']=actual
            else:
                save_json(manifest_path,m)
                return m
    rate = profile["sample_rate"]
    segment = int(profile["segment_seconds"] * rate)
    overlap = int(profile["overlap_seconds"] * rate)
    minimum = max(1, int(profile["minimum_seconds"] * rate))
    if segment < minimum or overlap < 0 or overlap >= segment:
        raise ValueError("Invalid segmentation settings.")
    clips = [];audible=False
    channels=2 if settings.get("channels")=="preserve" else 1
    for start,end,x in segments(path,rate,segment,overlap,minimum,channels):
        audible=audible or bool(np.any(x))
        clip_id = digest({"source": sha, "start_frame": start, "end_frame": end, "profile": profile})
        wav = directory / (clip_id + ".wav")
        write_wav(wav, x, rate)
        y = x.astype(float) / 32768
        if y.ndim==2:y=y.mean(axis=1)
        f = np.abs(np.fft.rfft(y[:min(len(y), 32768)]))
        feature = [float(np.sqrt(np.mean(y*y))), float(np.mean(np.abs(np.diff(y)))), float(np.dot(np.arange(len(f)), f)/(f.sum()+1e-9)/len(f))]
        c = {"id": clip_id, "source_hash": sha, "name": label, "tags": tags or [], "start_frame": start, "end_frame": end,
             "start": start/rate, "end": end/rate, "seconds": (end-start)/rate, "sample_rate": rate,
             "format": ("stereo" if channels==2 else "mono")+" PCM16 WAV", "channels": channels, "adapter": adapter_version(settings), "cache_file": str(wav.relative_to(cache)), "cache_sha256":file_hash(wav), "features": feature}
        if channels==2:
            from .features import frames
            c["analysis"]=frames(x.astype(float)/32768,rate)
            c["channel_policy"]="preserve stereo; duplicate mono; FFmpeg downmix for more than two channels"
        save_json(wav.with_suffix(".json"), {k:v for k,v in c.items() if k != "cache_file"})
        clips.append(c)
    if not clips or not audible:raise ValueError('Source is empty or digitally silent; no substitute audio was used.')
    m = {"source_hash": sha, "profile": profile, "clips": clips}
    save_json(manifest_path, m)
    return m

def import_folder(folder, cache=None, settings=None):
    folder = Path(folder).resolve()
    cache = Path(cache or ROOT / ".cache" / "audio")
    settings = settings or config()["import"]
    private = ROOT / ".state"
    private.mkdir(exist_ok=True)
    db = sqlite3.connect(private / "library.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, hash TEXT, profile TEXT)")
    clips, files, errors = [], [], []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in EXTENSIONS:
            continue
        try:
            m = import_one(p, cache, settings)
            clips.extend(m["clips"])
            stat = p.stat()
            db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)", (str(p), stat.st_size, stat.st_mtime_ns, m["source_hash"], digest(settings)))
            files.append({"hash":m["source_hash"], "name":p.name, "path":str(p), "bytes":stat.st_size, "extension":p.suffix.lower()})
        except (ValueError, OSError) as e:
            errors.append({"name":p.name,"error":str(e) if isinstance(e,ValueError) else "Unable to read source"})
    db.commit(); db.close()
    # One hash/start/end identity across local and web imports; aliases remain private.
    clips = sorted({c["id"]:c for c in clips}.values(), key=lambda c:(c["source_hash"],c["start_frame"]))
    if not clips:
        raise ValueError("No valid selected sound materials. Generation stopped.")
    snapshot = {"schema":1,"import":settings,"clips":clips}
    snapshot["id"] = digest(snapshot)
    save_json(private / "snapshot.json", snapshot)
    save_json(private / "sources.json", files)
    save_json(private / "import-errors.json", errors)
    return snapshot, errors

def main():
    p=argparse.ArgumentParser();p.add_argument("folder");a=p.parse_args()
    s,e=import_folder(a.folder)
    print(json.dumps({"snapshot":s["id"],"clips":len(s["clips"]),"failed":e},ensure_ascii=False))

if __name__ == "__main__": main()
