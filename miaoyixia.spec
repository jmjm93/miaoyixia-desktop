# Windows x64, folder bundle: models and dictionaries are available offline.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = []
for package in ('rapidocr', 'unidic_lite', 'certifi'):
    datas += collect_data_files(package, excludes=['models/*'])
import rapidocr
models = Path(rapidocr.__file__).parent / 'models'
for name in ('PP-OCRv6_det_small.onnx', 'PP-OCRv6_rec_small.onnx', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'):
    assert (models / name).is_file(), f'Missing OCR model: {name}; run tools/prepare_release.py'
    datas.append((str(models / name), 'rapidocr/models'))
for relative in ('dict', 'spanish'):
    datas.append((str(root / 'data' / relative), 'data/' + relative))
for name in ('jmdict-es.sqlite3', 'README.md', 'licence.html', 'meta.json'):
    datas.append((str(root / 'data/japanese' / name), 'data/japanese'))
datas += [(str(root / 'README.md'), '.'), (str(root / 'README.es.md'), '.'),
          (str(root / 'LICENSE'), '.'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
          (str(root / 'bench/japanese/horizontal-compound.png'), 'self-test'),
          (str(root / 'build-artifacts/third-party-licenses'), 'third-party-licenses')]
hidden = collect_submodules('rapidocr') + collect_submodules('fugashi') + ['unidic_lite', 'edge_tts']
datas += copy_metadata('rapidocr') + copy_metadata('edge-tts')
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root)], datas=datas,
    binaries=collect_dynamic_libs('onnxruntime') + collect_dynamic_libs('fugashi'),
    hiddenimports=hidden, excludes=['pytest', 'fastapi', 'uvicorn', 'tkinter', 'matplotlib'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Miaoyixia', console=False)
coll = COLLECT(exe, a.binaries, a.datas, name='Miaoyixia')
