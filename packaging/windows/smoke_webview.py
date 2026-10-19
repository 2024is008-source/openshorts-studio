"""Live Windows host check with isolated storage, no credentials and no API billing."""
import json
from pathlib import Path
import sys
import tempfile
import time
import urllib.request
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import webview
from desktop.windows_shell import Desktop, configure_webview
from desktop.storage import Storage

(ROOT / 'build').mkdir(exist_ok=True)
temporary = tempfile.TemporaryDirectory(prefix='webview-smoke-', dir=ROOT / 'build')
root = Path(temporary.name)
configure_webview()
desktop = Desktop(Storage(root / 'local', root / 'roaming'))
desktop.window.confirm_close = False
result = {'success': False}
desktop.fail = lambda error: (result.update(error=str(error)), desktop.window.destroy())


def inspect():
    try:
        if not desktop.ready_event.wait(150):
            raise RuntimeError('Engine startup timeout')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            data = desktop.window.evaluate_js("({text:document.body.innerText.slice(0,300),fileInput:!!document.querySelector('input[type=file]'),h264:document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')})")
            if data and data.get('fileInput'): break
            time.sleep(.3)
        assert data and data['fileInput'], data
        assert data['h264'] in ('probably','maybe'), data
        try:
            urllib.request.urlopen(desktop.origin + '/api/config', timeout=5)
            raise AssertionError('Local API is unguarded')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        # Exercise authenticated browser fetch, using the native header interceptor.
        desktop.window.evaluate_js("fetch('/api/config').then(r=>window.__smokeConfig={status:r.status}).catch(()=>window.__smokeConfig={status:0});true")
        config = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            config = desktop.window.evaluate_js('window.__smokeConfig || null')
            if config: break
            time.sleep(.1)
        assert config['status'] == 200, config
        result.update(success=True, dashboard=data, authenticated_config=config)
    except Exception as error:
        result.update(error=str(error))
    finally:
        desktop.window.destroy()


import threading
def launch():
    threading.Thread(target=inspect, daemon=True).start()
    desktop.start()
webview.start(launch, gui='edgechromium', private_mode=True,
    storage_path=str(root / 'browser'), menu=desktop.menus(),
    icon=str(ROOT / 'assets/desktop.ico'))
desktop.stop()
temporary.cleanup()
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['success'] else 1)
