from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules
root=Path(SPECPATH).resolve().parents[1]
stage=root/'build'/'wpf-engine-resources'
datas=[(str(stage),'.')];binaries=[];hidden=[]
for package in ('ultralytics','transnetv2_pytorch','faster_whisper','mediapipe','google.genai','scenedetect','py3langid','yt_dlp_ejs'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
hidden += [p.stem for p in root.glob('*.py') if not p.name.startswith('verify_') and p.name not in ('desktop_entry.py',)]
hidden += [name for name in collect_submodules('desktop') if name not in ('desktop.windows_shell','desktop.windows_settings')]
a=Analysis([str(root/'native_engine_entry.py')],pathex=[str(root)],datas=datas,binaries=binaries,hiddenimports=hidden,
           excludes=['webview','PySide6','PyQt5','PyQt6','desktop.windows_shell','desktop.windows_settings','cloud','tkinter','pytest','IPython'])
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='OpenShorts.Engine',console=False,upx=False,
        icon=str(root/'assets/desktop.ico'))
coll=COLLECT(exe,a.binaries,a.datas,name='OpenShorts.Engine',upx=False)
