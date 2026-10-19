"""Gemini adapter reusing existing keys, validation, uploads and retry code."""
from contextlib import contextmanager
import json
import time
from .runtime import BudgetExceeded,digest


class Operation:
    def __init__(self,ledger,identity,seconds,tokens,fps=2):
        self.ledger=ledger;self.identity=identity;self.seconds=seconds;self.tokens=tokens;self.fps=fps
    def request(self):
        self.ledger.request(self.identity,'visual',self.tokens,self.seconds,output_allowance=4096)
        stage=self.ledger.stages.get('verify',{})
        self.ledger.stage('verify',stage.get('completed',0),stage.get('total'),retry=self.ledger.attempts[self.identity]>1)
    def prepare(self):self.ledger.request(self.identity,'visual',self.tokens,self.seconds,4096,prepare=True)
    def transfer_retry(self):self.ledger.transfer_retry(self.identity)
    def upload_key(self,key,media):
        import hashlib
        return digest([hashlib.sha256(key.encode()).hexdigest(),hashlib.sha256(media.read_bytes()).hexdigest()])
    def upload_reference(self,key,media,info=None):
        from pathlib import Path
        from story_director import atomic_json
        path=self.ledger.path.parent/'amce-upload-references.json'
        try:
            records=json.loads(path.read_text()) if path.stat().st_size<512000 else {}
        except (OSError,ValueError):records={}
        if not isinstance(records,dict):records={}
        identity=self.upload_key(key,media)
        if info is None:return records.get(identity)
        records[identity]={'name':info.name,'saved_at':time.time()}
        records={k:v for k,v in records.items() if isinstance(v,dict) and time.time()-v.get('saved_at',0)<46*3600}
        atomic_json(path,dict(list(records.items())[-128:]));return records[identity]


@contextmanager
def scope(operation):
    import story_director as sd
    values={'adaptive_operation':operation,'visual_output_tokens':4096,'video_fps':operation.fps}
    before={key:getattr(sd._chapter_context,key,None) for key in values}
    for key,value in values.items():setattr(sd._chapter_context,key,value)
    try:yield
    finally:
        for key,value in before.items():setattr(sd._chapter_context,key,value)


class Gateway:
    def __init__(self,model,ledger):self.model=model;self.ledger=ledger;self.capabilities=None
    def validate(self):
        if self.capabilities is not None:return self.capabilities
        from google import genai
        import gemini_worker,story_director as sd
        from google.genai import types
        keys=sd.api_keys()
        if not keys:raise ValueError('Configure a usable Gemini key')
        self.ledger.check()
        client=genai.Client(api_key=keys[0],http_options=gemini_worker.http_options().model_copy(update={'timeout':self.ledger.timeout_ms()}))
        try:
            metadata=client.models.get(model=self.model)
            actions=getattr(metadata,'supported_actions',None) or []
            if actions and not any('generatecontent' in str(a).replace('_','').lower() for a in actions):raise ValueError('Configured model does not support content generation')
            self.capabilities=dict(model=self.model,generate_content=True,files=hasattr(client.files,'upload'),
                temporal_sampling='video_metadata' in types.Part.model_fields,
                limitations=['Model metadata does not independently certify video quality or event recall.'])
            return self.capabilities
        finally:client.close()
    def text(self,prompt,schema,identity,kind='text',images=()):
        from google import genai
        from google.genai import types
        import gemini_worker,story_director as sd
        self.validate();keys=sd.api_keys()
        # No quota-based key rotation. A logical request stays with its selected key.
        selected=int(identity[:8],16)%len(keys)
        client=genai.Client(api_key=keys[selected],http_options=gemini_worker.http_options().model_copy(update={'timeout':self.ledger.timeout_ms()}))
        compatible=False;tokens=max(1,len(prompt)//3)+len(images)*1024
        try:
            for attempt in range(self.ledger.cfg['retries']+1):
                self.ledger.request(identity,kind,tokens,output_allowance=4096)
                config=types.GenerateContentConfig(response_mime_type='application/json',response_schema=None if compatible else schema,max_output_tokens=4096)
                if 'gemini-3' in self.model:config.thinking_config=types.ThinkingConfig(thinking_level='minimal' if 'flash-lite' in self.model else 'low')
                contents=[*images,prompt+('\nReturn exactly this JSON schema: '+json.dumps(schema.model_json_schema()) if compatible else '')]
                try:
                    response=client.models.generate_content(model=self.model,contents=contents,config=config)
                    gemini_worker.raise_if_blocked(response)
                    cost=gemini_worker._calculate_cost_analysis(response,self.model)
                    self.ledger.record_usage(cost)
                    return sd._analysis_response(response,schema)
                except gemini_worker.GeminiBlockedError:raise
                except Exception as exc:
                    if getattr(exc,'code',None) in (401,403,429) or 'RESOURCE_EXHAUSTED' in str(exc):raise
                    if getattr(exc,'code',None)==400 and not compatible:compatible=True
                    elif not (sd.transient_analysis_error(exc) or isinstance(exc,ValueError)):raise
                    if attempt>=self.ledger.cfg['retries']:raise
                    self.ledger.check();time.sleep(min(2,attempt+1))
        finally:client.close()
    def video(self,proxy,prompt,seconds,identity,fps=2):
        import story_director as sd
        self.validate()
        if not self.capabilities['files'] or not self.capabilities['temporal_sampling']:raise ValueError('Installed Gemini SDK lacks required video transport/sampling support')
        tokens=max(1,len(prompt)//3)+int(seconds*fps*128)
        operation=Operation(self.ledger,identity,seconds,tokens,fps)
        with scope(operation):return sd._inspect(proxy,prompt,self.model)[0]
