# OpenShorts native WPF development and release

TASK-DESKTOP-002 is an incremental native migration. The C# application uses
real WPF controls, CommunityToolkit.Mvvm, dependency injection, async commands,
structured privacy-conscious logging and LibVLC playback. It does not load the
React dashboard or WebView2. Legacy frontend fixtures are retained only for regression compatibility.
The existing Python backend and supported renderer remain desktop runtime modules.

## Run the built native application

On this development machine, double-click `start_wpf.vbs`, or run
`native\OpenShorts.Desktop\bin\Debug\net10.0-windows\OpenShorts.Desktop.exe`.
This is a development build requiring the installed .NET Desktop Runtime and
the existing Python environment. It is not a customer installer.

The app discovers the repository when running from its build folder. An explicit
development launch accepts:

```powershell
.\native\OpenShorts.Desktop\bin\Debug\net10.0-windows\OpenShorts.Desktop.exe --source-root 'D:\path\to\OpenShorts-Gemini-NoDocker'
```

Use `--library 'D:\Video Library\OpenShorts'` to select a library for that launch.
Without it, the app reads the existing AppData library location. On insufficient
space it offers a native folder picker. Existing settings, projects and Gemini
DPAPI files remain compatible with the prior shell. WPF and the prior shell use
the same instance lock and should not run together against the same user state.

## Build from source

Requirements on the developer machine: Windows x64, .NET SDK 10.0.401 (or later
10.0.4xx patch permitted by global.json), the existing Python 3.11 venv and
FFmpeg/FFprobe on PATH. No Node build is required for native WPF startup.

```powershell
dotnet restore native/OpenShorts.sln --packages .nuget/packages --locked-mode
dotnet build native/OpenShorts.sln --no-restore
```

NuGet locks are committed for all five projects. The first restore downloads
the native LibVLC runtime and may take several minutes. VideoLAN.LibVLC.Windows
3.0.21 provides the x64 native DLLs/plugins; LibVLCSharp.WPF 3.10.2 provides the
native WPF playback host. Playback supports H.264 and millisecond seeking;
frame-perfect editing/export is provided by Python/FFmpeg, not promised by VLC.

## Native workflows

- **Home / Projects:** start or restart the engine, list completed local jobs,
  reopen a project and select a result clip. Restart stops owned processing;
  saved engine manifests/projects survive. The app does not silently restart
  an engine in the middle of a render.
- **AI Clipper:** import via native picker or Windows file drop, confirm rights,
  choose an optional engine template and submit the actual multipart processing
  API. Display real worker log stages; keep progress indeterminate when no
  measured percentage exists. Cancel an active/queued clipping job without
  deleting saved files. Live Gemini/Whisper still run in Python.
- **Video Editor:** open a clip from AI Clipper results. A retained source plays
  in source time; rendered output plays in assembled time. The timeline overview
  maps video, captions and linked audio onto assembled time. Click it to seek.
  Edit source start/end ranges, split at the playhead, reorder/remove ranges,
  edit caption text/timing, choose crop/contain/preserve with focal points, and
  select a template/caption look. Save uses backend revision checks. Invalid
  numeric edits prevent saves until corrected. Original audio follows the video
  ranges; there is no separate freeform audio mixer in this increment.
- **Render preview / Render final:** both call the existing saved-editor render
  APIs and await their real progress and validation. Final render updates the
  clip's delivered media. **Export MP4** copies the selected delivered file via
  the protected API to a native save destination using an atomic partial file.
  Save a draft and render final before exporting edits.
- **Templates:** use the existing Python catalog. Native selection applies to
  generation or to an opened draft on save/render. Full custom overlay-content
  authoring and browser Remotion effects remain in the previous interface.
- **Settings:** existing DPAPI-compatible Gemini key, bounded encoder/preset
  choices, one pipeline job, live encoder/CUDA capability probe. Settings/key
  changes take effect after an engine restart. An untouched blank password box
  preserves the existing loaded key; the explicit remove action deletes it.
- **Account:** shows the actual local-only state. Trusted subscription contracts
  are defined in Core; no fake login, payment, trial or entitlement controls are
  presented when there is no configured authority service.

