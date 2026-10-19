"""Python, binary and retained renderer attribution inventory; no web application build."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/"build/wpf-engine-resources"

def copy(source, relative):
    destination = STAGE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '.cache', '.remotion'))
    else:
        shutil.copy2(source, destination)


def inventory(include_web=True):
    notices = STAGE / 'licenses'
    notices.mkdir(exist_ok=True)
    distributions = []
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        distributions.append({'name': name, 'version': dist.version,
                              'license': dist.metadata.get('License-Expression') or dist.metadata.get('License')})
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ('license', 'notice', 'copying')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = notices / 'python' / name / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (notices / 'python-inventory.json').write_text(json.dumps(distributions, indent=2), 'utf-8')
    binary_hashes = {}
    for source in STAGE.rglob('*'):
        if source.is_file() and source.suffix.lower() in ('.exe', '.dll', '.pt'):
            with source.open('rb') as stream:
                binary_hashes[str(source.relative_to(STAGE))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (notices / 'runtime-sha256.json').write_text(json.dumps(binary_hashes, indent=2), 'utf-8')
    for name in (('remotion', 'render-service') if include_web else ()):
        lock = ROOT / name / 'package-lock.json'
        if lock.exists():
            copy(lock, f'licenses/{name}-package-lock.json')
        for base, dirs, files in os.walk(ROOT / name / 'node_modules'):
            dirs[:] = [d for d in dirs if d not in ('.cache', '.remotion', '.bin')]
            for filename in files:
                if filename.lower().startswith(('license', 'notice', 'copying')):
                    source = Path(base) / filename
                    copy(source, Path('licenses') / name / source.relative_to(ROOT / name / 'node_modules'))

