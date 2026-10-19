"""Release-only build. The previous FFmpeg distribution blocker is mandatory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]


def run(args):
    subprocess.run(list(map(str,args)),cwd=ROOT,check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--python',default=sys.executable)
    parser.add_argument('--installer',action='store_true')
    parser.add_argument('--iscc',default='')
    args=parser.parse_args()
    source_record=ROOT/'packaging/windows/FFMPEG-SOURCE-OFFER.txt'
    if not source_record.is_file():
        parser.error('FFmpeg distribution blocked: complete packaging/windows/FFMPEG-SOURCE-OFFER.txt before packaging binaries. See docs/DESKTOP_RELEASE.md.')
    vendor_notices=ROOT/'packaging/wpf/THIRD-PARTY-NOTICES.txt'
    if not vendor_notices.is_file():
        parser.error('Complete packaging/wpf/THIRD-PARTY-NOTICES.txt for the selected LibVLC/.NET/model distribution before publishing binaries.')
    ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:parser.error('FFmpeg/FFprobe are required on the build machine')
    ffmpeg_license=Path(ffmpeg).parent.parent/'LICENSE'
    if not ffmpeg_license.is_file():parser.error('The selected FFmpeg distribution license is missing')
    deno=Path(args.python).resolve().parent/'deno.exe'
    if not deno.is_file():parser.error('The selected build environment must supply Deno for supported desktop URL downloads')
    deno_license=ROOT/'packaging/wpf/vendor/Deno-NOTICES.txt'
    if not deno_license.is_file():parser.error('Supply authentic notices for the selected Deno executable before distribution')
    if args.installer and not Path(args.iscc).is_file():parser.error('Inno Setup 6 ISCC.exe is required')
    stage=ROOT/'build/wpf-engine-resources'
    if stage.exists():parser.error('Inspect and remove the previous build/wpf-engine-resources before a fresh release')
    stage.mkdir(parents=True)
    for name in ('assets','fonts'):
        shutil.copytree(ROOT/name,stage/name)
    for script in ('main.py','quality_probe.py','export_quality.py'):
        shutil.copy2(ROOT/script,stage/script)
    shutil.copy2(ROOT/'yolov8n.pt',stage/'yolov8n.pt')
    (stage/'bin').mkdir();(stage/'licenses').mkdir()
    for binary in (ffmpeg,ffprobe):shutil.copy2(binary,stage/'bin'/Path(binary).name)
    shutil.copy2(deno,stage/'bin/deno.exe')
    shutil.copy2(deno_license,stage/'licenses/Deno-NOTICES.txt')
    shutil.copy2(ffmpeg_license,stage/'licenses/FFmpeg-LICENSE')
    shutil.copy2(source_record,stage/'licenses/FFMPEG-SOURCE-OFFER.txt')
    shutil.copy2(ROOT/'LICENSE',stage/'licenses/OpenShorts-LICENSE')
    shutil.copy2(vendor_notices,stage/'licenses/WPF-THIRD-PARTY-NOTICES.txt')
    # Inventory the Python engine and supported optional Remotion fallback.
    sys.path.insert(0,str(ROOT/'packaging'))
    import desktop_inventory as inventory
    inventory.STAGE=stage;inventory.inventory(include_web=True)
    run([args.python,'-m','PyInstaller','--noconfirm','packaging/wpf/OpenShorts.Engine.spec'])
    run(['dotnet','restore','native/OpenShorts.sln','--locked-mode'])
    target=ROOT/'dist/wpf'
    run(['dotnet','publish','native/OpenShorts.Desktop/OpenShorts.Desktop.csproj','-c','Release','-r','win-x64','--self-contained','true','-p:PublishSingleFile=false','-o',target])
    shutil.copytree(ROOT/'dist/OpenShorts.Engine',target/'engine',dirs_exist_ok=True)
    licenses=target/'licenses';licenses.mkdir(exist_ok=True)
    for lock in (ROOT/'native').rglob('packages.lock.json'):
        shutil.copy2(lock,licenses/(lock.parent.name+'-packages.lock.json'))
    package_inventory=subprocess.check_output(['dotnet','list','native/OpenShorts.Desktop/OpenShorts.Desktop.csproj','package','--include-transitive','--format','json'],cwd=ROOT,text=True)
    (licenses/'nuget-inventory.json').write_text(package_inventory,'utf-8')
    if args.installer:
        run([args.iscc,ROOT/'packaging/wpf/installer.iss'])
        artifact=ROOT/'dist/wpf-installer/OpenShorts-Setup.exe'
        if not artifact.exists():raise RuntimeError('Installer compiler did not produce its artifact')
        with artifact.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        artifact.with_suffix('.exe.sha256').write_text(digest+'  '+artifact.name+'\n','ascii')
        print(artifact)
    else:print('Published self-contained WPF application. Installer not requested.')


if __name__=='__main__':main()
