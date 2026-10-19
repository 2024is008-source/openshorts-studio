"""Audit independently exported source trees and create a matched source overlay.

Never extracts an input archive or includes credentials, media, models or binaries.
Apply the generated overlay to a COPY of the old engine tree; provision dependencies
separately. This is source recovery, not an installer or a redistribution license.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.py','.cs','.xaml','.csproj','.sln','.props','.targets','.json','.txt',
              '.md','.ps1','.vbs','.spec','.iss','.ico','.ttf','.otf','.png','.svg'}
OMIT = {'bin','obj','TestResults','__pycache__','.git','.venv','.nuget','node_modules',
        'vendor','output','uploads','logs','build','dist'}
REQUIRED = ('app.py','main.py','render_runtime.py','ffmpeg_utils.py','caption_timing.py','generation_options.py',
            'desktop/native_api.py','desktop/contract.py','desktop/backend.py',
            'desktop/processes.py','desktop/security.py','desktop/credentials.py',
            'desktop/projects.py','desktop/storage.py','desktop_entry.py','native_engine_entry.py',
            'desktop/generation_review.py','native/OpenShorts.Desktop/ClipperWorkspaceView.xaml',
            'native/OpenShorts.Desktop/ReviewDetails.xaml','native/OpenShorts.Desktop/GenerationStepper.xaml',
            'native/OpenShorts.Desktop/ClipperTheme.xaml','native/OpenShorts.EngineBridge/ReviewExportClient.cs',
            'native/OpenShorts.Core/GenerationReview.cs','desktop/home.py','desktop/editor_assets.py','desktop/cache.py','desktop/native_media.py',
            'native/OpenShorts.Desktop/HomePanel.xaml','native/OpenShorts.Desktop/EditorAssetsPanel.xaml',
            'native/OpenShorts.Desktop/EditorInspector.xaml','native/OpenShorts.Desktop/EditorTimelinePanel.xaml',
            'native/OpenShorts.Desktop/EditorStudioWorkspace.cs','native/OpenShorts.Desktop/ExportWorkspace.cs',
            'native/OpenShorts.Desktop/ExportWindow.xaml','native/OpenShorts.Desktop/PreviewOverlayControl.xaml',
            'native/OpenShorts.Desktop/EditorStyles.xaml',
            'native/OpenShorts.Desktop/HeroArtwork.xaml','native/OpenShorts.Desktop/StudioIcon.cs',
            'native/OpenShorts.Desktop/HeroBackdrop.cs',
            'native/OpenShorts.Desktop/RouteMatchConverter.cs','native/OpenShorts.Desktop/Assets/Studio/creator-hero.png',
            'native/OpenShorts.Desktop/DesktopStatusPanel.xaml','native/OpenShorts.Desktop/BrandResources.xaml',
            'native/OpenShorts.Desktop/Assets/Brands/LICENSE.md',
            'timeline_api.py','timeline_project.py','timeline_render.py','caption_renderer.py',
            'packaging/wpf/build.py','packaging/wpf/OpenShorts.Engine.spec','packaging/wpf/installer.iss',
            'build_wpf.ps1','native/OpenShorts.sln','native/OpenShorts.EngineBridge/NativeContract.cs')


def source_files(root=ROOT):
    paths=list(root.glob('*.py'))+list(root.glob('requirements*.txt'))
    paths += [root/name for name in ('LICENSE','global.json','build_wpf.ps1','start_wpf.vbs')]
    for folder in ('desktop','native','packaging','assets','fonts','tests','docs','tools'):
        paths += list((root/folder).rglob('*'))
    result={}
    for path in paths:
        relative=path.relative_to(root)
        if set(relative.parts)&OMIT or path.is_symlink() or not path.is_file():continue
        if path.name in ('FFMPEG-SOURCE-OFFER.txt','THIRD-PARTY-NOTICES.txt'):continue
        if path.suffix.lower() not in EXTENSIONS and path.name!='LICENSE':continue
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Source path escapes root')
        result[relative.as_posix()]=path
    missing=set(REQUIRED)-set(result)
    if missing:raise ValueError('Missing integration sources: '+', '.join(sorted(missing)))
    return dict(sorted(result.items()))


def sha(data):return hashlib.sha256(data).hexdigest()


def compare(archive, files):
    with zipfile.ZipFile(archive) as z:
        entries={i.filename.replace('\\','/'):i for i in z.infolist() if not i.is_dir()}
        # Support either flat exports or a common enclosing repository folder.
        if 'app.py' not in entries and 'native/OpenShorts.sln' not in entries:
            prefixes={name.split('/')[0] for name in entries if '/' in name}
            if len(prefixes)==1:entries={name.split('/',1)[1]:i for name,i in entries.items() if '/' in name}
        scope={name:path for name,path in files.items() if (name.startswith('native/')) == (Path(archive).name=='native.zip')}
        same=[];changed=[];missing=[]
        for name,path in scope.items():
            if name not in entries:missing.append(name)
            elif sha(path.read_bytes())==sha(z.read(entries[name])):same.append(name)
            else:changed.append(name)
        return dict(archive=Path(archive).name,sha256=sha(Path(archive).read_bytes()),
                    same=same,changed=changed,missing=missing,
                    contains_environment_file=any(Path(n).name=='.env' for n in entries),
                    contains_user_outputs=any(n.startswith(('output/','uploads/','logs/')) for n in entries))


def export(destination, files):
    if Path(destination).exists():raise ValueError('Choose a new overlay path; existing exports are preserved.')
    entries={name:path.read_bytes() for name,path in files.items()}
    manifest=dict(format=1,protocol_version=1,editor_project_version=1,
                  provenance='working-tree SHA-256 inventory; repository has no committed revision',
                  kind='matched-source-overlay-not-installer',
                  files={name:sha(data) for name,data in entries.items()})
    entries['native-pair-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    Path(destination).parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():
            info=zipfile.ZipInfo(name,(2026,10,17,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    verify(destination)
    return manifest


def verify(archive, tree=None):
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('native-pair-manifest.json'))
        names=z.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(manifest['files'])|{'native-pair-manifest.json'}:
            raise ValueError('Archive inventory mismatch')
        for name,digest in manifest['files'].items():
            if name.startswith('/') or '\\' in name or ':' in name or '..' in name.split('/') or set(name.split('/'))&OMIT:
                raise ValueError('Unsafe archive path')
            if sha(z.read(name))!=digest:raise ValueError('Archive hash mismatch: '+name)
            if tree is not None:
                target=(Path(tree)/name).resolve()
                if not target.is_relative_to(Path(tree).resolve()) or not target.is_file() or sha(target.read_bytes())!=digest:
                    raise ValueError('Extracted source mismatch: '+name)
        if set(REQUIRED)-set(manifest['files']):raise ValueError('Archive lacks integration sources')
        return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path);parser.add_argument('--export',type=Path)
    parser.add_argument('--verify',type=Path)
    parser.add_argument('--check-tree',type=Path,help='With --verify, check a transferred/extracted tree against every source hash')
    args=parser.parse_args()
    if args.verify:
        print(json.dumps(dict(verified=True,files=len(verify(args.verify,args.check_tree)['files']))));return
    files=source_files()
    if args.audit:
        result=dict(required=list(REQUIRED),archives=[compare(ROOT/name,files) for name in
                    ('OpenShorts-Gemini-NoDocker.zip','native.zip') if (ROOT/name).is_file()])
        args.audit.parent.mkdir(parents=True,exist_ok=True)
        args.audit.write_text(json.dumps(result,indent=2),'utf-8')
    if args.export:print(json.dumps(dict(export=str(args.export),files=len(export(args.export,files)['files']))))


if __name__=='__main__':main()
