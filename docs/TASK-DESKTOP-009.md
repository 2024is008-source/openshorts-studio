# TASK-DESKTOP-009 delivery

Implemented the native Generating Clips and Generated Clips Review workspaces in the existing charcoal/cyan theme. No AI algorithms, subscription features or Home/Templates layouts were replaced.

## 1. Files changed

- Presentation: `native/OpenShorts.Desktop/ClipperWorkspaceView.xaml(.cs)`, `ClipperWorkspace.cs`, `ClipperTheme.xaml`, `GenerationStepper.xaml(.cs)`, `ReviewDetails.xaml(.cs)`.
- Integration: desktop `MainViewModel.cs`, `MainWindow.xaml(.cs)`, `App.xaml(.cs)`, `ImportWorkspace.cs`, `HomeWorkspace.cs`; Core `GenerationReview.cs`; EngineBridge `ReviewExportClient.cs`, `NativeContract.cs`.
- Python: `desktop/generation_review.py`, `desktop/native_api.py`, `desktop/contract.py`, additive worker timing in `app.py`; `desktop/video_import.py` rechecks a committed manifest when a fast worker exits during polling.
- Verification: `tests/test_generation_review.py`, `tests/test_native_import.py`, `native/OpenShorts.Tests/GenerationReview.cs`, `native/OpenShorts.Desktop/ClipperSmokeTest.cs`, `tools/prepare_clipper_smoke.py`, source-pair requirements in `tools/native_pair.py`.

## 2. Reused backend functions

The authenticated EngineBridge submits the existing upload/process pipeline. Cancellation closes the existing owned Windows Job Object. Delivered-media validation, cached thumbnails, recovered metadata, clip ranking and saved timeline GET/PUT/run/cancel operations are reused. Timeline rendering and export quality gates remain the existing FFmpeg implementation. DPAPI credential storage is unchanged.

## 3. New UI components

Generation: workflow icons, actual imported source card, animated indeterminate ring/bar, observed stage list, elapsed time, safe diagnostics, frozen settings and managed-background indicator.

Review: LibVLC preview/fullscreen/seek/volume, virtualized rows, score/duration/source sorting, available-tag filters, batch checkboxes, working More Actions for copying titles/hooks, saved hook/style/framing/audio details and export settings. Narrow windows move Details/Export into a tab; short windows reduce repeated metadata. Primary actions remain outside the scrolling details area.

## 4. Progress and job state

Adds authenticated GET `/api/desktop/jobs/{job_id}/progress`. Status polling is asynchronous at 1.5-second intervals with a 30-second status-request timeout. Overall progress remains indeterminate until actual completion. Log observations are explicitly labelled reported, rather than invented stage completions. Remaining time is not estimated without measurements. Raw provider logs and secrets are not exposed by the new UI.

Idle, preparing, running, cancel_requested, cancelled, failed and completed states are represented. Submission has no cancel button until the worker returns its job ID. Navigation preserves the in-app job; shutdown still stops the owned worker. Failed generation never retries paid analysis automatically.

## 5. Results and preview

Adds authenticated GET/PUT `/api/desktop/jobs/{job_id}/review` and GET `/api/desktop/jobs/{job_id}/clips/{clip_index}/thumbnail`. Results are derived from actual metadata and validated delivered file references. Missing/unrendered records are distinguished. Scores are retained editorial scores, never probabilities; stale scores are hidden. Default selection chooses the highest available score unless a valid saved selection exists.

Real rendered MP4 playback uses the existing LibVLC player without editor overlays. Missing rendered media can use a clearly labelled retained-source segment when available. Edit opens the original revision-protected timeline and retains source timestamps, captions, framing and template decisions. Global Video Editor navigation loads the selected review clip rather than leaving a previous timeline attached to another clip's playback.

Selection, sort/filter preferences and export history use an atomic revision-protected `desktop-review.json`. Corrupt preferences and revision conflicts are not silently overwritten. Completed projects, selected clips and export history were recovered after a real worker restart in the native acceptance test.

## 6. Export integration

Individual, selected and all-available exports run sequentially through saved timeline final rendering. Controls support MP4/H.264/AAC, destination/name, supported resolutions, frame rate, CPU/NVIDIA/automatic encoder, quality and caption inclusion. Caption inclusion changes the saved timeline through its revision contract. Output files are numbered when necessary; the final copy also refuses overwrite races. Each item keeps its own status/progress. Retry targets failed exports only. Rendering settings are captured for the batch, and refreshing results preserves the chosen filename.

## 7. Tests executed

- Focused Python regression suite: **69 passed**, with thread exceptions treated as errors. Includes authenticated routes, cancellation/owned cleanup, scoring, missing media, corrupt/revision-conflicting state, import completion race, real thumbnails and a real 1080×1920 timeline render.
- C# test suite: **54 passed**. Includes contract compatibility, nullable scores/progress, existing timeline revisions/captions, safe filenames and export conflict handling.
- Normal Debug build: **0 warnings, 0 errors**. Isolated Release configuration: **0 warnings, 0 errors**. The final reference refinement also built the normal Release output successfully; the normal launcher now chooses that newer build.
- Final native acceptance: `build/clipper-009-verified/clipper-result.json` reports success. Tests actual local import, mocked AI progress/errors/disconnect/cancellation/background navigation, real recovered clips, native playback/fullscreen, editor opening, real sequential exports, partial failure/retry and worker restart recovery.
- FFprobe confirmed the acceptance MP4 outputs contain **1080×1920 H.264 video and AAC audio**. Native captures cover desktop, laptop and 910×510 effective layout (a small-window/high-scaling layout check). No actual Windows scaling setting was changed.
- **No paid Gemini requests were made.** Paid-job responses are mocked only in explicit `--clipper-smoke` diagnostic mode. Synthetic video and mocked scores are test fixtures, never production fallback records.

## 8. Remaining limitations

Fresh Gemini analysis was not exercised. ETA and overall pipeline percentages are unavailable until the engine supplies reliable measurements. Background execution lasts only while the desktop application remains open. Caption, framing and audio settings can be saved inline with revision protection, with advanced edits available in the existing Video Editor. Independent clip duplication is now supported through the existing saved timeline API; it shares retained media without copying large video files. A failed original generation candidate without delivered media cannot be individually rerendered through a nonexistent adapter operation; inspect preserved work or explicitly authorize a fresh generation run. The full Python suite, installer and clean-machine packaging were not run for this task.

Close the running app and reopen `start_wpf.vbs` to use the updated native build.

## 9. Suggested Git commit

`feat(desktop): add native AI generation progress and clip review workflow`
