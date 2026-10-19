"""Read-only project audit plus verified backup; never moves/deletes originals.

No credential values are read. Runtime/user-data trees are inventoried by path
and size only. The conservative proposal deliberately leaves uncertain items.
"""
import ast
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
STAMP=datetime.now().strftime('%Y%m%d-%H%M%S')
REPORT=ROOT/'build'/('desktop-cleanup-audit-'+STAMP)
RECOVERY=ROOT/'.desktop-cleanup-recovery'/STAMP
SKIP_SOURCE={'.git','.venv','.nuget','node_modules','bin','obj','__pycache__','build','OpenShorts Library','output','uploads','logs','.local-gemini','.desktop-cleanup-recovery','not update'}
PROTECTED={'.git','.local-gemini','OpenShorts Library','output','uploads','logs','.remotion'}
EXCEPTIONS={'dashboard/src/remotion/lib/captions.ts','dashboard/src/remotion/compositions/Subtitles.tsx',
            'dashboard/src/remotion/lib/types.ts','dashboard/src/components/DeleteAccountCard.jsx'}
TARGET_FILES={'start_frontend_windows.bat','start_windows.bat'}


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=True),encoding='utf-8')


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def category(relative):
    parts=relative.split('/');top=parts[0];name=parts[-1]
    if top in PROTECTED or name=='.env' or name.startswith('.env.') and name!='.env.example' or name.endswith(('.dpapi','.sqlite','.sqlite3','.db')):return 'PROTECTED_USER_DATA'
    if relative in EXCEPTIONS:return 'KEEP_DESKTOP_TEST'
    if top=='dashboard' and any(word in name.lower() for word in ('license','notice','copying')):return 'KEEP_RUNTIME_DEPENDENCY'
    if top=='dashboard':return 'REMOVE_GENERATED' if 'node_modules' in parts or parts[1:2]==['dist'] else 'REMOVE_WEB_ONLY'
    if relative in TARGET_FILES:return 'REMOVE_WEB_ONLY'
    if top in ('remotion','render-service','cloud','alembic','ops','cli','not update') or name.endswith('.zip'):return 'REVIEW_REQUIRED'
    if top=='build' or top=='screenshots' or name.startswith('verify_'):return 'REVIEW_REQUIRED'
    if top in ('.venv','.nuget','fonts','assets') or name=='yolov8n.pt':return 'KEEP_RUNTIME_DEPENDENCY'
    if top=='native':return 'KEEP_DESKTOP'
    if top=='tests' or top=='benchmarks':return 'KEEP_DESKTOP_TEST'
    if top in ('desktop','learning','adaptive_analysis') or name.endswith('.py'):return 'KEEP_SHARED_ENGINE'
    return 'REVIEW_REQUIRED'


def inventory():
    aggregate=defaultdict(lambda:dict(files=0,bytes=0));selected=[];links=[];errors=[];total=0;count=0
    with (REPORT/'file-inventory.jsonl').open('w',encoding='utf-8') as out:
        for base,dirs,files in os.walk(ROOT,followlinks=False,onerror=lambda e:errors.append(type(e).__name__)):
            base=Path(base)
            dirs[:]=[d for d in dirs if d!='.desktop-cleanup-recovery' and not (base/d).is_symlink() and not (hasattr((base/d),'is_junction') and (base/d).is_junction())]
            for filename in files:
                path=base/filename;relative=path.relative_to(ROOT).as_posix()
                if path.is_symlink():links.append(relative);continue
                try:size=path.stat().st_size
                except OSError as exc:errors.append(type(exc).__name__);continue
                kind=category(relative);top=relative.split('/')[0]
                aggregate[top]['files']+=1;aggregate[top]['bytes']+=size;total+=size;count+=1
                out.write(json.dumps(dict(path=relative,size_bytes=size,classification=kind))+'\n')
                if kind in ('REMOVE_WEB_ONLY','REMOVE_GENERATED'):
                    selected.append(dict(path=relative,size_bytes=size,classification=kind))
    return selected,dict(bytes=total,files=count,top_level=dict(aggregate),links_skipped=links,errors=errors)


