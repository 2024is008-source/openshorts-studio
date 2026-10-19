"""Load existing routes after configuring writable desktop storage."""
import os
import socket
from pathlib import Path


def serve(native=False):
    if not native:
        raise RuntimeError("The browser shell is retired. Start the native WPF application.")
    import uvicorn
    from desktop.processes import hide_child_consoles, resources
    from desktop.security import LocalAccess
    hide_child_consoles()
    import app as engine
    from desktop.projects import register
    register(engine)
    if native:
        from desktop.native_api import register as register_native
        register_native(engine)
    from desktop.storage import Storage
    storage=Storage(local=os.environ.get('OPENSHORTS_LIBRARY') or os.getcwd(),roaming=os.environ.get('OPENSHORTS_ROAMING'))
    from desktop.model_provisioning import register as register_models
    from desktop.renderer_runtime import register as register_renderer
    models=register_models(engine,storage);renderer=register_renderer(engine,storage)
    @engine.app.get('/api/desktop/capabilities')
    async def desktop_capabilities():
        import asyncio
        from desktop.hardware import capabilities
        result=await asyncio.to_thread(capabilities)
        from desktop.download_runtime import status
        result['url_download_runtime']=status()
        return result
    sock = socket.socket()
    # Windows exclusive bind prevents another process stealing/reusing this port.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    secured = LocalAccess(engine.app, os.environ['OPENSHORTS_LOCAL_TOKEN'], origin, os.getcwd())
    Path(os.environ['OPENSHORTS_READY_FILE']).write_text(str(port), 'ascii')
    try:
        uvicorn.Server(uvicorn.Config(secured, log_config=None, access_log=False,
                                      log_level='critical', timeout_graceful_shutdown=5)).run(sockets=[sock])
    finally:
        models.close()
        renderer.stop()
        sock.close()


def worker(script, arguments):
    import runpy
    import sys
    from desktop.processes import hide_child_consoles, resources
    if script == 'native-import':
        hide_child_consoles()
        from desktop.import_worker import run
        run(arguments[0])
        return
    if script == 'model-download':
        hide_child_consoles()
        from desktop.model_download import download
        download()
        return
    if script not in ('main.py', 'quality_probe.py', 'export_quality.py'):
        raise ValueError('Unknown processing worker')
    hide_child_consoles()
    sys.argv = [script, *arguments]
    runpy.run_path(str(resources() / script), run_name='__main__')
