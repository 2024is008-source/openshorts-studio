# TASK-DESKTOP-001: repository assessment and decision

Assessment recorded before implementation, 2026-10-16.

The existing interface is React 18/Vite 4 (`dashboard/src`), with a Remotion
player, timeline editor, uploads/drop zone, progress polling and download links.
It is not a server-rendered application. `app.py` is the FastAPI entry point;
it runs `main.py` as a Python subprocess and exposes `/api`, `/videos`,
`/thumbnails`, `/gallery` and MCP routes. `timeline_api.py` and the existing
FFmpeg render modules implement editing. Gemini uses google-genai and BYOK
headers/environment; optional cloud billing already lives in `cloud/`.

`render-service` is a separate Express/Remotion service. It currently bundles
the Remotion sources at startup and uses Chromium and Node, independently of
the Python FFmpeg engine. Both paths must remain available. `render_runtime.py`
and `ffmpeg_utils.py` already implement bounded rendering, actual NVENC encode
probing, cancellation, validation and CPU fallback. Reuse these capabilities.
YOLO weights exist at the root; Whisper and some detection assets can download
on demand. Fonts and video template definitions are repository assets.

Current launchers require a venv, Node/npm, terminal windows and a browser.
There is no desktop packaging configuration. Upload/output/log paths are
relative to the working directory. Existing retention deletes old projects;
that is unsuitable for durable desktop work. Frozen workers cannot treat
`sys.executable` as a normal Python interpreter.

## Framework evaluation

Tauri can embed the dashboard unchanged and has good Windows installers, but
adds Rust, a Python sidecar build, IPC integration and a second lifecycle layer.
PySide6 with native widgets alone would require a costly dashboard rewrite.
The initial choice was PySide6 with QtWebEngine, preserving the dashboard and
keeping process/credential/storage integration in Python. A live codec probe
then returned an empty `canPlayType` result for H.264 with PySide6 6.10.2. That
would break the existing editor. The Qt implementation was removed.

Final choice: **pywebview 6.2.1 / native WinForms / Windows WebView2**, with the
same Python backend supervisor, PyInstaller onedir and Inno Setup. The actual
Windows WebView2 smoke test returned `probably` for H.264, displayed the existing
dashboard and passed authenticated browser fetches. This additional framework
option preserves the dashboard without Rust or a UI rewrite and avoids shipping
an incompatible Qt codec build. Release builds include the official WebView2
Fixed Version runtime. Python/.NET interop and WebView2 DLLs come from pywebview.

## Intended boundaries

The GUI owns one Windows kill-on-close Job Object and all processing children.
A suspended backend is assigned before execution; FFmpeg/Node/Chromium inherit
the job. A per-user lock prevents duplicate instances. Backend binds a socket to
127.0.0.1 with an OS-assigned port. Every HTTP request, including media, requires
a random per-launch secret inserted by a native WebView2 request interceptor.
Host and Origin are checked as additional DNS-rebinding/CSRF defenses. The
desktop session token is never URL data. The separate renderer has a different
secret, HTTP header authentication and a private capability URL for owned
Chromium's source media reads; it is not the desktop session token.
External navigation is handled outside the privileged page.

Read-only resources stay with binaries. Settings and DPAPI-encrypted credentials
live under roaming AppData/OpenShorts. Projects, uploads, model caches, temporary
work and logs default to LocalAppData/OpenShorts. On insufficient disk space the
user can select another library drive; only its path is saved in AppData. The
browser profile is private and API keys typed into dashboard fields last for the
session. User exports use native save
dialogs. Automatic desktop project retention is disabled. Cache deletion never
touches projects, uploads or models, refuses links, and is restricted to idle work.

Subscription integration is a provider protocol only: trusted remote authority
must decide entitlements, activation, trial and offline grace. BYOK remains
usable locally; there is no local paid-license verifier or payment simulation.

API references: https://pywebview.flowrl.com/api/ and
https://pyinstaller.org/en/stable/runtime-information.html. The pinned pywebview
native adapter is isolated in `desktop/windows_shell.py`; its public
`request_sent` event is asynchronous in 6.2.1, so native synchronous WebView2
callbacks attach headers before requests leave the browser. Do not upgrade the
adapter without rerunning the live smoke test.
