# TASK-DESKTOP-003A — executed results

Date: 2026-10-17 (Asia/Colombo). Companion audit: `NATIVE_INTEGRATION_COMPATIBILITY.md`.

## 1. Compatibility decision

The original two ZIPs are **not compatible as supplied**. The working pair is compatible after the additive protocol check, Windows worker-environment fix and stable Windows x64 NuGet runtime configuration. No Git history exists; SHA-256 source manifests provide exact transfer provenance instead of an invented commit revision.

The old engine ZIP lacks `desktop/`, native worker/build integration and the saved timeline modules. Root `native_engine_entry.py` is the correct worker path; no `desktop/native_engine_entry.py` is required. Reusable working files are supplied together in `build/OpenShorts-native-compatible-source.zip`, not silently inserted into or substituted for the original archives. See the companion report for verification/application commands.

## 2. Native workflow evidence

The user authorized the real video and explicitly authorized Gemini requests. The automated WPF acceptance used the native UI-bound import/generate/open/save/render commands, an isolated library and DPAPI-protected configuration. This was not a fake HTTP job and not a manual mouse/accessibility acceptance test.

| Check | Executed result |
| --- | --- |
| Real media | 537,058,072-byte source, 1920×1080, audio present, 2152.352 seconds; original unchanged |
| Import / playback | Actual native file import and LibVLC video output succeeded |
| Gemini configuration | Configured key transferred to isolated current-user DPAPI; launch environment remains sanitized; copied test credentials removed after completion |
| Fresh processing | Local cached faster-whisper-small produced 1,149 transcript segments; Gemini requests returned usage/cost records; generation completed with 12 clips |
| Clip selections | All retained source EDL ranges are within the real recording. Canonical clip start=0 for montage outputs is not the original source time; verification checks `recipe.segments`. |
| AI selection qualification | **All 12 retained selections are marked `deterministic_transcript_fallback`.** This proves the operational fallback path, not acceptance of Gemini's recommendations or story quality. Selection algorithms were preserved. |
| Captions / framing | 1,650 source caption rows loaded in the native editor. Generated and final-export contact sheets inspected: timed text rendered, panel/speaker framing retained. Comprehensive semantic transcription accuracy is not certified. |
| Native saved project | Open/save/final-render/restart/reopen succeeded, with deep equality of saved edit decisions across restart |
| Final export | **1080×1920**, H.264 High / yuv420p, ~23.976 fps, stereo AAC 48 kHz; ~15.724 seconds, 5,896,626 bytes |
| GPU execution | Final stream encoder identifies `h264_nvenc`; actual export used NVENC on this host, beyond a capability-only probe |
| Media validity | All 14 generated quality receipts encountered passed; exported MP4 decoded completely with FFmpeg |
| Audio | Audio stream, decode and engine quality checks pass. No full human listening/comprehension acceptance was performed. |
| Cost evidence | Engine-reported estimated Gemini cost: 0.0268145 USD. This is the engine's estimate, not an independently verified billing statement. |

Generated real evidence is under `build/native-003a-real-fixed/`: `result.json`, redacted `engine-status.json`, `verification.json`, `user-video-export.mp4`, `caption-framing-sample.png`, `final-export-sample.png` and the isolated project library. Native acceptance reports `manualUiAcceptance=false` and explicitly retains human review requirements.

Two preceding runs failed during startup of processing, before fresh analysis, because the safe environment removed Windows USERNAME. Their isolated diagnostics are retained under `build/native-003a-real*`; the final corrected run completed. No engine algorithm was rewritten to make acceptance pass.

## 3. Existing native features and regressions

The **self-contained .NET WPF build** also passed the no-paid synthetic native acceptance using the source Python worker (`build/native-003a-synthetic/result.json`). It exercised actual playback/seek, clip reopen, phrase corrections, aligned-word timing/emphasis, custom caption appearance, drag-trim mutation/history, split/reorder/delete history, undo/redo, waveform, conflict rejection/reload, autosave, automatic/manual preview, final rendering, export and restart recovery. Template catalog/selection contracts remain available; engine template rendering has existing Python test coverage. Real-video acceptance used no selected template, so it does not qualify every native template/content combination.

## 4. Tests executed

| Run | Result |
| --- | --- |
| Complete Python suite: `python -X utf8 -m pytest tests -q --tb=short` | **1,585 passed**, 75 deprecation warnings, 370.89 seconds |
| Desktop/native focused run after the Windows environment fix | **18 passed**, including the added real sanitized-subprocess getpass regression |
| Final contract/transfer checks | **4 passed**, including complete source allowlist/hash verification and rejection of incomplete transfer |
| C# suite with `OPENSHORTS_TEST_ROOT` set | **25 passed**, including actual protected worker startup/restart and DPAPI interoperability; final Release run also passed |
| WPF solution build | Zero warnings/errors |
| Locked restore → self-contained publish → locked restore | Passed after stabilizing `RuntimeIdentifiers=win-x64` |
| Self-contained native acceptance with source worker | Passed |
| Authorized real-video native acceptance | Passed operational workflow and export checks, subject to selection/semantic limitations above |

The full Python run was collected before the final additional Windows identity regression was added. That regression and final transfer checks passed in the focused runs; **do not describe 1,586 as the executed full-suite count** or add overlapping test runs together.

The suite includes a controlled NVENC execution failure followed by real CPU encode replay, quality/timing preservation, and rejection of non-hardware decode/filter failures. A deliberately induced physical GPU/driver failure and full device/codec matrix were not executed. Local capability probes detected RTX 2050, initialized NVENC/libx264 and Torch/CTranslate2 CUDA support.

## 5. Release blockers and packaging answer

The source pair is ready to transfer/build together; the .NET part publishes with its runtime and LibVLC. **The complete application is not yet ready to package for customers or sell.**

- No frozen Python worker built or tested. Combined release build correctly stopped at the missing concrete FFmpeg corresponding-source/distribution record; that gate remains intact.
- WPF third-party notices, exact LibVLC/.NET/model/font inventory and redistribution review are incomplete. Model weights/runtimes require provisioning on a clean machine.
- Optional Remotion/browser-effect resources are not fully staged by the WPF worker builder.
- No complete signed installer produced or verified; install/upgrade/uninstall, update behavior and clean Windows VM acceptance remain outstanding.
- Retained clip selections used deterministic fallback. Human review of story choice, subtitle accuracy, framing and audio remains required; do not use mechanical media checks as proof of editorial quality.
- Native parity gaps remain in template-content/director authoring, independent audio/music and browser effects. Subscription authority and paid-account activation remain unfinished.

No installer-exists, production-ready or ready-for-sale claim is made. This task implements integration and compatibility only.
