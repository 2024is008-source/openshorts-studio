"""Verify/preview a cleanup backup. Restoration requires --restore explicitly.

No deletion, moving, or overwrite occurs without that explicit flag. Existing
changed files are refused; this tool never replaces later user edits silently.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def checksum(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args();manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    root=Path(manifest['project']).resolve();backup=Path(manifest['backup']).resolve()
    if not manifest.get('backup_verified') or checksum(backup)!=manifest['backup_sha256']:raise ValueError('Backup hash mismatch; restoration refused')
    rows=manifest['files'];expected={r['path']:r for r in rows}
    missing=[];changed=[]
    with zipfile.ZipFile(backup) as archive:
        if set(archive.namelist())!=set(expected):raise ValueError('Backup inventory mismatch')
        for info in archive.infolist():
            row=expected[info.filename];relative=Path(info.filename)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe recovery member')
            raw=root/relative
            if raw.is_symlink() or any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in raw.parents if p!=root and p.is_relative_to(root)):raise ValueError('Linked recovery destination')
            destination=raw.resolve()
            if not destination.is_relative_to(root) or destination==root:raise ValueError('Recovery path escapes project')
            if destination.is_symlink() or any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in destination.parents if p!=root and p.is_relative_to(root)):raise ValueError('Linked recovery destination')
            with archive.open(info) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=row['sha256']:raise ValueError('Backup member hash mismatch')
            if destination.exists():
                if not destination.is_file() or checksum(destination)!=row['sha256']:changed.append(row['path'])
            else:missing.append(row['path'])
        if args.restore:
            if changed:raise ValueError('Existing modified files require manual conflict review; no files restored')
            for relative in missing:
                destination=(root/relative).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(relative) as source,destination.open('xb') as target:
                    for chunk in iter(lambda:source.read(1024*1024),b''):target.write(chunk)
                if checksum(destination)!=expected[relative]['sha256']:raise ValueError('Restored-file verification failed')
    print(json.dumps(dict(backup_verified=True,mode='restore' if args.restore else 'verify_only',members=len(rows),missing=len(missing),changed=len(changed),restored=len(missing) if args.restore else 0)))


if __name__=='__main__':main()
