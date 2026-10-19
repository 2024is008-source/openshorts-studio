"""Discover URL download tools in source and frozen resources; no tool download."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys

def deno_path():
    from desktop.processes import resources
    name='deno.exe' if os.name=='nt' else 'deno'
    paths=[resources()/'bin'/name,Path(sys.executable).parent/name]
    for path in paths:
        if path.is_file():return str(path)
    return None if getattr(sys,'frozen',False) else shutil.which('deno')

def status():
    def installed(name):
        try:return importlib.util.find_spec(name) is not None
        except (ImportError,ValueError):return False
    return dict(yt_dlp=installed('yt_dlp'),deno=bool(deno_path()),challenge_solver_assets=installed('yt_dlp_ejs'),
        frozen=bool(getattr(sys,'frozen',False)),developer_path_fallback=not bool(getattr(sys,'frozen',False)),
        protected_content_supported=False)
