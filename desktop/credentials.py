"""Windows current-user DPAPI. No plaintext fallback, no secrets in logs."""
import ctypes
from ctypes import wintypes
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data, decrypt=False):
    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows credential protection failed')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'credentials.dpapi'

    def load(self):
        if not self.path.exists():
            return ''
        return _protect(self.path.read_bytes(), decrypt=True).decode('utf-8')

    def save(self, key):
        if not key:
            self.path.unlink(missing_ok=True)
            return
        if len(key) > 4096 or any(c.isspace() for c in key):
            raise ValueError('Invalid API key format')
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(_protect(key.encode('utf-8')))
        temporary.replace(self.path)
