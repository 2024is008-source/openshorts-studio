"""Windows WebView2 host, preserving the React dashboard and H.264 playback."""
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import webbrowser
import webview
from webview.menu import Menu, MenuAction, MenuSeparator
from desktop import VERSION
from desktop.credentials import CredentialStore
from desktop.processes import ProcessTree, command, environment, resources
from desktop.storage import Storage


def message(text, error=False):
    ctypes.windll.user32.MessageBoxW(None, text, 'OpenShorts', 0x10 if error else 0x40)


class InstanceLock:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b'1')
            self.file.flush()
        self.file.seek(0)

    def acquire(self):
        import msvcrt
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def close(self):
        self.file.close()


class Desktop:
    def __init__(self, storage):
        self.storage = storage
        self.vault = CredentialStore(storage.roaming)
        self.tree = self.origin = self.backend = self.renderer = self.model_download = None
        self.clean_on_close = False
        self.stopped = threading.Event()
        self.ready_event = threading.Event()
        self.lifecycle = threading.RLock()
        self.window = webview.create_window(f'OpenShorts {VERSION}',
            html='<body style="background:#111827;color:white;font:18px Segoe UI;padding:48px">Starting OpenShorts…</body>',
            width=1440, height=960, min_size=(1100,720), background_color='#111827',
            text_select=True, confirm_close=True)
        self.window.events.before_show += self.install_browser_boundary
        self.window.events.closed += self.stop

    def install_browser_boundary(self):
        # Pinned pywebview 6.2.1 adapter: synchronous native callbacks are needed;
        # its asynchronous request_sent event cannot reliably attach credentials.
        control = self.window.native.browser.webview
        self.control = control
        def navigation(sender, args):
            url = str(args.Uri)
            if url.startswith('about:') or (self.origin and url.startswith(self.origin + '/')):
                return
            args.Cancel = True
            if urlsplit(url).scheme in ('https', 'http'):
                webbrowser.open(url)
        def resource(sender, args):
            url = urlsplit(str(args.Request.Uri))
            if self.origin and f'{url.scheme}://{url.netloc}' == self.origin:
                args.Request.Headers.SetHeader('X-OpenShorts-Session', self.env['OPENSHORTS_LOCAL_TOKEN'])
            elif url.hostname in ('127.0.0.1', 'localhost', '::1') or url.scheme in ('file', 'ftp'):
                args.Response = sender.Environment.CreateWebResourceResponse(None, 403, 'Forbidden', '')
        def initialized(sender, args):
            if not args.IsSuccess:
                return self.fail(RuntimeError('Windows WebView2 could not start. Repair the WebView2 Runtime.'))
            core = control.CoreWebView2
            from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
            core.AddWebResourceRequestedFilter('*', CoreWebView2WebResourceContext.All)
            core.WebResourceRequested += resource
            def download(sender, args):
                try:
                    destination = Path(str(args.ResultFilePath))
                    needed = max(int(args.DownloadOperation.TotalBytesToReceive), 256 * 1024**2)
                    if shutil.disk_usage(destination.parent).free < needed:
                        args.Cancel = True
                        message('There is not enough free space in the selected export folder.', error=True)
                except OSError:
                    args.Cancel = True
            core.DownloadStarting += download
            self._download_callback = download
            core.ProcessFailed += lambda sender, args: self.fail(RuntimeError('The dashboard stopped. Restart OpenShorts.'))
            core.Settings.IsPasswordAutosaveEnabled = False
            core.Settings.IsGeneralAutofillEnabled = False
        control.NavigationStarting += navigation
        self._callbacks = (navigation, resource, initialized)
        if control.CoreWebView2:
            class Ready: IsSuccess = True
            initialized(control, Ready())
        else:
            control.CoreWebView2InitializationCompleted += initialized

    def menus(self):
        return [Menu('File', [MenuAction('Import video…', self.import_video),
            MenuAction('Open project folder', lambda: os.startfile(self.storage.local / 'output')),
            MenuSeparator(), MenuAction('Exit', self.window.destroy)]),
            Menu('Settings', [MenuAction('Credentials and performance…', self.settings),
                MenuAction('Clear temporary cache on exit', self.clear_cache)]),
            Menu('Help', [MenuAction('Download speech model…', self.download_model),
                MenuAction('About OpenShorts', lambda: message(f'OpenShorts {VERSION}\nLocal AI video editing\nYour projects stay on this PC.'))])]

    def import_video(self):
        if self.ready_event.is_set():
            self.window.evaluate_js("location.hash='app';setTimeout(()=>{const el=document.querySelector('input[type=file][accept*=video]');if(el)el.click();},500)")

    def start(self):
        if self.stopped.is_set(): return
        with self.lifecycle:
            if self.stopped.is_set(): return
            self._launch()
        if self.backend and not self.stopped.is_set(): self._monitor()

    def _launch(self):
        try:
            if not (resources() / 'dashboard/dist/index.html').is_file():
                raise RuntimeError('The dashboard build is missing. Build the dashboard or repair the installation.')
            self.storage.check_space()
            self.tree = ProcessTree()
            self.env = environment(self.storage, self.storage.settings(), self.vault.load())
            self.ready_file = self.storage.work / f'ready-{secrets.token_hex(16)}'
            self.env['OPENSHORTS_READY_FILE'] = str(self.ready_file)
            renderer_root = resources() / 'render-service'
            node = resources() / 'bin/node.exe'
            if not node.exists() and not getattr(sys, 'frozen', False):
                node = Path(shutil.which('node') or node)
            if (renderer_root / 'dist/server.js').is_file() and node.is_file():
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0))
                    port = probe.getsockname()[1]
                self.env.update(PORT=str(port), RENDER_HOST='127.0.0.1',
                    RENDER_SERVICE_URL=f'http://127.0.0.1:{port}',
                    OPENSHORTS_RENDER_TOKEN=secrets.token_urlsafe(48),
                    REMOTION_BUNDLE_PATH=str(resources() / 'remotion'),
                    PYTHON_EXECUTABLE=sys.executable,
                    OPENSHORTS_FROZEN='1' if getattr(sys, 'frozen', False) else '0')
                bundle = resources() / 'remotion-bundle'
                if not (bundle / 'index.html').exists() and not getattr(sys, 'frozen', False):
                    bundle = resources() / 'build/desktop-resources/remotion-bundle'
                if (bundle / 'index.html').exists():
                    self.env['REMOTION_SERVE_URL'] = str(bundle)
                chromium = resources() / 'browser/chrome-headless-shell.exe'
                if not chromium.exists() and not getattr(sys, 'frozen', False):
                    chromium = renderer_root / 'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'
                if chromium.exists():
                    self.env['REMOTION_BROWSER_EXECUTABLE'] = str(chromium)
                self.renderer = self.tree.start([str(node), str(renderer_root / 'dist/server.js')], env=self.env, cwd=str(self.storage.local))
            elif getattr(sys, 'frozen', False):
                raise RuntimeError('The installed Remotion runtime is incomplete. Repair the installation.')
            self.backend = self.tree.start(command('--backend'), env=self.env, cwd=str(self.storage.local))
        except Exception as error:
            self.fail(error)

    def _monitor(self):
        try:
            deadline = time.monotonic() + 180
            while not self.stopped.wait(.3):
                if self.backend.poll() is not None:
                    raise RuntimeError('The processing engine stopped. Restart OpenShorts.')
                if self.renderer and self.renderer.poll() is not None:
                    raise RuntimeError('The Remotion renderer stopped. Restart OpenShorts.')
                if not self.origin:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Engine startup timed out. Check that your security software permits OpenShorts.')
                    try:
                        port = int(self.ready_file.read_text('ascii'))
                        origin = f'http://127.0.0.1:{port}'
                        req = urllib.request.Request(origin + '/health', headers={'X-OpenShorts-Session': self.env['OPENSHORTS_LOCAL_TOKEN']})
                        with urllib.request.urlopen(req, timeout=.5) as response:
                            if response.status != 200: continue
                    except (OSError, ValueError):
                        continue
                    self.origin = origin
                    self.window.load_url(origin + '/#app')
                    self.ready_event.set()
                if self.model_download and self.model_download.poll() is not None:
                    success = self.model_download.returncode == 0
                    self.model_download = None
                    message('Speech model downloaded. Restart OpenShorts to use it.' if success else 'Model download failed. Check internet access and disk space, then retry.')
        except Exception as error:
            self.fail(error)

    def fail(self, error):
        self.stop()
        with (self.storage.local / 'desktop-crash.log').open('a', encoding='utf-8') as stream:
            stream.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} desktop {type(error).__name__}\n')
        message(str(error) if isinstance(error, RuntimeError) else 'OpenShorts could not start. Check disk space and Windows profile permissions.', error=True)

    def stop(self):
        self.stopped.set()
        with self.lifecycle:
            if self.tree:
                self.tree.close()
                self.tree = None
        if hasattr(self, 'ready_file'): self.ready_file.unlink(missing_ok=True)
        if self.clean_on_close:
            try: self.storage.clear_cache()
            except (OSError, ValueError): pass

    def clear_cache(self):
        self.clean_on_close = True
        message('Temporary work will be cleared on exit. Projects, source videos and models are kept.')

    def settings(self):
        from desktop.windows_settings import show_settings
        from System import Action
        self.window.native.Invoke(Action(lambda: show_settings(self)))

    def download_model(self):
        if self.model_download or not self.tree: return
        try:
            self.storage.check_space()
            self.model_download = self.tree.start(command('--worker', 'model-download'), env=self.env, cwd=str(self.storage.local))
            message('Downloading the speech model (about 500 MB). You can continue editing. Closing stops the download; retry to resume.')
        except (OSError, ValueError):
            message('Unable to start download. Check free disk space.', error=True)


