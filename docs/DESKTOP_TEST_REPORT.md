# TASK-DESKTOP-001 functionality report

Test host: Windows x64, Python 3.11.9, Node 24.18.0, existing Gyan FFmpeg 9.0,
installed Windows WebView2 Runtime. Report date: 2026-10-16.

## Executed verification

| Check | Result |
| --- | --- |
| Desktop security/storage/process tests | 10 passed, including DPAPI ciphertext roundtrip, token/Host/Origin guards for API and media, insufficient disk rejection, cache preservation, environment secret isolation, frozen worker command dispatch, local project state/restore/traversal rejection, duplicate-instance file lock, and a real grandchild killed on Job Object close |
| Live Windows WebView2 shell | Passed: real dashboard visible, file input present, H.264 codec reported `probably`, native header interceptor enabled authenticated browser `/api/config` with 200, direct unauthenticated request returned 403, isolated processing tree closed |
| Initial QtWebEngine experiment | Dashboard loaded, but H.264 probe returned empty. Rejected and removed from implementation |
| Dashboard production build | Passed; existing warnings for unset analytics placeholders, old Browserslist data and large chunks |
| Dashboard JavaScript tests | 31 passed |
| Remotion TypeScript build | Passed |
| Remotion JavaScript/TypeScript tests | 20 passed outside sandbox; includes real full-HD H.264/AAC export, export validation, bounds and cancellation |
| Full Python regression run | 1,561 passed, 6 failed in 485.76 seconds, before the two added project/instance tests |
| UTF-8 targeted regression rerun | 7 passed, 1 failed; all five encoding-related failures passed with `-X utf8` |
| Python syntax compilation | Desktop modules and packaging scripts compiled |
| Release packaging attempt | Stopped by missing FFmpeg corresponding-source/distribution record; no frozen EXE or installer generated |

The one reproducible non-encoding regression failure is
`tests/test_smart_reframe.py::test_legacy_fallback_adapts_to_resolution_and_aspect_changes`:
the third synthetic frame is 104 instead of expected 120 after a landscape to
portrait resolution change. It reproduces in isolation with UTF-8 enabled. The
engine file `main.py` and that test were not changed by TASK-DESKTOP-001. Do not
claim a completely green engine regression suite.

The initial sandboxed Vite build could not resolve real file paths and sandboxed
Chromium integration tests failed. The relevant builds/tests passed with the
required filesystem/process access. C: had less than 2 GB free; the disk-space
check correctly rejected it. The live smoke test uses an isolated library on D:.

## Manual/end-to-end acceptance still required

| Scenario | Status / reason |
| --- | --- |
| Desktop shortcut launch, no terminal, installer wizard | Not verified: no installer artifact |
| Native import and OS drag-and-drop using real user footage | Input is present; interactive selection/drop not performed |
| Live Gemini analysis and AI clipping with user credentials | Not called; isolated desktop smoke uses no credentials and makes no paid requests |
| Full uploaded-video analysis → captions → timeline → final export | Existing engine tests cover components; complete credentialed workflow not exercised through the shell |
| Native save dialog/export destination and cancelled downloads | Implemented; needs interactive acceptance with a real export |
| Local projects reopen after full app restart | Backend state roundtrip and durable engine recovery are covered separately; interactive restart/reopen still needs acceptance |
| NVIDIA/NVENC and AI CUDA on each supported driver/GPU | Existing actual encode probe/fallback retained; protected `/api/desktop/capabilities` reports encoder and AI CUDA separately. Hardware matrix not qualified |
| First-run model download, interrupted resume, offline retry | Manager implemented; no new model download completed during this task |
| Frozen Python workers and bundled DLL/model loading | Build configuration/dispatch implemented; needs an actual freeze and clean-machine test |
| Install, upgrade and uninstall with retained projects | Inno configuration prepared; not executed |
| Windows installation without developer tools | Not executed; required release vendor inputs are missing |
| Authenticode / secure upgrade distribution | Documented release plan; not signed or published |

## Known limitations and remaining tasks

1. Complete the concrete vendor inputs listed in DESKTOP_RELEASE.md, build the
   frozen application/installer and qualify it on a clean Windows VM. The build
   script is source configuration, not evidence of a successfully frozen app.
2. Resolve the existing legacy reframing test failure or formally scope that
   old fallback out of a release. Run Windows tests with UTF-8 (`-X utf8`).
3. Qualify the entire credentialed editing workflow and GPU/CPU matrix. A codec
   availability result alone is not proof of decoded video/timeline playback.
4. Pin and review the Python lock for the chosen CPU/CUDA release, audit
   distribution/model licenses and fulfill the selected FFmpeg source terms.
5. The WebView2 adapter uses pinned pywebview internals for synchronous request
   headers. Rerun the live smoke test whenever either runtime changes.
6. One concurrent pipeline is the supported desktop default. Multiple jobs and
   automatic updates remain unqualified. The optional tray is not implemented.
7. Other dashboard service keys are intentionally session-only. Gemini saved in
   native Settings persists via DPAPI. Subscription provider contracts have no
   payment/authority implementation and grant no synthetic paid entitlement.
8. In-progress exports stop on close. Debounced per-clip UI state may need up
   to two seconds to reach disk; use the editor's existing explicit save before
   closing. Source uploads and completed local projects are retained until the
   user explicitly removes them.

No `OpenShorts-Setup.exe` was generated, installed, uninstalled, signed or tested
on a clean Windows installation during this task.