## Storage and communication

Settings/credentials and the shared lock live under `%APPDATA%\OpenShorts`.
The selected library contains output, uploads, temp, models and `logs\wpf.jsonl`.
Logs rotate at 1 MB and contain event IDs, levels and exception class names,
not paths, API payloads or secrets. Engine startup ignores repository `.env`
and inherited production secrets. WPF never embeds a production Gemini key.

WPF uses the existing authenticated loopback HTTP API. Each worker launch gets
a fresh random token, exact Host/Origin guards and OS-assigned loopback port.
The native backend mounts no dashboard. A readiness file contains only a port.
C# assigns a suspended Python process to a kill-on-close Windows Job Object
before resuming it; Python pipeline workers use nested jobs for cancellation.
No shell-interpolated process command is used. Media paths from the worker are
checked against the library, including link rejection. Requests and JSON replies
have protocol, size and identity checks. Redirects/proxies are disabled.

## Tests

```powershell
$env:OPENSHORTS_TEST_ROOT = (Get-Location).Path
dotnet test native/OpenShorts.Tests/OpenShorts.Tests.csproj --no-restore
.venv\Scripts\python.exe -X utf8 -m pytest tests -q
```

Set OPENSHORTS_TEST_ROOT to execute the Python/.NET interoperability and live
worker tests. Without it those two integration tests return without executing
their source-dependent steps; the reported results in WPF_TEST_REPORT.md used it.

An isolated live WPF/editor smoke test creates synthetic local footage and does
not use a Gemini key or call paid services:

```powershell
.\native\OpenShorts.Desktop\bin\Debug\net10.0-windows\OpenShorts.Desktop.exe --source-root "$PWD" --library "$PWD\build\wpf-smoke-new\library" --smoke-test "$PWD\build\wpf-smoke-new"
```

Use a fresh smoke directory each time to avoid deliberately changing retained
source identities in an existing saved project. Inspect `result.json`, the
exported MP4, the source fixture and `wpf-shell.png`. WPF bitmap screenshots do
not capture native VLC child-window pixels; the separate decoding/seek assertions
verify real playback. The smoke also saves/renders/restores a real local draft.

## Customer publication and installer

`build_wpf.ps1` / `packaging/wpf/build.py` publish win-x64 self-contained WPF and
freeze a separate windowless `OpenShorts.Engine.exe`. The planned layout is:

```text
dist/wpf/OpenShorts.Desktop.exe       # includes .NET Desktop runtime
dist/wpf/libvlc/win-x64/              # playback DLLs/plugins
dist/wpf/engine/OpenShorts.Engine.exe # Python engine/runtime/dependencies
dist/wpf/engine/_internal/bin/       # FFmpeg and FFprobe
dist/wpf/licenses/                   # runtime inventories/notices
```

Release builds are intentionally blocked until the existing
`packaging/windows/FFMPEG-SOURCE-OFFER.txt` is complete. They additionally require
`packaging/wpf/THIRD-PARTY-NOTICES.txt` for the selected .NET, NuGet, LibVLC/VLC
plugins, Python/model/font dependencies, notices, source availability and
redistribution terms. LibVLC packages declare LGPL-2.1-or-later; verify plugin
and corresponding-source obligations for the actual selected binary set. Do
not use an empty placeholder document to pass these checks. Complete publisher
inputs before bundling any third-party binaries for distribution.

After those records are complete:

```powershell
.\build_wpf.ps1
.\build_wpf.ps1 -Installer -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

The installer configuration preserves the stable app identity, user data and
prior shell files, creates Start menu/optional desktop shortcuts and registers
uninstall. Its minimum OS build is set to Windows build 19045; OS/runtime
qualification is still required before release. Large CUDA bundles may produce adjacent Inno disk slices; ship them
with the EXE. Code signing and secure HTTPS upgrade distribution follow
DESKTOP_RELEASE.md. Do not remove the previous interface until the remaining
parity and clean-machine checks pass.

No self-contained customer publication or installer was generated in this task;
the verified artifact is the framework-dependent development WPF application.
