"""User storage, bounded settings and deliberately narrow cache cleanup."""
import json
import os
import shutil
from pathlib import Path


class Storage:
    def __init__(self, local=None, roaming=None):
        self.roaming = Path(roaming or Path(os.environ['APPDATA']) / 'OpenShorts')
        selected = None
        if local is None:
            try:
                value = json.loads((self.roaming / 'library-location.json').read_text('utf-8'))
                if isinstance(value, str) and Path(value).is_absolute():
                    selected = value
            except (OSError, ValueError):
                pass
        self.local = Path(local or selected or Path(os.environ['LOCALAPPDATA']) / 'OpenShorts')
        for directory in (self.local, self.roaming, self.work, self.cache,
                          self.local / 'output', self.local / 'uploads', self.local / 'models'):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def work(self):
        return self.local / 'temp'

    @property
    def cache(self):
        return self.local / 'cache'

    def check_space(self, required=2 * 1024**3):
        if shutil.disk_usage(self.local).free < required:
            raise OSError('At least 2 GB of free working space is required. Free disk space and retry.')

    def settings(self):
        try:
            return validate_settings(json.loads((self.roaming / 'settings.json').read_text('utf-8')))
        except (OSError, ValueError, TypeError):
            return validate_settings({})

    def save_settings(self, settings):
        value = validate_settings(settings)
        destination = self.roaming / 'settings.json'
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2), 'utf-8')
        temporary.replace(destination)

    def clear_cache(self):
        # Caller must stop the backend first. Do not follow junctions/symlinks.
        for root in (self.work, self.cache):
            if is_link(root) or root.resolve().parent != self.local.resolve():
                raise ValueError('Unsafe cache directory')
            for path in root.rglob('*'):
                if is_link(path) or path.resolve().is_relative_to(root.resolve()) is False:
                    raise ValueError('Linked cache entries cannot be cleaned')
                if hasattr(path, 'is_junction') and path.is_junction():
                    raise ValueError('Cache junctions cannot be cleaned')
            for path in root.iterdir():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()


def is_link(path):
    # Python 3.11 Path.is_junction does not exist. Reparse attributes cover both
    # junctions and symlinks without following them during recursive cleanup.
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError('Settings must be an object')
    encoder = value.get('encoder', 'auto')
    preset = value.get('preset', 'balanced')
    if encoder not in ('auto', 'x264', 'nvenc') or preset not in ('balanced', 'quiet', 'performance'):
        raise ValueError('Unknown performance setting')
    # Only one concurrent pipeline has been qualified for the desktop host.
    return {'encoder': encoder, 'preset': preset, 'jobs': 1}
