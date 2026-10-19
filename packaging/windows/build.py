"""Windows build: stage explicit resources, freeze Python, then compile installer.

No .env, cookies, user output, caches or credentials are ever copied.
Use a clean build venv for release; package versions and hashes are inventoried.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / 'build' / 'desktop-resources'


def run(args, cwd=ROOT):
    build_env = os.environ.copy()
    # The distributed dashboard must always use the protected local origin.
    build_env.update(VITE_API_URL='', VITE_OPENPANEL_API_URL='', VITE_OPENPANEL_CLIENT_ID='')
    subprocess.run(list(map(str, args)), cwd=cwd, check=True, env=build_env)


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
    for name in (('dashboard', 'remotion', 'render-service') if include_web else ()):
        lock = ROOT / name / 'package-lock.json'
        if lock.exists():
            copy(lock, f'licenses/{name}-package-lock.json')
        for base, dirs, files in os.walk(ROOT / name / 'node_modules'):
            dirs[:] = [d for d in dirs if d not in ('.cache', '.remotion', '.bin')]
            for filename in files:
                if filename.lower().startswith(('license', 'notice', 'copying')):
                    source = Path(base) / filename
                    copy(source, Path('licenses') / name / source.relative_to(ROOT / name / 'node_modules'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', default=shutil.which('iscc') or '')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build on Windows x64 with Python 3.11')
    if sys.version_info[:2] != (3, 11):
        parser.error('Use Python 3.11 for the existing multimedia dependency set')
    # Check release prerequisites before consuming gigabytes of staging space.
    node_license_override = ROOT / 'packaging/windows/vendor/Node-LICENSE'
    source_offer = ROOT / 'packaging/windows/FFMPEG-SOURCE-OFFER.txt'
    if not source_offer.exists():
        parser.error('Missing packaging/windows/FFMPEG-SOURCE-OFFER.txt; see docs/DESKTOP_RELEASE.md')
    if not args.prepare_only and (not args.iscc or not Path(args.iscc).is_file()):
        parser.error('Inno Setup 6 ISCC.exe is required; pass --iscc or use build_desktop.ps1 -InnoCompiler')
    webview_runtime = ROOT / 'packaging/windows/vendor/webview2'
    if not (webview_runtime / 'msedgewebview2.exe').is_file():
        parser.error('Provide the official x64 WebView2 Fixed Version runtime under packaging/windows/vendor/webview2')
    if STAGE.exists() and any(p.name != 'remotion-bundle' for p in STAGE.iterdir()):
        parser.error('Staging directory already exists. Use a fresh build directory to prevent stale release resources.')
    STAGE.mkdir(parents=True, exist_ok=True)
    npm = shutil.which('npm.cmd')
    node = shutil.which('node')
    if not npm or not node:
        parser.error('Node/npm are required on the BUILD machine only')
    # All dependency versions resolve through committed lockfiles.
    for project in ('dashboard', 'remotion', 'render-service'):
        run([npm, 'ci', '--ignore-scripts', '--no-audit'], ROOT / project)
    for project in ('dashboard', 'render-service'):
        run([npm, 'run', 'build'], ROOT / project)
    run([node, ROOT / 'packaging/windows/prepare-renderer.mjs'], ROOT / 'render-service')
    for name in ('assets', 'fonts', 'dashboard/dist'):
        copy(ROOT / name, name)
    copy(webview_runtime, 'webview2')
    copy(ROOT / 'dashboard/public/logo-openshorts.png', 'dashboard/public/logo-openshorts.png')
    # runpy worker scripts require source. Explicit root files only, never .env.
    for source in ROOT.glob('*.py'):
        copy(source, source.name)
    copy(ROOT / 'yolov8n.pt', 'yolov8n.pt')
    copy(ROOT / 'LICENSE', 'licenses/OpenShorts-LICENSE')
    copy(Path(node), 'bin/node.exe')
    # Node's embedded distribution license accompanies every release.
    node_license = Path(node).parent / 'LICENSE'
    if not node_license.exists():
        node_license = node_license_override
    if not node_license.exists():
        parser.error('Node distribution LICENSE is missing; obtain the official Node license before packaging')
    copy(node_license, 'licenses/Node-LICENSE')
    ffmpeg = Path(shutil.which('ffmpeg') or '')
    ffprobe = Path(shutil.which('ffprobe') or '')
    if not ffmpeg.is_file() or not ffprobe.is_file():
        parser.error('FFmpeg and FFprobe must be on the build PATH')
    for binary in (ffmpeg, ffprobe):
        copy(binary, 'bin/' + binary.name)
    vendor_root = ffmpeg.parent.parent
    if not (vendor_root / 'LICENSE').is_file():
        parser.error('FFmpeg distribution LICENSE must be beside its bin directory')
    copy(vendor_root / 'LICENSE', 'licenses/FFmpeg-LICENSE')
    for name in ('README.txt', 'doc'):
        if (vendor_root / name).exists():
            copy(vendor_root / name, 'licenses/ffmpeg/' + name)
    config = subprocess.check_output([str(ffmpeg), '-version'], text=True)
    (STAGE / 'licenses/ffmpeg-build.txt').write_text(config, 'utf-8')
    # Desktop distribution requires a source offer/provenance record, not just
    # the GPL text. The builder supplies this for its selected binary build.
    offer = ROOT / 'packaging/windows/FFMPEG-SOURCE-OFFER.txt'
    if not offer.exists():
        parser.error('Provide packaging/windows/FFMPEG-SOURCE-OFFER.txt for your selected FFmpeg binary; see DESKTOP_RELEASE.md')
    copy(offer, 'licenses/FFMPEG-SOURCE-OFFER.txt')
    copy(ROOT / 'render-service/dist', 'render-service/dist')
    copy(ROOT / 'render-service/node_modules', 'render-service/node_modules')
    copy(ROOT / 'render-service/package.json', 'render-service/package.json')
    # Remotion capability checks and validator locate resources relative to root.
    copy(ROOT / 'remotion/package.json', 'remotion/package.json')
    chrome_roots = list((ROOT / 'render-service/node_modules/.remotion').glob('chrome-headless-shell/*/chrome-headless-shell-*'))
    if not chrome_roots:
        parser.error('Remotion Chromium is missing; run prepare-renderer.mjs first')
    copy(chrome_roots[0], 'browser')
    from PIL import Image
    Image.open(ROOT / 'dashboard/public/logo-openshorts.png').convert('RGBA').save(
        STAGE / 'openshorts.ico', sizes=[(16,16), (32,32), (48,48), (256,256)])
    inventory()
    (STAGE / 'licenses/build-lock.txt').write_text(subprocess.check_output(
        [sys.executable, '-m', 'pip', 'freeze'], text=True), 'utf-8')
    if args.prepare_only:
        print('Resources prepared; no executable or installer generated.')
        return
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', 'packaging/windows/OpenShorts.spec'])
    if not args.iscc or not Path(args.iscc).is_file():
        parser.error('Desktop executable built. Inno Setup 6 ISCC.exe is required to generate OpenShorts-Setup.exe')
    run([args.iscc, ROOT / 'packaging/windows/installer.iss'])
    artifact = ROOT / 'dist/installer/OpenShorts-Setup.exe'
    if not artifact.exists():
        raise RuntimeError('Installer compiler did not produce OpenShorts-Setup.exe')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.with_suffix('.exe.sha256').write_text(digest + '  ' + artifact.name + '\n', 'ascii')
    print(f'Generated {artifact}')


if __name__ == '__main__':
    main()
