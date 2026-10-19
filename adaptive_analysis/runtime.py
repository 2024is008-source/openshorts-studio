"""One job ledger; operation retries never acquire a fresh budget."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import time
from story_director import atomic_json

SCHEMA=1
PROMPT=1
from category_intelligence import REGISTRY, LEGACY
CATEGORIES=('auto',*REGISTRY,*LEGACY)
DEFAULTS={
    'economy':dict(video_seconds=120,visual_requests=4,input_tokens=24000,job_seconds=600,retries=1,candidates=24,text_requests=24),
    'balanced':dict(video_seconds=360,visual_requests=10,input_tokens=60000,job_seconds=1200,retries=2,candidates=40,text_requests=40),
    'quality':dict(video_seconds=720,visual_requests=20,input_tokens=120000,job_seconds=1800,retries=2,candidates=64,text_requests=64)}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


class BudgetExceeded(RuntimeError):pass
class Cancelled(RuntimeError):pass


def configuration():
    mode=os.getenv('ANALYSIS_MODE','adaptive-balanced').removeprefix('adaptive-')
    if mode not in DEFAULTS:raise ValueError('Unsupported adaptive analysis profile')
    category=os.getenv('AMCE_CATEGORY','auto')
    if category not in CATEGORIES:raise ValueError('Unsupported adaptive category')
    cfg=dict(DEFAULTS[mode],mode=mode,category=category,cost_ceiling=None,input_price=None,output_price=None)
    # Starting policy values, not benchmarked optimums.
    if category in ('cricket','football','sports_highlights'):
        cfg['input_tokens']={'economy':60000,'balanced':180000,'quality':360000}[mode]
    elif category.startswith('podcast'):
        cfg['visual_requests']={'economy':2,'balanced':6,'quality':12}[mode]
    for key,maximum in dict(video_seconds=1800,visual_requests=60,input_tokens=500000,job_seconds=3600,retries=3,candidates=100,text_requests=120).items():
        raw=os.getenv('AMCE_MAX_'+key.upper())
        if raw is not None:
            try:value=int(raw)
            except ValueError:raise ValueError('Invalid analysis budget') from None
            if not 0<=value<=maximum:raise ValueError('Analysis budget out of bounds')
            cfg[key]=value
    for key in ('cost_ceiling','input_price','output_price'):
        raw=os.getenv('AMCE_'+key.upper())
        if raw is not None:
            try:value=float(raw)
            except ValueError:raise ValueError('Invalid analysis pricing') from None
            if not math.isfinite(value) or not 0<=value<=10000:raise ValueError('Invalid analysis pricing')
            cfg[key]=value
    if cfg['cost_ceiling'] is not None and (cfg['input_price'] is None or cfg['output_price'] is None):raise ValueError('Cost ceiling requires configured per-million input/output prices')
    return cfg


class Ledger:
    def __init__(self,cfg,path,cancel=None):
        self.cfg=cfg;self.path=Path(path);self.cancel=cancel;self.started=time.monotonic()
        self.requests={'text':0,'visual':0};self.video_seconds=0.;self.estimated_tokens=0
        self.usage={'input_tokens':0,'output_tokens':0,'thinking_tokens':0};self.actual_cost=0.;self.reserved_cost=0.
        self.payloads=set();self.payload_seconds={};self.attempts={};self.cache_hits=0;self.events=[];self.stages={};self.current=None
        self.transfer_retries={}
        self.upload_seconds=0.;self.local_processing_seconds=0.;self.encoding_seconds=0.
    def check(self):
        if self.cancel and self.cancel.is_set():raise Cancelled('Adaptive analysis cancelled; validated checkpoints retained')
        if time.monotonic()-self.started>=self.cfg['job_seconds']:raise BudgetExceeded('Job analysis latency budget exhausted')
        if self.usage['input_tokens']>self.cfg['input_tokens']:raise BudgetExceeded('Reported input-token budget exhausted')
        if self.cfg['cost_ceiling'] is not None and self.cfg['input_price'] is not None:
            priced=(self.usage['input_tokens']*self.cfg['input_price']+(self.usage['output_tokens']+self.usage['thinking_tokens'])*self.cfg['output_price'])/1e6
            if priced>=self.cfg['cost_ceiling']:raise BudgetExceeded('Reported priced usage exhausted cost ceiling')
    def timeout_ms(self,maximum=90000):
        self.check()
        return max(1,min(maximum,int((self.cfg['job_seconds']-(time.monotonic()-self.started))*1000)))
    def request(self,identity,kind,tokens,seconds=0,output_allowance=2048,prepare=False):
        self.check();count=self.attempts.get(identity,0)
        if count+self.transfer_retries.get(identity,0)>self.cfg['retries']:raise BudgetExceeded('Logical operation retry budget exhausted')
        if self.requests[kind]>=self.cfg['visual_requests' if kind=='visual' else 'text_requests']:raise BudgetExceeded(kind+' request budget exhausted')
        # Count every generation submission, including retries/context requests.
        # Reusing a file avoids another upload, but still submits video to inference.
        extra=seconds
        if self.video_seconds+extra>self.cfg['video_seconds']:raise BudgetExceeded('Submitted video duration budget exhausted')
        if self.estimated_tokens+tokens>self.cfg['input_tokens']:raise BudgetExceeded('Estimated input-token budget exhausted')
        cost=((tokens*self.cfg['input_price']+output_allowance*self.cfg['output_price'])/1e6
            if self.cfg['input_price'] is not None and self.cfg['output_price'] is not None else 0.)
        if self.cfg['cost_ceiling'] is not None and self.reserved_cost+cost>self.cfg['cost_ceiling']:raise BudgetExceeded('Configured cost ceiling exhausted')
        if prepare:return
        self.requests[kind]+=1;self.attempts[identity]=count+1;self.video_seconds+=extra;self.payloads.add(identity)
        self.payload_seconds[identity]=max(seconds,self.payload_seconds.get(identity,0))
        self.estimated_tokens+=tokens;self.reserved_cost+=cost
        self.events.append(dict(operation=identity,kind=kind,attempt=count+1));self.save()
    def transfer_retry(self,identity):
        self.transfer_retries[identity]=self.transfer_retries.get(identity,0)+1
        if max(0,self.attempts.get(identity,0)-1)+self.transfer_retries[identity]>self.cfg['retries']:raise BudgetExceeded('Logical media retry budget exhausted')
        self.check()
    def record_usage(self,value):
        value=value or {}
        for key in self.usage:self.usage[key]+=max(0,int(value.get(key,0) or 0))
        self.actual_cost+=max(0,float(value.get('total_cost',0) or 0));self.save()
    def stage(self,name,completed=0,total=None,cache=False,retry=False):
        now=time.monotonic()
        if self.current and self.current!=name:self.stages[self.current]['elapsed_seconds']=round(now-self.stages[self.current]['_start'],3)
        self.current=name
        item=self.stages.setdefault(name,{'_start':now})
        item.update(completed=completed,total=total,elapsed_seconds=round(now-item['_start'],3),cache_reuse=cache,retry=retry)
        print('AMCE_PROGRESS '+json.dumps(dict(stage=name,**{k:v for k,v in item.items() if not k.startswith('_')})),flush=True)
        self.save()
    def save(self):
        atomic_json(self.path,dict(schema=SCHEMA,requests=self.requests,video_seconds=self.video_seconds,
            unique_operation_video_seconds=sum(self.payload_seconds.values()),
            estimated_input_tokens=self.estimated_tokens,usage=self.usage,reported_provider_cost=self.actual_cost,
            reserved_pricing_cost=self.reserved_cost if self.cfg['input_price'] is not None else None,
            upload_seconds=round(self.upload_seconds,3),local_processing_seconds=round(self.local_processing_seconds,3),encoding_seconds=round(self.encoding_seconds,3),
            cache_hits=self.cache_hits,retry_count=sum(max(0,n-1) for n in self.attempts.values())+sum(self.transfer_retries.values()),
            elapsed_seconds=round(time.monotonic()-self.started,3),stages={k:{a:b for a,b in v.items() if not a.startswith('_')} for k,v in self.stages.items()}))


class Cache:
    def __init__(self,root,source,model,cfg):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.source=source
        self.scope=digest([SCHEMA,PROMPT,source,model,cfg.get('category'),cfg.get('prompt_constraint','')])
    def key(self,kind,identity):return digest([SCHEMA,self.source,kind,identity]) if kind=='media-index' else digest([self.scope,kind,identity])
    def read(self,kind,identity):
        key=self.key(kind,identity);path=self.root/(key+'.json')
        try:
            if path.stat().st_size>8*1024*1024:return None
            record=json.loads(path.read_text(encoding='utf-8'))
            if record.get('key')==key:return record['value']
        except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
        return None
    def write(self,kind,identity,value):
        key=self.key(kind,identity);atomic_json(self.root/(key+'.json'),{'key':key,'value':value})
        # Bound metadata cache without touching source media or project timelines.
        entries=sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        for stale in entries[512:]:
            try:stale.unlink()
            except OSError:pass
