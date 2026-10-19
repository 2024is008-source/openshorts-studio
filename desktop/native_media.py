"""Short playback aliases for LibVLC 3 on Windows; original references stay intact."""
import hashlib
import os
from pathlib import Path
import re
import shutil


def playback_path(path,folder):
    path=Path(path).resolve()
    if len(str(path))<240:return str(path)
    folder=Path(folder).resolve()
    stat=path.stat()
    key=hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:20]
    extension=path.suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,6}',extension):extension='.mp4'
    target=folder/f'.desktop-preview-{key}{extension}'
    if target.is_symlink() or not target.resolve().is_relative_to(folder):raise OSError('Linked playback aliases are not supported')
    if not target.exists():
        try:os.link(path,target)
        except OSError:shutil.copy2(path,target)
    if target.stat().st_size!=stat.st_size:raise OSError('Playback alias does not match the retained media')
    return str(target)
