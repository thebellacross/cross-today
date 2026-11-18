import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def config():
    return json.loads((ROOT / "config.json").read_text())

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical(value))
    os.replace(tmp, path)

def ffmpeg():
    # Use the pinned package's platform binary, not a mutable runner system install.
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def run_audio(args):
    result = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", *map(str, args)], capture_output=True)
    if result.returncode:
        # FFmpeg stderr may contain an original private pathname; never forward it.
        raise ValueError("Audio decoding/encoding failed; check the file format and integrity.")
    return result.stdout

def public_name(value):
    return str(value).replace("\\", "/").split("/")[-1].replace("\x00", "")[:180]