def sources():
    for base,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in SKIP_SOURCE and not (Path(base)/d).is_symlink()]
        for name in files:
            if Path(name).suffix in ('.py','.cs','.csproj','.xaml','.ps1','.spec','.vbs','.bat','.json','.ts','.tsx','.jsx') and not name.startswith('.env') and name!='package-lock.json':yield Path(base)/name


def graph():
    edges=[];routes=[];native_routes=[];parse_errors=[];files=list(sources());modules={}
    for path in files:
        if path.suffix=='.py':
            module=path.relative_to(ROOT).with_suffix('').as_posix().replace('/','.')
            modules[module.removesuffix('.__init__')]=path.relative_to(ROOT).as_posix()
    for path in files:
        relative=path.relative_to(ROOT).as_posix()
        try:text=path.read_text(encoding='utf-8-sig')
        except (OSError,UnicodeError):continue
        if path.suffix=='.py':
            try:tree=ast.parse(text)
            except SyntaxError:parse_errors.append(relative);continue
            decorators={id(decorator) for function in ast.walk(tree) if isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)) for decorator in function.decorator_list}
            for node in ast.walk(tree):
                names=[]
                if isinstance(node,ast.Import):names=[v.name for v in node.names]
                if isinstance(node,ast.ImportFrom):
                    prefix=(node.module or '')
                    if node.level:
                        base=relative[:-3].split('/')[:-node.level];prefix='.'.join(base+([prefix] if prefix else []))
                    names=[prefix]+[prefix+'.'+v.name for v in node.names]
                for name in names:
                    target=modules.get(name)
                    if not target and '.' in name:target=modules.get(name.split('.')[0])
                    edges.append(dict(source=relative,target=target or name,kind='python_import',local=target is not None,line=node.lineno))
                if isinstance(node,ast.Call):
                    func=ast.unparse(node.func)
                    if func.endswith(('import_module','__import__')) and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                        name=node.args[0].value;edges.append(dict(source=relative,target=modules.get(name,name),kind='dynamic_literal_import',local=name in modules,line=node.lineno))
                    if id(node) in decorators and isinstance(node.func,ast.Attribute) and node.func.attr in ('get','post','put','delete','patch') and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and node.args[0].value.startswith('/'):
                        routes.append(dict(source=relative,line=node.lineno,method=node.func.attr.upper(),path=node.args[0].value))
        if path.suffix=='.cs':
            for match in re.finditer(r'"(/(?:api|health|videos|thumbnails)[^"\r\n]*)"',text):
                native_routes.append(dict(source=relative,path=match[1],line=text.count('\n',0,match.start())+1))
        for marker in ('dashboard','render-service','remotion','node.exe','npm','webview','StaticFiles','runpy','subprocess','import_module','GetType','LoadFrom','Resource Include','Content Include','cloud'):
            lines=[i for i,line in enumerate(text.splitlines(),1) if marker in line]
            if lines:edges.append(dict(source=relative,target=marker,kind='runtime_or_resource_marker_REVIEW',lines=lines[:40]))
    adjacency=defaultdict(set)
    for edge in edges:
        if edge.get('local'):adjacency[edge['source']].add(edge['target'])
    def closure(roots):
        seen=set();queue=list(roots)
        while queue:
            item=queue.pop()
            if item in seen:continue
            seen.add(item);queue.extend(adjacency[item]-seen)
        return sorted(seen)
    result=dict(schema=1,python_roots=['native_engine_entry.py','desktop_entry.py','app.py','main.py'],
        conservative_import_closure=closure(['native_engine_entry.py','desktop_entry.py','app.py','main.py']),edges=edges,
        http_routes=routes,native_route_literals=native_routes,parse_errors=parse_errors,
        limitations=['Static imports overapproximate conditional paths. Interpolated routes and reflection require manual review; absence is not deletion proof.',
            'Marker records expose file/line locations only, not source text or credential values. All unknown paths remain protected from removal.'])
    save(REPORT/'dependency-graph.json',result)