def configure_webview():
    webview.settings.update(ALLOW_DOWNLOADS=True, ALLOW_FILE_URLS=False,
        OPEN_EXTERNAL_LINKS_IN_BROWSER=True, OPEN_DEVTOOLS_IN_DEBUG=False)
    if (resources() / 'webview2').exists():
        webview.settings['WEBVIEW2_RUNTIME_PATH'] = str(resources() / 'webview2')
    logging.getLogger('pywebview').disabled = True


def main():
    storage = Storage()
    lock = InstanceLock(storage.roaming / 'desktop.lock')
    if not lock.acquire():
        message('OpenShorts is already running for this Windows user.')
        lock.close()
        return 0
    configure_webview()
    desktop = Desktop(storage)
    def launch():
        try: storage.check_space()
        except OSError:
            message('Choose a folder with at least 2 GB of free space for your video library.')
            selected = desktop.window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:
                desktop.window.destroy()
                return
            library = Path(selected[0]) / 'OpenShorts Library'
            (storage.roaming / 'library-location.json').write_text(json.dumps(str(library)), 'utf-8')
            desktop.storage = Storage(local=library, roaming=storage.roaming)
        desktop.start()
    try:
        webview.start(launch, gui='edgechromium', private_mode=True,
            storage_path=str(storage.cache / 'webview'), menu=desktop.menus(), icon=str(resources() / 'assets/desktop.ico'))
    except Exception as error:
        desktop.fail(error)
        return 1
    finally:
        desktop.stop()
        lock.close()
    return 0
