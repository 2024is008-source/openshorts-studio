"""Race-free Windows process tree ownership; no console windows."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import subprocess
import sys


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t),
                ('max_working', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                ('scheduling', wintypes.DWORD)]


class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class ProcessTree:
    def __init__(self):
        self.children = []
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        self.handle = k.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('Cannot create Windows process ownership boundary')

    def start(self, command, *, env, cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        child = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(child._handle))):
                raise OSError('Cannot assign backend to Windows Job Object')
            nt = ctypes.WinDLL('ntdll')
            nt.NtResumeProcess.argtypes = [wintypes.HANDLE]
            nt.NtResumeProcess.restype = ctypes.c_long
            if nt.NtResumeProcess(wintypes.HANDLE(int(child._handle))) != 0:
                raise OSError('Cannot resume desktop backend')
        except BaseException:
            child.kill()
            child.wait(timeout=10)
            raise
        self.children.append(child)
        return child

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        for child in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def command(mode, *arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, mode, *map(str, arguments)]
    return [sys.executable, str(resources() / 'desktop_entry.py'), mode, *map(str, arguments)]


def engine_command(script):
    if getattr(sys, 'frozen', False):
        return command('--worker', script)
    return [sys.executable, '-u', str(resources() / script)]


def environment(storage, settings, gemini_key):
    # Start from a restricted environment; only allowlisted local Gemini settings are read below.
    safe = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'USERPROFILE',
            'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'USERNAME')
    env = {key: value for key, value in os.environ.items() if key.upper() in safe}
    env.update(OPENSHORTS_DESKTOP='1', BILLING_ENABLED='false', PYTHONUTF8='1',
               PYTHONUNBUFFERED='1', PYTHON_DOTENV_DISABLED='1',
               OPENSHORTS_LOCAL_TOKEN=secrets.token_urlsafe(48),
               MAX_CONCURRENT_JOBS='1', OUTPUT_MAX_GB='0', UPLOADS_MAX_GB='0',
               OUTPUT_DIR=str(storage.local / 'output'),
               OPENSHORTS_LEARNING_DIR=str(storage.local / 'learning'),
               OPENSHORTS_ANALYSIS_CACHE=str(storage.cache / 'video-analysis'),
               TEMP=str(storage.work), TMP=str(storage.work),
               HF_HOME=str(storage.local / 'models' / 'huggingface'),
               TORCH_HOME=str(storage.local / 'models' / 'torch'),
               TORCHINDUCTOR_CACHE_DIR=str(storage.cache / 'torchinductor'),
               YOLO_CONFIG_DIR=str(storage.local / 'models' / 'ultralytics'),
               YOLO_MODEL_PATH=str(resources() / 'yolov8n.pt'),
               FFMPEG_ENCODER=settings['encoder'], CLIP_WORKERS='1',
               RENDER_MAX_ENCODERS='1', RENDER_SERVICE_WORKERS='1',
               GEMINI_API_KEY=gemini_key)
    explicit_keys=[]
    if not getattr(sys,'frozen',False):
        from dotenv import dotenv_values
        local_config=resources()/'.env'
        config=dotenv_values(local_config,interpolate=False) if local_config.is_file() else {}
        from gemini_keys import configured
        explicit_keys=configured(config)
        if any(len(key)>4096 or any(c.isspace() for c in key) for key in explicit_keys):raise ValueError('Invalid configured Gemini key format')
        for name in ('GEMINI_MODEL','GEMINI_MODEL_VISION'):
            value=config.get(name)
            if isinstance(value,str) and __import__('re').fullmatch(r'[A-Za-z0-9_./-]{1,128}',value):env[name]=value
        # Nonsecret, allowlisted adaptive limits; runtime validates numeric bounds.
        for name in ('AMCE_MAX_VIDEO_SECONDS','AMCE_MAX_VISUAL_REQUESTS','AMCE_MAX_INPUT_TOKENS',
                     'AMCE_MAX_JOB_SECONDS','AMCE_MAX_RETRIES','AMCE_MAX_CANDIDATES','AMCE_MAX_TEXT_REQUESTS',
                     'AMCE_COST_CEILING','AMCE_INPUT_PRICE','AMCE_OUTPUT_PRICE'):
            value=config.get(name)
            if isinstance(value,str) and __import__('re').fullmatch(r'\d{1,9}(?:\.\d{1,8})?',value):env[name]=value
    threads = {'quiet': '2', 'balanced': '4', 'performance': '8'}[settings['preset']]
    env.update(FFMPEG_THREADS=threads, OMP_NUM_THREADS=threads,
               MKL_NUM_THREADS=threads, REMOTION_CONCURRENCY='2')
    env['PATH'] = str(resources() / 'bin') + os.pathsep + env.get('PATH', '')
    whisper = storage.local / 'models' / 'whisper-small'
    from desktop.model_provisioning import verified_path
    try:pinned=verified_path(storage)
    except (OSError,ValueError):pinned=None
    if pinned:
        env['WHISPER_MODEL']=str(pinned)
    elif (whisper / 'model.bin').exists() and (whisper / 'config.json').exists():
        env['WHISPER_MODEL'] = str(whisper)
    from desktop.gemini_keys import apply_pool
    return apply_pool(env,resources()/'.local-gemini',explicit_keys)


def hide_child_consoles():
    """Applied only inside owned desktop workers, including transitive FFmpeg calls."""
    base = subprocess.Popen

    class HiddenPopen(base):
        def __init__(self, *args, **kwargs):
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = HiddenPopen
