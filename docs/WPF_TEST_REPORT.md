# TASK-DESKTOP-002: results and remaining parity work

Date: 2026-10-16. Host: Windows x64, .NET SDK 10.0.401/runtime 10.0.12,
Python 3.11.9, existing FFmpeg 9.0 and NVIDIA GeForce RTX 2050.

## Verified

| Check | Executed result |
| --- | --- |
| Five-project C# solution and WPF XAML build | Success, zero warnings/errors |
| Native C# tests with OPENSHORTS_TEST_ROOT set | 18 passed; actual Python startup/restart, token rotation, unauthenticated/foreign-Origin rejection, Unicode/unsafe route validation, DPAPI encryption and Python/.NET interoperability, cross-instance locking, path validation, actual child/grandchild kill-on-close |
| Full Python suite with `-X utf8` | 1,572 passed, 75 warnings, 416.27 seconds |
| Additional native cancellation test run | 4 passed, including a real pipeline process stopped through the cancellation API while saved files remain |
| Focused desktop + smart-reframe run | 52 passed; the previous 120-versus-104 failure is fixed |
| Real native WPF/editor smoke | Passed with the source Python worker and isolated library |
| H.264 playback | LibVLC produced a real video output; synthetic H.264/AAC media played and seeking reached about 2.4 s after a 2 s seek plus 0.5 s playback |
| Local project restore | A real metadata/source fixture was recovered across engine restarts and opened through native commands |
| Native editor actions | Source range trim, caption correction and contain crop saved with revision checks; graphical video/caption/linked-audio overview is native WPF |
| Preview/final and MP4 export | Native commands called real Python FFmpeg rendering, captions and export quality checks. Exported 320×180 H.264/AAC, 3 s MP4 was accepted as PASS |
| Draft restart recovery | Saved contain crop and editor project survived worker restart |
| Local hardware capability probe | FFmpeg/FFprobe/libx264 initialized; NVENC encode probe succeeded; Torch CUDA available, RTX 2050 detected, CTranslate2 reports one CUDA device |
| Existing CPU fallback behavior | Full Python suite includes existing fallback/quality/resource-bound tests; algorithms retained |
| Release build preflight | Correctly blocked on the existing FFmpeg corresponding-source/distribution record |

Live smoke evidence is under `build/wpf-verified` (ignored generated files):
`result.json`, `wpf-shell.png`, `native-export.mp4`, a synthetic source, the saved
project and its quality report. The screenshot covers the actual native WPF
controls; native VLC child-window pixels are not included in WPF's bitmap
capture, so video decoding is checked separately using real video output/time.
The smoke test does not invoke Gemini, Whisper downloads, account login or
paid services. It exercises the native commands used by the actual UI.

The full Python run predates the final additional real pipeline cancellation
test, which passed separately. Do not add the focused runs to the full-suite
count or claim that they were separate new tests each time.

## Reframing regression investigation

On an aspect change the legacy path rebuilt its camera/tracker, then always
forced GENERAL layout. For a narrow portrait raster, GENERAL fitted the source
over a dimmed blurred background. Its exposed pixels became `120 - 15.3 = 104`
after uint8 conversion, explaining the assertion exactly. The fix keeps the
freshly rebuilt TRACK crop for portrait/square rasters and chooses GENERAL for
landscape context. It does not reuse coordinates from the old raster or remove
the intended background treatment from GENERAL itself. The original assertion
was preserved and now passes; no expected values were weakened.

## Not yet qualified / intentionally retained old interface

- Live Gemini/Whisper → AI clip generation through the native UI with real user
  credentials has not been executed. The actual multipart API and progress/
  cancellation flow are connected; tests/smoke do not substitute a fake AI job.
- Native template selection is wired to existing definitions. Full template
  content/headline authoring, waveform/scene tools, advanced per-scene direction,
  independent music/audio mixing, browser Remotion effects and all the previous
  web editor's keyboard/undo interactions are not at full native parity yet.
- The native timeline has editable ordered video ranges, caption timing/text,
  a linked original-audio lane and a graphical assembled-time overview/seek.
  It is not yet a freeform multi-video compositor or independent audio editor.
- LibVLC seeking is millisecond-based and decoder/keyframe dependent. No claim
  of frame-perfect interactive playback or frame stepping is made.
- Native pipeline cancellation is available once upload returns its job ID;
  initial transfer/startup operations do not show a misleading cancel action.
  Editor cancellation uses the existing cooperative saved-editor route. Closing
  the app always terminates the owned engine process tree.
- GPU capability is demonstrated on this host. A complete CPU/GPU codec/driver
  export matrix and deliberately induced real GPU-failure tests remain to be
  qualified. A successful capability probe alone is not an export benchmark.
- Native file/save dialogs and file-drop handlers are implemented. Interactive
  drag/drop, cancellation of Windows dialogs, accessibility, multiple-monitor
  DPI, all layout sizes and long/Unicode paths need broader manual acceptance.
- New WPF and old Python shells remain in source with the shared instance lock.
  Neither the dashboard nor the prior launcher has been removed. Full migration
  completion requires the feature-parity acceptance matrix, not just startup.
- Frozen WPF-specific Python deployment, self-contained win-x64 distribution,
  Authenticode signing, installation/upgrades/uninstall and clean-machine use
  have not been executed. The existing FFmpeg licensing blocker is preserved;
  new LibVLC/.NET/model distribution notices also require completion.
- The Account page accurately reports local-only operation. No fake paid
  entitlements or login/payment actions are implemented. Contracts remain for
  a trusted remote authority.

No production-readiness claim, self-contained release or installer claim is
made. No `OpenShorts-Setup.exe` was generated by TASK-DESKTOP-002.

## Changed-file summary

| Area | Changes |
| --- | --- |
| `native/OpenShorts.sln`, global.json, project/lock files | C#/.NET 10 WPF solution with Core, Infrastructure, EngineBridge, Desktop and Tests |
| Core | UI/engine/storage/process contracts and trusted subscription seam |
| Infrastructure | DPAPI-compatible store, bounded settings, shared instance lock, privacy-conscious rotating JSON logs and suspended Job Object process launcher |
| EngineBridge | Authenticated loopback transport, streaming import/export, bounded/validated JSON, safe routes, startup/restart and ownership |
| Desktop | Seven native screens, dark theme, MVVM commands, LibVLC video, native dialogs/drop import, saved editor controls, custom multitrack timeline, actual export and isolated smoke harness |
| `desktop/native_api.py`, `native_engine_entry.py` | Native bootstrap, media/template/cancellation routes and windowless frozen-engine entry |
| `desktop/backend.py`, `desktop_entry.py` | Add native mode without dashboard mounting; previous mode unchanged |
| `desktop/processes.py`, `app.py` | Reuse tested process ownership for individual cancelable pipelines; retain captured progress and saved files |
| `main.py` | Focused portrait aspect-change regression correction |
| `tests/test_native_desktop.py` | Native authorization/path/cancellation tests, including real process cancellation |
| `build_wpf.ps1`, `packaging/wpf/` | License-gated self-contained/frozen-engine release pipeline and Inno installer configuration |
| `start_wpf.vbs`, `.gitignore`, docs | Windowless development launcher, generated-file exclusions, architecture/build/verification guides |
