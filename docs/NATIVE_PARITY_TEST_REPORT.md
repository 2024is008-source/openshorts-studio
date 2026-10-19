# TASK-DESKTOP-003 verification

Executed on 2026-10-16, Windows x64, .NET SDK 10.0.401, Python 3.11.9. The native WPF architecture, authenticated owned Python worker, shared caption renderer and FFmpeg pipeline were retained.

| Check | Result |
| --- | --- |
| Five-project .NET solution / XAML | Build succeeded, zero warnings or errors |
| Complete Python suite, `python -X utf8 -m pytest tests -q --tb=short` | **1,582 passed**, 75 existing deprecation warnings, 409.73 seconds |
| Native C# tests with `OPENSHORTS_TEST_ROOT` | **18 passed**; actual worker startup/restart, authentication, process-tree ownership, DPAPI and boundary checks |
| Focused timeline project tests | 28 passed, including appearance validation, word alignment, overlap rejection and normalization round-trip |
| Focused saved editor API tests | 9 passed |
| Native WPF acceptance | Passed with a real synthetic H.264/AAC project and isolated library |

Native acceptance exercises the actual view-model commands and existing engine routes: invalid timestamp protection, whole-gesture split/trim undo and redo, reorder/delete history, phrase edits, aligned-word timing/emphasis persistence, custom caption appearance, external revision conflict rejection/reload, real 600-bin waveform, two-second autosave, automatic rendered preview, manual preview/final, quality-gated MP4 export and restart recovery. LibVLC produced one real video output; seeking to two seconds reached approximately 2.15 seconds after another half-second of playback.

Generated evidence: `build/wpf-parity-verified/result.json`, `wpf-editor.png`, `wpf-shell.png`, `native-export.mp4` and isolated project/quality files. WPF bitmap capture omits the native VLC child-window pixels; playback is verified separately through video output and timestamps. No live Gemini request, model download, subscription or paid service was used.

The expanded smoke exposed and corrected a Windows readiness-file sharing race and an intermediate-state split undo bug. Caption validation tests also verify that normalized aligned-word decisions can be saved/reloaded repeatedly without changing their schema.

## Acceptance limits

- Mouse trim/reorder logic is connected to the native surface and its view-model mutation/history path is exercised. Broader manual pointer, keyboard focus, accessibility, multiple-monitor DPI and long-recording usability qualification remains.
- Source playback traverses cuts on the existing 200 ms UI clock. Seeking is millisecond-based and decoder-dependent. Preview/final rendering is the authority for assembled output; no frame-perfect playback claim is made.
- Scene markers sample at 2 fps and may miss rapid cuts. They are invalidated with waveform data after cut changes.
- Auto-preview is an optional asynchronous engine-rendered update, not instant ASS compositing in WPF. Templates retain their own caption design.
- Existing bounds remain 12 output segments / 180 assembled seconds. Visible-range drawing and recycled data grids avoid creating visual controls for every offscreen item; no unbounded timeline performance benchmark is claimed.
- Word timing is available only when original alignment exists. Rewritten phrases retain phrase timing. Emphasis uses the existing caption renderer animation behavior.
- Revision conflicts preserve local edits in memory and pause saving. Explicit reload asks before discarding them; automatic merging and crash recovery of an unsaved conflict are not implemented.
- Template content/director authoring, independent audio mixing and browser-specific effects remain gaps listed in the parity matrix. Installer, subscription and release qualification remain unfinished.

See `NATIVE_PARITY_MATRIX.md` and `NATIVE_EDITOR_GUIDE.md` for implemented behavior and remaining scope. Historical TASK-DESKTOP-002 results are retained in `WPF_TEST_REPORT.md`.
