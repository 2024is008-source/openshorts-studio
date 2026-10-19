"""Load a protected local Gemini pool without replacing saved source settings."""
import json
import hashlib
import time
from pathlib import Path
from desktop.credentials import CredentialStore


def apply_pool(env,directory,explicit=None):
    directory=Path(directory)
    source='env' if explicit else 'protected_pool'
    if explicit:keys=explicit
    else:
        if not (directory/'credentials.dpapi').is_file():return env
        keys=json.loads(CredentialStore(directory).load())
    if not isinstance(keys,list) or not 1<=len(keys)<=32 or any(not isinstance(k,str) or not k or len(k)>4096 or any(c.isspace() for c in k) for k in keys):
        raise ValueError('Invalid protected Gemini key pool')
    keys=list(dict.fromkeys(keys))
    model=env.get('GEMINI_MODEL_VISION') or env.get('GEMINI_MODEL') or 'gemini-3.1-flash-lite'
    try:
        health=json.loads((directory/'key-health.json').read_text(encoding='utf-8'))
        records=health.get('keys',{}) if health.get('version')==1 else {}
        def rejected(key):
            row=records.get(hashlib.sha256(key.encode()).hexdigest(),{})
            return (row.get('model')==model and row.get('http_status') in (401,403)
                and type(row.get('checked_at')) in (int,float) and 0<=time.time()-row['checked_at']<3600)
        keys=[key for key in keys if not rejected(key)]
    except (OSError,ValueError,TypeError,AttributeError):pass
    for name in list(env):
        if name.startswith('LLM_') or name.startswith('GEMINI_API_KEY_'):env.pop(name,None)
    env.update(LLM_PROVIDER='gemini',GEMINI_API_KEY=keys[0] if keys else '',GEMINI_KEY_POOL='1' if keys else '0',
        GEMINI_KEY_SOURCE=source,GEMINI_KEY_POOL_SIZE=str(len(keys)),TRANSCRIBE_BACKEND='whisper')
    env.update({f'GEMINI_API_KEY_{i+1}':key for i,key in enumerate(keys)})
    return env
