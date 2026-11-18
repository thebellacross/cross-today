import json
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from music.common import ffmpeg,config
import numpy
import PIL
c=config();print('Python:',sys.version.split()[0]);print('NumPy:',numpy.__version__);print('Pillow:',PIL.__version__);print(subprocess.check_output([ffmpeg(),'-version'],text=True).splitlines()[0])
print('Local source folder:', 'present' if (ROOT/'C_SoundSource').is_dir() else 'not present')
print('Cloud endpoint:', c['worker_url'] or 'NOT CONNECTED')
print('Public site:', c['site_url'] or 'NOT DEPLOYED')
print('Pinned reference:',c['reference']['commit'])
