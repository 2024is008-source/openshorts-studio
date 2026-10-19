"""Execute only the user's explicitly approved 2026-10-19 Phase 1 manifest.

Never deletes files/directories. Exact members are renamed into quarantine;
changed/uncertain members are skipped. The approved patch is context checked.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/'build/desktop-cleanup-audit-20261019-185359'
MANIFEST=AUDIT/'cleanup-manifest.json'
EDITS={'desktop/backend.py','desktop_entry.py','start_desktop.vbs','packaging/windows/build.py','packaging/wpf/build.py'}
RECOVERY=ROOT/'.desktop-cleanup-recovery/20261019-185359'
QUARANTINE=RECOVERY/'quarantine'


def checksum(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.writing')
    temporary.write_text(json.dumps(data,indent=2),encoding='utf-8');os.replace(temporary,path)


def safe_path(base,relative):
    part=Path(relative)
    if part.is_absolute() or '..' in part.parts:raise ValueError('Unsafe relative member')
    raw=base/part
    for item in (raw,*raw.parents):
        if not item.is_relative_to(base):continue
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('Linked path refused')
    resolved=raw.resolve()
    if not resolved.is_relative_to(base.resolve()) or resolved==base.resolve():raise ValueError('Path outside approved root')
    return resolved


def patched_files(text):
    lines=text.splitlines(keepends=True);i=0;results={}
    while i<len(lines):
        if not lines[i].startswith('--- a/'):raise ValueError('Unexpected patch header')
        relative=lines[i][6:].strip();i+=1
        if i>=len(lines) or lines[i].strip()!='+++ b/'+relative:raise ValueError('Patch target mismatch')
        if relative not in EDITS or relative in results:raise ValueError('Unapproved patch target')
        i+=1;original=safe_path(ROOT,relative).read_text(encoding='utf-8').splitlines(keepends=True);output=[];position=0
        while i<len(lines) and not lines[i].startswith('--- a/'):
            match=re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\s*\n?',lines[i])
            if not match:raise ValueError('Invalid patch hunk')
            start=int(match[1])-1
            if start<position:raise ValueError('Overlapping patch hunks')
            output.extend(original[position:start]);position=start;i+=1;old_count=0;new_count=0
            while i<len(lines) and not lines[i].startswith(('@@ ','--- a/')):
                line=lines[i];i+=1
                if not line or line[0] not in ' +-':raise ValueError('Unsupported patch line')
                if line[0] in ' -':
                    if position>=len(original) or original[position]!=line[1:]:raise ValueError('Patch context changed: '+relative)
                    position+=1;old_count+=1
                if line[0] in ' +':output.append(line[1:]);new_count+=1
            if old_count!=int(match[2] or 1) or new_count!=int(match[4] or 1):raise ValueError('Patch hunk length mismatch')
        output.extend(original[position:]);results[relative]=''.join(output)
    if set(results)!=EDITS:raise ValueError('Approved patch does not contain exactly five files')
    return results


def tree_size():
    size=0;count=0;errors=[]
    for base,dirs,files in os.walk(ROOT,followlinks=False):
        dirs[:]=[d for d in dirs if d!='.desktop-cleanup-recovery' and not (Path(base)/d).is_symlink() and not (hasattr(Path(base)/d,'is_junction') and (Path(base)/d).is_junction())]
        for name in files:
            path=Path(base)/name
            if path.is_symlink():continue
            try:size+=path.stat().st_size;count+=1
            except OSError as exc:errors.append(type(exc).__name__)
    return dict(files=count,bytes=size,errors=errors,recovery_excluded=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute-approved-phase1',action='store_true');args=parser.parse_args()
    if not args.execute_approved_phase1:raise SystemExit('Use the explicitly authorized Phase 1 flag; no work performed')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S');report=ROOT/'build'/('desktop-cleanup-phase1-'+stamp);report.mkdir(parents=True,exist_ok=False)
    data=json.loads(MANIFEST.read_text(encoding='utf-8'));archive=Path(data['backup']).resolve()
    if Path(data['project']).resolve()!=ROOT or archive!=RECOVERY/'pre-cleanup.zip' or Path(data['quarantine']).resolve()!=QUARANTINE:raise ValueError('Approved manifest root mismatch')
    selected=[r for r in data['files'] if r['action']=='proposed_quarantine_after_approval']
    if len(selected)!=9493 or sum(r['size_bytes'] for r in selected)!=108816388 or len({r['path'] for r in selected})!=9493:raise ValueError('Approved scope mismatch')
    exceptions=set(data['protected_exceptions'])
    for row in selected:
        if row['path'] in exceptions or not (row['path'].startswith('dashboard/') or row['path'] in ('start_windows.bat','start_frontend_windows.bat')):raise ValueError('Unapproved or protected member')
    if checksum(archive)!=data['backup_sha256']:raise ValueError('Backup archive checksum mismatch')
    rows={r['path']:r for r in data['files']}
    with zipfile.ZipFile(archive) as backup:
        if set(backup.namelist())!=set(rows):raise ValueError('Backup inventory mismatch')
        for member in backup.infolist():
            with backup.open(member) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=rows[member.filename]['sha256']:raise ValueError('Backup member failed verification')
    patch=AUDIT/'proposed-edits.patch';prepared=patched_files(patch.read_text(encoding='utf-8'))
    # Frontend moves require all launcher/backend changes to be independently safe.
    for relative in EDITS:
        if checksum(safe_path(ROOT,relative))!=rows[relative]['sha256']:raise ValueError('Source changed since approval; abort before moving frontend: '+relative)
    retained={relative:checksum(safe_path(ROOT,relative)) for relative in exceptions}
    ready=[];skipped=[]
    for row in selected:
        try:
            source=safe_path(ROOT,row['path']);target=safe_path(QUARANTINE,row['path'])
            if not source.is_file() or target.exists() or checksum(source)!=row['sha256']:raise ValueError('Missing, changed or existing quarantine destination')
            ready.append(row)
        except (OSError,ValueError) as exc:skipped.append(dict(path=row['path'],reason=type(exc).__name__))
    before=tree_size()
    receipt=dict(schema=1,report=str(report),created_at=datetime.now(timezone.utc).isoformat(),approval='User approved only exact 9493 Phase 1 entries plus five-file patch',
        manifest_sha256=checksum(MANIFEST),patch_sha256=checksum(patch),backup_sha256=data['backup_sha256'],backup_verified=True,
        approved_files=9493,eligible_files=len(ready),skipped=skipped,before=before,quarantine=str(QUARANTINE),moved=[],modified=[])
    save(report/'execution.json',receipt)
    print('Verified backup and exact patch. Eligible files: '+str(len(ready)),flush=True)
    # Apply the native-only startup/packaging change before retiring frontend files.
    for relative,new_text in prepared.items():
        path=safe_path(ROOT,relative)
        if checksum(path)!=rows[relative]['sha256']:raise ValueError('Source changed after preflight; frontend not moved')
        temporary=path.with_name(path.name+'.phase1-writing');temporary.write_text(new_text,encoding='utf-8');os.replace(temporary,path)
        receipt['modified'].append(dict(path=relative,before_sha256=rows[relative]['sha256'],after_sha256=checksum(path)))
    save(report/'execution.json',receipt)
    journal=report/'quarantine-journal.jsonl'
    with journal.open('x',encoding='utf-8') as log:
        for i,row in enumerate(ready):
            try:
                source=safe_path(ROOT,row['path']);target=safe_path(QUARANTINE,row['path'])
                if not source.is_file() or checksum(source)!=row['sha256'] or target.exists():raise ValueError('File changed after preflight')
                target.parent.mkdir(parents=True,exist_ok=True)
                source.rename(target)
                if checksum(target)!=row['sha256']:raise ValueError('Quarantine integrity mismatch')
                entry=dict(path=row['path'],size_bytes=row['size_bytes'],sha256=row['sha256'])
                receipt['moved'].append(entry);log.write(json.dumps(entry)+'\n')
            except (OSError,ValueError) as exc:receipt['skipped'].append(dict(path=row['path'],reason=type(exc).__name__))
            if (i+1)%1000==0:log.flush();save(report/'execution.json',receipt);print('Quarantined '+str(len(receipt['moved']))+' files',flush=True)
    for relative,expected in retained.items():
        if checksum(safe_path(ROOT,relative))!=expected:raise ValueError('Protected exception changed')
    receipt.update(moved_files=len(receipt['moved']),moved_bytes=sum(r['size_bytes'] for r in receipt['moved']),protected_exceptions_verified=len(retained),
        after=tree_size(),permanently_deleted=0,phase2_executed=False)
    save(report/'execution.json',receipt)
    print(json.dumps({key:receipt[key] for key in ('report','moved_files','moved_bytes','protected_exceptions_verified','permanently_deleted','phase2_executed','skipped')}),flush=True)


if __name__=='__main__':main()
