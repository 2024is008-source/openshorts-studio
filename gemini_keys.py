"""Shared bounded Gemini credential selection. Never includes keys in messages."""
import itertools
import os
import re
import threading

_jobs=itertools.count()
_lock=threading.Lock()


def numbered_names(env):
    return sorted((n for n in env if re.fullmatch(r'GEMINI_API_KEY_[1-9][0-9]?',n)),key=lambda n:int(n.rsplit('_',1)[1]))


def configured(env=None):
    env=os.environ if env is None else env
    names=['GEMINI_API_KEY',*numbered_names(env)]
    keys=[]
    for name in names:
        value=env.get(name)
        if isinstance(value,str) and value.strip() and value.strip() not in keys:keys.append(value.strip())
    return keys[:32]


def assign_job(env):
    """Round-robin primary per job, retaining the remaining keys as failover."""
    keys=configured(env)
    if not keys:return env
    with _lock:index=next(_jobs)%len(keys)
    keys=keys[index:]+keys[:index]
    for name in numbered_names(env):env.pop(name,None)
    env.update({f'GEMINI_API_KEY_{i+1}':key for i,key in enumerate(keys)})
    env['GEMINI_API_KEY']=keys[0]
    return env
