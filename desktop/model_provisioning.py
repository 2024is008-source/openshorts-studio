"""Consent-only, pinned Whisper provisioning into the user's writable library."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

class Cancelled(Exception):pass

def manifest():
    from desktop.processes import resources
    data=json.loads((resources()/'assets/whisper-small-manifest.json').read_text('utf-8'))
    if not re.fullmatch('[0-9a-f]{40}',data['revision']):raise ValueError('Invalid model revision')
    for row in data['files']:
        if Path(row['name']).name!=row['name'] or row['name'] in ('.','..') or not re.fullmatch('[0-9a-f]{64}',row['sha256']) or not 0<row['size']<2**31:raise ValueError('Invalid model file manifest')
    return data

def model_directory(storage,data=None):
    return storage.local/'models/whisper-small-pinned'/(data or manifest())['revision']

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def verified_path(storage):
    """No network, no cache download and no changes to pre-existing legacy models."""
    data=manifest();folder=model_directory(storage,data)
    for parent in [folder,*folder.parents]:
        if parent.exists() and (parent.is_symlink() or (os.name=='nt' and parent.stat().st_file_attributes & 0x400)):return None
        if parent==storage.local:break
    for row in data['files']:
        p=folder/row['name']
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=row['size'] or digest(p)!=row['sha256']:return None
    return folder

class Provisioner:
    def __init__(self,storage,data=None,client_factory=None):
        self.storage=storage;self.data=data or manifest();self.folder=model_directory(storage,self.data)
        self.client_factory=client_factory;self.cancelled=threading.Event();self.lock=threading.RLock();self.thread=None
        self.state='not_installed';self.error=None;self.downloaded=0;self.verified=None
    def _check_paths(self):
        for p in [self.folder,*self.folder.parents]:
            if p.exists() and (p.is_symlink() or (os.name=='nt' and p.stat().st_file_attributes & 0x400)):raise ValueError('Linked model storage is unsupported')
            if p==self.storage.local:break
    def available(self):
        self._check_paths();signature=[]
        for row in self.data['files']:
            p=self.folder/row['name']
            if p.is_symlink() or not p.is_file():return False
            signature.append((p.stat().st_size,p.stat().st_mtime_ns))
        if self.verified==signature:return True
        for row in self.data['files']:
            p=self.folder/row['name']
            if p.stat().st_size!=row['size'] or digest(p)!=row['sha256']:return False
        self.verified=signature;return True
    def status(self):
        running=bool(self.thread and self.thread.is_alive())
        try:
            available=self.available() if not running else False
            partial=sum((self.folder/(r['name']+'.partial')).stat().st_size for r in self.data['files'] if (self.folder/(r['name']+'.partial')).is_file())
        except (OSError,ValueError):
            available=False;partial=0
            self.error='verification_or_storage_failed'
            if not running:self.state='failed'
        return dict(id=self.data['id'],revision=self.data['revision'],available=available,
            state='ready' if available else self.state,running=running,error_code=self.error,
            downloaded_bytes=min(self.downloaded,sum(r['size'] for r in self.data['files'])),total_bytes=sum(r['size'] for r in self.data['files']),
            recoverable_partial_bytes=partial,user_controlled=True)
    def start(self,acknowledged=False):
        if not acknowledged:raise ValueError('Confirm the model download and required disk space first')
        with self.lock:
            if self.thread and self.thread.is_alive():return self.status()
            if self.available():return self.status()
            self.storage.check_space();self._check_paths();self.folder.mkdir(parents=True,exist_ok=True)
            self.cancelled.clear();self.error=None;self.state='downloading';self.downloaded=0
            self.thread=threading.Thread(target=self._work,daemon=True);self.thread.start()
        return self.status()
    def cancel(self):
        self.cancelled.set()
        if self.thread and self.thread.is_alive():self.state='cancelling'
        return self.status()
    def close(self):
        self.cancelled.set()
        if self.thread:self.thread.join(timeout=2)
    def _work(self):
        import httpx
        factory=self.client_factory or (lambda:httpx.Client(follow_redirects=True,timeout=httpx.Timeout(20,read=10),trust_env=True))
        try:
            with factory() as client:
                for row in self.data['files']:
                    if self.cancelled.is_set():raise Cancelled()
                    target=self.folder/row['name'];partial=self.folder/(row['name']+'.partial')
                    if target.is_symlink() or partial.is_symlink():raise ValueError('Linked model file')
                    if target.is_file() and target.stat().st_size==row['size'] and digest(target)==row['sha256']:
                        self.downloaded+=row['size'];continue
                    if target.exists():target.rename(target.with_name(target.name+'.unverified-'+uuid.uuid4().hex))
                    for attempt in range(2):
                        if partial.exists() and partial.stat().st_size>=row['size']:
                            if partial.stat().st_size==row['size'] and digest(partial)==row['sha256']:break
                            partial.rename(partial.with_name(partial.name+'.rejected-'+uuid.uuid4().hex))
                        offset=partial.stat().st_size if partial.exists() else 0
                        url=f"https://huggingface.co/{self.data['repository']}/resolve/{self.data['revision']}/{row['name']}"
                        headers={'Range':f'bytes={offset}-'} if offset else {}
                        with client.stream('GET',url,headers=headers) as response:
                            response.raise_for_status()
                            if offset and response.status_code==206:
                                if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid resume response')
                            elif response.status_code==200:offset=0
                            else:raise ValueError('Invalid download response')
                            length=response.headers.get('Content-Length')
                            if length and int(length)>row['size']-offset:raise ValueError('Oversized model response')
                            with partial.open('ab' if offset else 'wb') as stream:
                                for chunk in response.iter_bytes(1024*256):
                                    if self.cancelled.is_set():raise Cancelled()
                                    offset+=len(chunk)
                                    if offset>row['size']:raise ValueError('Oversized model file')
                                    stream.write(chunk);self.downloaded+=len(chunk)
                        if offset==row['size'] and digest(partial)==row['sha256']:break
                    if partial.stat().st_size!=row['size'] or digest(partial)!=row['sha256']:raise ValueError('Model digest mismatch')
                    if self.cancelled.is_set():raise Cancelled()
                    os.replace(partial,target)
                self.state='ready' if self.available() else 'failed'
                if self.state=='ready' and os.environ.get('OPENSHORTS_DESKTOP')=='1':os.environ['WHISPER_MODEL']=str(self.folder)
        except Cancelled:self.state='cancelled'
        except (httpx.TransportError,httpx.HTTPStatusError):self.state='offline';self.error='network_unavailable'
        except (OSError,ValueError):self.state='failed';self.error='verification_or_storage_failed'

def register(engine,storage):
    import asyncio
    from fastapi import Request,HTTPException
    service=Provisioner(storage);engine.app.state.model_provisioner=service
    @engine.app.get('/api/desktop/models/whisper')
    async def status():return await asyncio.to_thread(service.status)
    @engine.app.post('/api/desktop/models/whisper/prepare')
    async def prepare(request:Request):
        body=await request.json()
        try:return await asyncio.to_thread(service.start,isinstance(body,dict) and body.get('acknowledged') is True)
        except (OSError,ValueError):raise HTTPException(400,'Confirm the download and check model storage availability')
    @engine.app.post('/api/desktop/models/whisper/cancel')
    async def cancel():return service.cancel()
    return service
