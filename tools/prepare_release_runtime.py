"""Inventory and prepare a clean release venv; never clone the developer venv.

Wheel installation is offline, requires actual wheel hashes, and is opt-in.
Absent wheel artifacts are a reported blocker rather than silently borrowing
developer site-packages. No binary freezing or licensing bypass is performed.
"""
import argparse
import importlib
import importlib.metadata as md
import json
from pathlib import Path
import subprocess
import sys
import venv
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name,parse_wheel_filename

ROOT=Path(__file__).resolve().parents[1]
MODULES={'faster-whisper':'faster_whisper','ctranslate2':'ctranslate2','google-genai':'google.genai','torch':'torch',
 'opencv-contrib-python':'cv2','mediapipe':'mediapipe','scenedetect':'scenedetect','transnetv2-pytorch':'transnetv2_pytorch',
 'fastapi':'fastapi','uvicorn':'uvicorn','httpx':'httpx','yt-dlp':'yt_dlp','yt-dlp-ejs':'yt_dlp_ejs',
 'pillow':'PIL','py3langid':'py3langid','boto3':'boto3','beautifulsoup4':'bs4','python-multipart':'python_multipart',
 'python-dotenv':'dotenv','deno':'deno','pyinstaller':'PyInstaller',
 'ultralytics':'ultralytics','numpy':'numpy','psutil':'psutil'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--wheelhouse',type=Path);parser.add_argument('--install',action='store_true');args=parser.parse_args()
    folder=args.directory.resolve();folder.mkdir(parents=True,exist_ok=True);env=folder/'environment'
    if not (env/'pyvenv.cfg').exists():venv.EnvBuilder(with_pip=True,system_site_packages=False).create(env)
    known={canonicalize_name(d.metadata['Name']):d for d in md.distributions()};selected={};queue=list(MODULES)
    while queue:
        name=canonicalize_name(queue.pop())
        if name in selected:continue
        if name not in known:raise RuntimeError('Required build distribution unavailable: '+name)
        dist=known[name];selected[name]=dist
        for value in dist.requires or []:
            req=Requirement(value)
            if req.marker and not any(req.marker.evaluate({'extra':extra}) for extra in ('','default') if extra):
                if not req.marker.evaluate({'extra':''}):continue
            queue.append(req.name)
    lock='\n'.join(f'{name}=={dist.version}' for name,dist in sorted(selected.items()))+'\n'
    (folder/'runtime-versions.lock').write_text(lock,'utf-8')
    results=[]
    for distribution,module in MODULES.items():
        try:importlib.import_module(module);results.append(dict(distribution=distribution,version=md.version(distribution),module=module,status='PASS in developer reference environment'))
        except Exception as error:results.append(dict(distribution=distribution,module=module,status='FAIL',error=type(error).__name__))
    sys.path.insert(0,str(ROOT))
    for module in ['editing_director','story_director','adaptive_analysis.pipeline','learning.api','timeline_render','desktop.native_api','desktop.download_runtime']:
        try:importlib.import_module(module);results.append(dict(module=module,status='PASS in source reference environment'))
        except Exception as error:results.append(dict(module=module,status='FAIL',error=type(error).__name__))
    wheels={}
    if args.wheelhouse:
        for p in args.wheelhouse.glob('*.whl'):
            name,version,_,_=parse_wheel_filename(p.name);wheels[(canonicalize_name(name),str(version))]=p
    missing=[f'{n}=={d.version}' for n,d in selected.items() if (n,d.version) not in wheels]
    report=dict(interpreter=sys.version,isolated_environment=str(env),system_site_packages=False,
        selected_distributions=len(selected),reference_imports=results,missing_wheels=missing,
        installed_into_clean_environment=False,frozen_engine='BLOCKED: authentic redistribution materials incomplete',
        note='Version pins are not a complete wheel hash lock until authentic target-compatible wheels are supplied. No clean runtime import success is claimed from developer imports.')
    if args.install:
        if missing:raise RuntimeError('Refusing installation: incomplete pinned wheelhouse')
        import hashlib
        text='\n'.join(f'{n}=={d.version} --hash=sha256:{hashlib.sha256(wheels[(n,d.version)].read_bytes()).hexdigest()}' for n,d in sorted(selected.items()))+'\n'
        (folder/'runtime-wheels.lock').write_text(text,'utf-8')
        executable=env/'Scripts/python.exe' if sys.platform=='win32' else env/'bin/python'
        subprocess.run([str(executable),'-m','pip','install','--no-index','--find-links',str(args.wheelhouse),'--require-hashes','-r',str(folder/'runtime-wheels.lock')],check=True)
        subprocess.run([str(executable),'-m','pip','check'],check=True);report['installed_into_clean_environment']=True
    (folder/'inventory.json').write_text(json.dumps(report,indent=2),'utf-8');print(json.dumps(dict(selected=len(selected),missing_wheels=len(missing),isolated=True),indent=2))

if __name__=='__main__':main()
