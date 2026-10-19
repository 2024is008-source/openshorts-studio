"""Explicit tiny live probe. Never prints credentials or raw provider errors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def check(slot):
    import httpx
    label,source,key,model=slot
    result=dict(slot=label,source=source,model=model,success=False)
    started=time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(25,connect=10,write=15),headers={'x-goog-api-key':key}) as client:
            url='https://generativelanguage.googleapis.com/v1beta/models/'+model.removeprefix('models/')
            response=client.get(url)
            result['metadata_status']=response.status_code
            if response.status_code==200:
                config={'maxOutputTokens':8}
                if 'gemini-3' in model:config['thinkingConfig']={'thinkingLevel':'minimal' if 'flash-lite' in model else 'low'}
                response=client.post(url+':generateContent',json={
                    'contents':[{'parts':[{'text':'Reply OK only.'}]}],'generationConfig':config})
                result['ping_status']=response.status_code
                if response.status_code==200:
                    value=response.json()
                    result['success']=any(p.get('text','').strip() for c in value.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if not p.get('thought'))
                    result['usage']={k:v for k,v in value.get('usageMetadata',{}).items() if k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount')}
                result['status']='working' if result['success'] else 'quota_or_rate_limit' if response.status_code==429 else 'authentication_rejected' if response.status_code in (400,401,403) else 'provider_error' if response.status_code>=500 else 'empty_or_blocked_response'
            else:
                result['status']='model_unavailable' if response.status_code==404 else 'authentication_rejected' if response.status_code in (400,401,403) else 'quota_or_rate_limit' if response.status_code==429 else 'provider_error'
    except Exception as exc:
        result['status']='transport_error';result['error_type']=type(exc).__name__
    result['elapsed_seconds']=round(time.monotonic()-started,2)
    return result


def main():
    from dotenv import dotenv_values
    from gemini_keys import configured,numbered_names
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-saved',action='store_true')
    parser.add_argument('--save-health',action='store_true',help='Temporarily exclude authentication-rejected keys from this model for one hour.')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=dotenv_values(ROOT/'.env',interpolate=False)
    model=config.get('GEMINI_MODEL_VISION') or config.get('GEMINI_MODEL') or 'gemini-3.1-flash-lite'
    slots=[];seen=set()
    for name in ['GEMINI_API_KEY',*numbered_names(config)]:
        key=config.get(name)
        if isinstance(key,str) and key.strip() and key.strip() not in seen:
            key=key.strip();slots.append((name,'env',key,model));seen.add(key)
    if args.include_saved:
        from desktop.credentials import CredentialStore
        raw=CredentialStore(ROOT/'.local-gemini').load()
        old=json.loads(raw) if raw else []
        for index,key in enumerate(old):
            if isinstance(key,str) and key and key not in seen:
                slots.append((f'saved_slot_{index+1}','protected_saved_pool',key,model));seen.add(key)
    report={'model':model,'tests':[],'remaining_account_credit':'Not available through this key ping; no account balance is inferred.'}
    with ThreadPoolExecutor(max_workers=2) as executor:
        for row in executor.map(check,slots):
            report['tests'].append(row)
            print(json.dumps(row),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    if args.save_health:save_health(report,slots)


def save_health(report,slots):
    import hashlib
    records={}
    by_label={label:key for label,source,key,model in slots}
    for row in report['tests']:
        key=by_label.get(row['slot'])
        if not key:continue
        records[hashlib.sha256(key.encode()).hexdigest()]={
            'model':row['model'],'http_status':row.get('ping_status',row.get('metadata_status')),
            'checked_at':time.time(),'status':row['status']}
    root=ROOT/'.local-gemini';root.mkdir(parents=True,exist_ok=True)
    temporary=root/'key-health.writing'
    temporary.write_text(json.dumps({'version':1,'keys':records}),encoding='utf-8')
    temporary.replace(root/'key-health.json')


if __name__=='__main__':main()
