from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parents[1]
stage = root / 'build' / 'desktop-resources'
datas = [(str(stage), '.')]
binaries = []
hiddenimports = []
# Dynamic imports and model/package data used by the existing engine.
for package in ('ultralytics', 'transnetv2_pytorch', 'faster_whisper',
                'mediapipe', 'google.genai', 'scenedetect', 'py3langid'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += [p.stem for p in root.glob('*.py') if not p.name.startswith('verify_')]
hiddenimports += collect_submodules('desktop')
hiddenimports += ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                  'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on']

a = Analysis([str(root / 'desktop_entry.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'jupyter', 'pytest', 'cloud'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OpenShorts',
          debug=False, strip=False, upx=False, console=False,
          icon=str(stage / 'openshorts.ico'),
          version=str(root / 'packaging/windows/version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OpenShorts')
