"""Optional Remotion lifecycle owned by the native engine's Windows Job Object."""
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time

class Renderer:
    def __init__(self,engine,storage):
        self.engine=engine;self.storage=storage;self.tree=None;self.process=None;self.url=None;self.token=None
        self.lock=threading.RLock();self.state='unavailable';self.error=None;self.browser_checked=False
    def paths(self):
        from desktop.processes import resources
        root=resources();node=root/'bin/node.exe'
        if not node.is_file() and not getattr(sys,'frozen',False):node=Path(shutil.which('node') or root/'missing-node')
        service=root/'render-service/dist/server.js';bundle=root/'remotion-bundle'
        if not (bundle/'index.html').exists() and not getattr(sys,'frozen',False):bundle=root/'build/desktop-resources/remotion-bundle'
        browser=root/'browser/chrome-headless-shell.exe'
        if not browser.exists() and not getattr(sys,'frozen',False):browser=root/'render-service/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'
        installed=node.is_file() and service.is_file() and (root/'render-service/node_modules/@remotion/renderer').is_dir()
        configured=installed and browser.is_file() and ((bundle/'index.html').is_file() or (not getattr(sys,'frozen',False) and (root/'remotion/src/index.ts').is_file()))
        return dict(root=root,node=node,service=service,bundle=bundle,browser=browser,installed=installed,configured=configured)
    def health(self):
        if not self.browser_checked or not self.process or self.process.poll() is not None or not self.url:return False
        try:
            import httpx
            with httpx.Client(timeout=1,trust_env=False,follow_redirects=False) as client:
                r=client.get(self.url+'/health',headers={'X-OpenShorts-Render':self.token})
                return r.status_code==200 and r.json().get('renderer')=='remotion'
        except Exception:return False
    def status(self):
        if self.process and self.process.poll() is not None:
            self.error='renderer_exited';self.stop()
        paths=self.paths();running=bool(self.process and self.process.poll() is None);ready=self.health()
        state='ready' if ready else 'running' if running else 'configured' if paths['configured'] else 'installed' if paths['installed'] else 'unavailable'
        return dict(installed=paths['installed'],configured=paths['configured'],running=running,ready=ready,
            unavailable=not ready,state=state,error_code=self.error,optional=True,
            owned_pid=self.process.pid if running else None,engine_pid=os.getpid())
    def start(self):
        from desktop.processes import ProcessTree
        with self.lock:
            if self.health():return self.status()
            self.stop();paths=self.paths()
            if not paths['configured']:self.error='renderer_resources_missing';return self.status()
            try:
                probe=subprocess.run([str(paths['browser']),'--version'],capture_output=True,timeout=8,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                if probe.returncode:raise OSError('Browser preflight failed')
                self.browser_checked=True
            except (OSError,subprocess.SubprocessError):
                self.error='renderer_browser_unavailable';return self.status()
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            token=secrets.token_urlsafe(48);url=f'http://127.0.0.1:{port}'
            env=dict(os.environ);env.update(PORT=str(port),RENDER_HOST='127.0.0.1',OPENSHORTS_RENDER_TOKEN=token,
                OUTPUT_DIR=str(self.storage.local/'output'),PYTHON_EXECUTABLE=sys.executable,
                OPENSHORTS_FROZEN='1' if getattr(sys,'frozen',False) else '0',
                REMOTION_BUNDLE_PATH=str(paths['root']/'remotion'),REMOTION_BROWSER_EXECUTABLE=str(paths['browser']))
            if (paths['bundle']/'index.html').is_file():env['REMOTION_SERVE_URL']=str(paths['bundle'])
            self.tree=ProcessTree();self.token=token;self.url=url;self.error=None
            try:
                self.process=self.tree.start([str(paths['node']),str(paths['service'])],env=env,cwd=str(self.storage.local))
                deadline=time.monotonic()+45
                while time.monotonic()<deadline and self.process.poll() is None:
                    if self.health():
                        self.engine.RENDER_SERVICE_URL=url;os.environ['OPENSHORTS_RENDER_TOKEN']=token
                        return self.status()
                    time.sleep(.15)
                self.error='renderer_startup_failed';self.stop();return self.status()
            except OSError:
                self.error='renderer_startup_failed';self.stop();return self.status()
    def stop(self):
        with self.lock:
            if self.tree:self.tree.close()
            self.tree=None;self.process=None;self.url=None;self.token=None
            self.browser_checked=False
            os.environ.pop('OPENSHORTS_RENDER_TOKEN',None)
            self.engine.RENDER_SERVICE_URL='http://127.0.0.1:1'
    def restart(self):
        with self.lock:self.stop();return self.start()

def register(engine,storage):
    import asyncio
    service=Renderer(engine,storage);engine.app.state.desktop_renderer=service
    @engine.app.get('/api/desktop/renderer')
    async def status():return await asyncio.to_thread(service.status)
    @engine.app.post('/api/desktop/renderer/start')
    async def start():return await asyncio.to_thread(service.start)
    @engine.app.post('/api/desktop/renderer/restart')
    async def restart():return await asyncio.to_thread(service.restart)
    @engine.app.post('/api/desktop/renderer/stop')
    async def stop():
        await asyncio.to_thread(service.stop);return service.status()
    return service