def backup(selected):
    modifications=['desktop_entry.py','desktop/backend.py','desktop/native_api.py','desktop/__init__.py','desktop/windows_shell.py',
        'desktop/windows_settings.py','start_desktop.vbs','start_wpf.vbs','requirements.txt','requirements-local.txt',
        'requirements-desktop.txt','requirements-billing.txt','app.py','render_runtime.py','README.md','LOCAL_WINDOWS_SETUP.md',
        'packaging/wpf/build.py','packaging/wpf/OpenShorts.Engine.spec','packaging/windows/build.py',
        'packaging/windows/OpenShorts.spec','packaging/windows/installer.iss','packaging/windows/prepare-renderer.mjs',
        'packaging/windows/smoke_webview.py','build_desktop.ps1','build_wpf.ps1','tests/test_professional_captions.py']
    # Also back up the audit-only exceptions so restoration does not depend on
    # keeping an undocumented fragment of the old frontend.
    extra=set(modifications)|EXCEPTIONS
    mapping={r['path']:dict(r,action='proposed_quarantine_after_approval') for r in selected}
    for relative in extra:
        path=ROOT/relative
        if path.is_file():mapping.setdefault(relative,dict(path=relative,size_bytes=path.stat().st_size,classification=category(relative),action='backup_only_possible_future_edit'))
    required=sum(r['size_bytes'] for r in mapping.values())
    free=shutil.disk_usage(ROOT).free
    if free<required*2+2*1024**3:raise RuntimeError('Insufficient verified backup headroom; no cleanup allowed')
    RECOVERY.mkdir(parents=True,exist_ok=False);archive=RECOVERY/'pre-cleanup.zip';records=[]
    print('Backing up '+str(len(mapping))+' files; originals remain in place.',flush=True)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as output:
        for relative,row in sorted(mapping.items()):
            path=ROOT/relative
            before=path.stat();checksum=sha(path)
            output.write(path,relative)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('Candidate changed while backing up; audit must be repeated')
            record=dict(row,sha256=checksum,recovery_archive=str(archive),recovery_member=relative)
            if row['action']=='proposed_quarantine_after_approval':
                record.update(purpose='Standalone React/Vite frontend or web launch script',risk='low for native runtime; launcher/packaging migration and retained test exceptions required',
                    dependency_evidence='native EngineClient starts desktop_entry --native-backend; backend serves dashboard only when native=False; no WPF project includes dashboard resources')
            records.append(record)
    by_name={row['path']:row for row in records}
    with zipfile.ZipFile(archive) as saved:
        for info in saved.infolist():
            with saved.open(info) as stream:
                actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=by_name[info.filename]['sha256']:raise RuntimeError('Backup verification mismatch; cleanup forbidden')
    manifest=dict(schema=1,created_at=datetime.now(timezone.utc).isoformat(),project=str(ROOT),backup=str(archive),backup_sha256=sha(archive),
        backup_verified=True,free_before_bytes=free,uncompressed_backup_bytes=required,backup_bytes=archive.stat().st_size,
        proposed_files=len(selected),proposed_bytes=sum(r['size_bytes'] for r in selected),
        protected_exceptions=sorted(EXCEPTIONS),quarantine=str(RECOVERY/'quarantine'),approval='PENDING; no originals moved or deleted',files=records)
    save(RECOVERY/'manifest.json',manifest);save(REPORT/'cleanup-manifest.json',manifest)
    (RECOVERY/'RESTORE.md').write_text('Verified source snapshot: pre-cleanup.zip. No originals have been removed.\n\nTo restore after a separately approved cleanup, stop only owned application jobs, validate the ZIP SHA-256 against manifest.json, and restore only manifest members to their original relative paths after checking each destination stays inside the recorded project root. Back up current files before overwriting. Verify restored file hashes. Never extract unrelated archives or overwrite customer-data paths. The planned quarantine preserves the same paths and must not be purged without separate approval.\n',encoding='utf-8')
    return manifest


def main():
    REPORT.mkdir(parents=True,exist_ok=False)
    print('Audit directory: '+str(REPORT),flush=True)
    selected,summary=inventory();summary.update(measurement='Logical file sizes; links excluded; no claim about allocated/compressed disk space',recovery_excluded=True)
    save(REPORT/'project-size-before.json',summary);graph();manifest=backup(selected)
    print(json.dumps(dict(report=str(REPORT),recovery=str(RECOVERY),before_bytes=summary['bytes'],before_files=summary['files'],proposed_files=manifest['proposed_files'],proposed_bytes=manifest['proposed_bytes'],backup_bytes=manifest['backup_bytes'],backup_verified=True,originals_changed=False)),flush=True)


if __name__=='__main__':main()
