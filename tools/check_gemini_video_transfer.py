"""One explicitly authorized 10-second video generation; sanitized diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from desktop.processes import environment
    from desktop.storage import Storage
    from google import genai
    from google.genai import types
    from gemini_keys import configured
    out=ROOT/'build/gemini-video-transfer';out.mkdir(parents=True,exist_ok=True)
    storage=Storage(ROOT/'OpenShorts Library',out/'profile')
    env=environment(storage,storage.settings(),'')
    keys=configured(env);model=env.get('GEMINI_MODEL_VISION') or env.get('GEMINI_MODEL') or 'gemini-3.1-flash-lite'
    result=dict(model=model,key_source=env.get('GEMINI_KEY_SOURCE'),generation_calls=0,stages={})
    client=genai.Client(api_key=keys[0],http_options=types.HttpOptions(timeout=45_000,retry_options=types.HttpRetryOptions(attempts=1)))
    uploaded=None;stage='encode'
    try:
        with tempfile.TemporaryDirectory(dir=out) as folder:
            proxy=Path(folder)/'sample.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss','0','-t','10','-i',str(Path('D:/1016.mp4')),
                '-vf',"scale='min(640,iw)':-2,fps=8",'-c:v','libx264','-preset','veryfast','-crf','28','-threads','2','-filter_threads','1',
                '-c:a','aac','-ar','24000','-b:a','48k',str(proxy)],check=True,capture_output=True,timeout=60)
            result['proxy_bytes']=proxy.stat().st_size
            stage='file_upload';print('Live sample: file upload',flush=True);started=time.monotonic()
            uploaded=client.files.upload(file=str(proxy));result['stages'][stage]=round(time.monotonic()-started,2)
            stage='file_processing';print('Live sample: file processing',flush=True);started=time.monotonic()
            while time.monotonic()-started<45:
                info=client.files.get(name=uploaded.name)
                if info.state.name=='ACTIVE':break
                if info.state.name=='FAILED':raise RuntimeError('Processing failed')
                time.sleep(1)
            else:raise TimeoutError('Processing timeout')
            result['stages'][stage]=round(time.monotonic()-started,2)
            stage='video_generation';print('Live sample: one video-generation request',flush=True);started=time.monotonic()
            result['generation_calls']=1
            response=client.models.generate_content(model=model,contents=[info,
                'Describe one visible action in this supplied 10-second video. Return JSON with visible_action (short string), start (seconds), end (seconds). Use only visible evidence.'],
                config=types.GenerateContentConfig(response_mime_type='application/json',max_output_tokens=256,
                    thinking_config=types.ThinkingConfig(thinking_level='minimal')))
            result['stages'][stage]=round(time.monotonic()-started,2)
            result['observation']=json.loads(response.text)
            result['success']=True
            usage=response.usage_metadata
            result['tokens']={k:getattr(usage,k,None) for k in ('prompt_token_count','candidates_token_count','total_token_count')}
    except Exception as exc:
        result.update(success=False,failed_stage=stage,error_type=type(exc).__name__)
        if isinstance(getattr(exc,'code',None),int):result['http_status']=exc.code
    finally:
        if uploaded:
            try:client.files.delete(name=uploaded.name)
            except Exception:pass
        client.close()
        (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
