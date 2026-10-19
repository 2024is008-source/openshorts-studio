"""Allowlisted render failure facts. Never persist argv, exception text or media."""
import json
import os
from pathlib import Path
import re
import time

STAGES={'Preparing export':'prepare','Encoding video segment':'encode','Rendering changed video segments':'segments',
        'Assembling video':'assemble','Rendering captions':'captions','Rendering overlays':'overlays',
        'Mastering timeline audio':'audio','Validating rendered output':'validate'}

def facts(error,stage,run_id):
    import render_runtime
    cls=type(error).__name__
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,80}',cls):cls='Exception'
    code=getattr(error,'winerror',None);exit_code=getattr(error,'returncode',None)
    data=dict(version=1,event='editor_failure',exception_type=cls,
        windows_error=code if type(code) is int else None,
        ffmpeg_exit_code=exit_code if type(exit_code) is int else None,
        stage=next((v for k,v in STAGES.items() if str(stage).startswith(k)),'editor'),
        worker_pid=os.getpid(),run_id=run_id if re.fullmatch('[0-9a-f]{32}',str(run_id)) else None,
        resource_limits=render_runtime.limits(),time=time.time())
    try:
        import psutil
        process=psutil.Process();children=process.children(recursive=True)
        data.update(available_memory_bytes=psutil.virtual_memory().available,worker_rss_bytes=process.memory_info().rss,
            owned_child_count=len(children),owned_ffmpeg_count=sum(p.name().lower() in ('ffmpeg','ffmpeg.exe') for p in children))
    except Exception:pass
    return data

def record(directory,error,stage,run_id):
    data=facts(error,stage,run_id)
    try:
        target=Path(directory)/'editor-diagnostics.jsonl'
        with target.open('a',encoding='utf-8') as stream:stream.write(json.dumps(data)+'\n')
    except OSError:pass  # Do not mask the original exception if logging is unavailable.
    return data
