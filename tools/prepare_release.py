"""Verify assets and collect installed dependency licence texts for distribution."""
import importlib.metadata
from pathlib import Path
import platform
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ocr.ppocr import PPOCR
from PIL import Image

if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64') or sys.maxsize <= 2**32:
    raise SystemExit('Build with 64-bit Python on Windows x64.')
PPOCR().read(Image.new('RGB', (64, 64), 'white'))
root = Path(__file__).resolve().parents[1]
for filename in ('data/japanese/jmdict-es.sqlite3', 'data/spanish/gloss-es.json', 'data/dict/meta.json'):
    if not (root / filename).is_file():
        raise SystemExit(f'Missing {filename}; run the dictionary setup scripts first.')
destination = root / 'build/third-party-licenses'
destination.mkdir(parents=True, exist_ok=True)
manifest = []
for dist in importlib.metadata.distributions():
    name = dist.metadata['Name']
    manifest.append(f'{name}=={dist.version}')
    for member in dist.files or ():
        if any(word in str(member).lower() for word in ('license', 'licence', 'copying', 'notice', 'copyright')):
            original = Path(dist.locate_file(member))
            if original.is_file():
                target = destination / name / str(member).replace('..', '_').replace(':', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original.read_bytes())
(destination / 'PACKAGES.txt').write_text('\n'.join(sorted(manifest)), encoding='utf-8')
print('Release assets ready.')
