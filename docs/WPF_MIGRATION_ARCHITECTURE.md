# TASK-DESKTOP-002: migration architecture

Recorded before native UI implementation, 2026-10-16.

## Inspected dependencies

The current desktop shell is `desktop/windows_shell.py` (pywebview/WinForms/
WebView2). It starts the FastAPI backend and optional Remotion service. The
React/Vite dashboard implements editor controls, but algorithms live in Python:
`main.py`, `timeline_api.py`, `timeline_project.py`, `timeline_render.py`,
`caption_renderer.py`, `video_templates.py`, `ffmpeg_utils.py`, `render_runtime.py`
and the Gemini/Whisper/reframing modules. WPF must call those algorithms rather
than replace them. Existing editor routes have revision checks, validation,
saved drafts, progress, cancellation and validated export publication.

`desktop/projects.py` provides a durable local library. `desktop/storage.py`
separates AppData settings from library/temp/models. `desktop/credentials.py`
uses current-user DPAPI without custom entropy; .NET ProtectedData can read the
same ciphertext. `desktop/processes.py` suspends children before assignment to
a kill-on-close Windows Job Object. `desktop/security.py` protects ALL local
HTTP routes with a launch token, exact Host, Origin and loopback checks.
These boundaries and their tests must remain.

## Solution boundaries

- OpenShorts.Core: contracts, project/clip/settings models, no UI dependencies.
- OpenShorts.EngineBridge: async authenticated HTTP transport, worker startup,
  response bounds, protocol/path validation, recovery and process ownership.
- OpenShorts.Infrastructure: Windows process/Job Object APIs, DPAPI-compatible
  credentials, atomic settings, single-instance lock, local library locations.
- OpenShorts.Desktop: WPF, CommunityToolkit.Mvvm, dependency injection,
  native dialogs, LibVLCSharp playback, bound timeline/caption/crop/template
  controls. No embedded web dashboard or WebView2.
- OpenShorts.Tests: protocol, storage, process and integration coverage.

Use the existing protected HTTP API as the local IPC mechanism permitted by
the task. It already has security/regression coverage; adding a named-pipe RPC
proxy would duplicate validation and complicate streaming uploads/downloads.
Use an OS-assigned loopback port, random 384-bit launch token, inherited private
environment and an unpredictable per-launch readiness file inside user storage.
Never put secrets in command lines, URLs or structured logs. Native startup
does not mount dashboard assets. The C# supervisor assigns Python to a Windows
Job Object before resuming it. All Python/FFmpeg descendants inherit ownership.
Pipeline cancellation gets an additional nested job per main.py worker so it
can terminate that pipeline without killing unrelated saved editor work.

The existing backend still owns schema, timeline revisions, export quality,
media path authorization, Gemini credentials and entitlement decisions. Native
UI data never becomes shell command text. LibVLC plays validated local media
paths, while network media downloads go through the authenticated bridge.
LibVLC is a proven H.264 component with millisecond time seeking; exact frame
delivery remains the Python/FFmpeg engine's responsibility. Do not call WPF
MediaElement frame accurate, and do not claim LibVLC frame-perfect seeking.

## Incremental delivery and regression risks

1. Build and run native navigation and secure worker startup first.
2. Connect import, processing progress/cancel, project restore and native preview.
3. Connect timeline segment editing, captions, crop, templates and export to
   existing editor routes. Preserve revisions and report server errors visibly.
4. Add release scripts only behind the existing FFmpeg/source licensing gate.
5. Keep the complete prior Python shell/frontend until a credentialed parity
   matrix and clean-machine installer testing pass.

Risks: WPF/LibVLC native airspace and DLL deployment; arbitrary/obsolete media
paths; canceled uploads or queued pipelines; startup/shutdown races; stale
editor revisions; source time versus assembled timeline time; same-user local
process access (outside the existing trust boundary); AppData compatibility;
transitive model/runtime licenses; no paid entitlements granted locally.
Crashes may restart a job from its existing resume manifest, not an exact frame.

The 120-versus-104 smart-reframe regression must be investigated with UTF-8
tests. Preserve other working algorithm behavior and add a focused regression
test for any fix. Do not hide failing tests or weaken expected pixel assertions.

Reference APIs: https://learn.microsoft.com/en-us/dotnet/api/system.io.pipes.namedpipeserverstream?view=net-10.0
and https://docs.videolan.me/libvlcsharp/api/LibVLCSharp.Shared.MediaPlayer.html.
