# TASK-010 — Professional rendering and performance

## Baseline and implementation scope

Inspected `ffmpeg_utils.py`, FFmpeg v2 reframing/shot assembly, the OpenCV v1 raw-frame loop, recuts, ASS subtitles/hooks/director/templates, timeline caches/progress/jobs, export/audio validation, API generation/recovery and the React dashboard. Also inspected the installed Remotion 4.0.447 renderer types/implementation, render worker/server, browser WebCodecs path and existing tests. No AGENTS.md was found. No renderer, architecture, package requirement or Docker dependency was replaced or added.

Existing backends: Python FFmpeg/libass for composition/captions/graphics; OpenCV and local detectors for analysis/legacy frames; a separate optional Node Remotion service; browser Remotion/WebCodecs. libx264/NVENC selection already existed, but the probe was a tiny null encode, runtime failures were inconsistently retried, timeline output hardcoded x264, encoder settings were absent from cache dependencies, and progress was largely stage-based. The source inspection also documented historical AAC/intersample and NVENC RGB colorspace pitfalls, which remain covered by existing audio validation and explicit yuv420p output.

Pre-change focused baseline: **77 passed** (`test_ffmpeg_utils`, `test_timeline_project`, `test_timeline_api`, `test_export_quality`). The two unrelated full-suite baseline failures are listed below.

## Changes and behavior

### Capability, quality and CPU/GPU policy

- `GET /api/render/capabilities` reports FFmpeg/FFprobe version/availability, required filters, actual initialized libx264/NVENC support, installed OpenCV/Remotion components and process resource limits. GPU presence is not equated with usable encoding.
- NVENC initialization now runs at **1080×1920**, yuv420p with production HQ/VBR/AQ options. CPU initialization is also exercised. Missing dependencies/GPU/driver failure safely select CPU, with explicit selection logging/reporting. Cached hardware results avoid repeated initialization; a runtime failure enters a 60-second cooldown before reprobe.
- Existing per-stage quality tiers are retained: standard CPU CRF18 / delivery CRF22, studio CRF16; corresponding existing NVENC CQ25 / CQ29 / studio CQ20. CPU fallback maps these tiers explicitly and preserves filters, framing, clip timing, audio mapping and dimensions. CRF and CQ are different encoder controls, not a claimed perceptual equivalence.
- Configurable allowlisted x264 speed presets and NVENC p1–p7 presets do not replace quality controls. Invalid preset values fail clearly; thread/concurrency settings are bounded. CPU remains the default unless the existing local configuration chooses `auto` or `nvenc`.
- The legacy OpenCV raw-input renderer uses matching-tier libx264 because already consumed stdin cannot safely replay after a GPU session fails. File/filter v2, director/template/caption/hook and recut paths support NVENC plus bounded CPU recovery. The installed Remotion H.264 codec selector has no Windows NVENC implementation; its optional service explicitly retains CPU encoding. Browser WebCodecs acceleration depends on the client and is not claimed as NVIDIA-specific.

### Shared FFmpeg execution and validation

`render_runtime.py` is an execution adapter for the existing FFmpeg commands, not another video renderer. It bounds active processes, threads, captured binary output, deadlines and child lifetimes. It passes argv arrays without a shell and writes no command/source text to performance receipts.

Normal MP4 renders write a uniquely owned sibling staging file, force yuv420p for H.264, enable faststart, verify container/video/decode readiness, then atomically replace the destination. Failure/cancellation deletes that staging file and preserves the previous output. A diagnosed NVENC error retries once on CPU; unrelated decode/filter errors do not trigger GPU repair loops. A failed cut similarly gets a single CPU recovery for hardware errors while retaining its pre-existing finite schedule for other failures. The old unbounded cut attempt now has a 180-second timeout.

Known ASS caption/graphic assets are checked for existence/size/event validity and sampled raster changes on up to two styles/layers. A required legible layer producing no measurable image change is rejected. Unknown/freeform edits, frames below 160px, extremely brief events and geometry-changing filters are explicitly **UNVERIFIED/NOT_APPLICABLE**, not falsely certified. Requested captions with valid retained timing that fail generation block completion by default; silent sources and intentionally disabled captions remain valid.

Final publication continues through existing FFprobe/targeted decode/audio validation: expected dimensions/aspect/FPS/duration, expected audio, A/V timing, blank frames, borders, source-relative freezing, decode errors and measured AAC loudness/peaks. Existing framing/subject checks and scene-aware crop logic are preserved. Runtime readiness is an additional early check, not a replacement for the final technical gate. Explicit codec contracts can reject the wrong video codec, pixel format or audio codec without changing older records that do not declare those fields. A real worker regression caught Remotion full-range yuvj420p output; its native BT.709 conversion now produces limited-range yuv420p, checked by the same final gate.

`<output>.render.json` records requested/effective command encoder, selected mode, fallback, attempts, timing, peak encoder RSS when measurable, frames, threads, output identity/size, media and overlay-check evidence. The final `.quality.json` carries that evidence through audio mastering. The dashboard export details disclose actual encoder/fallback and overlay-check coverage.

### Work reuse, concurrency, progress and cancellation

- Encoder/quality/thread policy is included in timeline dependency keys; old artifacts are not reused under a different requested encoding policy. Successful cache parts still use file-identity receipts.
- A complete clean canonical clip already matching dimensions/FPS/H.264/yuv420p/square pixels/audio requirements bypasses video re-encoding. Trimmed/changed source still uses precise re-encoding. Unchanged cached segments and assemblies remain reusable.
- Caption-only passes copy audio instead of encoding it again. Existing combined template/director ASS rendering and stream-copy shot joins remain in place. Valid cache receipts are refreshed after mastering changes final AAC bytes. This avoids rerendering an unchanged final solely because its audio mastering changed file identity.
- Python encoder slots, CPU encode threads, filter threads, decoder threads and clip workers are bounded. Existing app-level jobs/timeline worker limits still apply; these are per-process limits, not a claim of a machine-wide semaphore across every application.
- FFmpeg progress is parsed from its actual frame/output clock. Binary waveform/scene extraction keeps a separate binary stdout path, preventing progress text from corrupting PCM/pixels. Queued/cancelled work cannot release another job's slot.
- Generation status exposes per-clip `render_progress`; the dashboard shows current-pass frames, seconds and measured percentage only when duration is known. Saved editor progress updates within each encoding stage. Existing decorative claims of an active analysis/transcription thread during export were replaced with measured encoding information/general processing state. 100% remains reserved for validated completion, not merely the end of encoding. Percentages describe stages/current passes, not an invented wall-time ETA.
- Saved editor cancellation kills/reaps its FFmpeg child, removes owned partial files and retains completed cache parts. Cancellation/deadlines also work while waiting for an encoder slot.
- Optional Remotion service uses a FIFO worker gate, bounded frame concurrency/cache, staged output, bounded deadlines (including queue wait), and `makeCancelSignal`. `POST /api/render/{id}/cancel` authorizes against the render service's actual source job; clients cannot authorize cancellation by supplying another job ID. During bounded Python audio/quality validation, cancellation prevents publication and waits for validation to exit, rather than leaving unmanaged subprocesses. Terminal status records are bounded separately from media retention.

## Configuration

| Setting | Default / bounds |
| --- | --- |
| `FFMPEG_ENCODER` | Existing `x264` default; `nvenc` or `auto` enables supported GPU paths |
| `FFMPEG_X264_PRESET` | Unset: existing per-tier preset; override with ultrafast/superfast/veryfast/faster/fast/medium/slow/slower/veryslow |
| `FFMPEG_NVENC_PRESET` | Unset: existing per-tier p4/p5/p6; optional p1–p7 |
| `FFMPEG_THREADS` | Up to 4 by default, bounded 1–16 |
| `RENDER_MAX_ENCODERS` | 2 per Python process, bounded 1–4 |
| `CLIP_WORKERS` | 2, bounded 1–4 |
| `RENDER_STRICT_OVERLAYS` | 1; 0 restores legacy missing-caption fallback, while known-asset raster checks still apply |
| `RENDER_SERVICE_WORKERS` | 1 optional Remotion job, bounded 1–4 |
| `REMOTION_CONCURRENCY` | 2 browser rendering slots per service job, bounded 1–4 |
| `REMOTION_X264_PRESET` | medium; allowlisted x264 speed setting |
| `REMOTION_TIMEOUT_SECONDS` | 600 including queue wait, positive values capped at 1800 |

Ordinary Python render operations keep existing per-stage budgets (timeline stages up to 180s, aggregate timeline 600s, other existing render budgets up to 1800s); queue waiting consumes the passed runtime budget. The optional service also bounds pending work/status retention. Existing Windows MP4/H.264/1080×1920/9:16/source-appropriate-FPS/AAC defaults remain provided by the selected output preset. Non-portrait legacy modes retain their dimensions; this optimization does not force every legacy export to portrait.

## Benchmark

Machine: **13th Gen Intel Core i5-13420H**, **NVIDIA GeForce RTX 2050 4GiB**, driver **610.47**, Windows, FFmpeg **9.0 full Gyan build**, Python 3.11; installed Remotion **4.0.447**. Actual CPU and full-HD NVENC initialization passed.

Reproduce with `.venv\Scripts\python.exe -X utf8 benchmarks/render_exports.py`. No source download, Gemini request or private user video is needed. Fixtures are deterministic synthetic video/tone audio: a simple 30s portrait clip, a moving 60s clip with five timed caption tokens/second, and 30s of existing BLUR/SPLIT/EDITORIAL filter compositions. Caption timing is a synthetic clock fixture, not a speech-intelligibility assessment. Preparation is excluded. CPU uses fast/CRF18; GPU uses p4/CQ25 with existing AQ/VBR; 30fps, 1080×1920, encode threads=4, AAC. Both modes receive identical source and layer decisions.

Final runs were sequential, with no concurrent test/build/render verification jobs. These are single observations, not statistical platform-wide speed guarantees. Render seconds include composition/caption encoding plus staging readiness/raster checks; end-to-end also includes measured mastering and targeted export validation. Encoder RSS is peak sampled FFmpeg process/children memory (optional existing psutil), not total OpenShorts/model memory. GPU utilization is whole-device nvidia-smi telemetry sampled during the export, including its CPU validation phase; it is not process attribution. NVENC utilization is queried separately from GPU compute utilization. Device-memory telemetry reported zero on this Windows driver and is retained as reported in raw JSON, not interpreted as zero GPU memory consumption.

| Case | Encoder | Render s | End-to-end s | Render FPS | Peak encoder RSS MiB | GPU mean % | NVENC peak % | Output MiB | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| simple-30 | libx264 | 5.109 | 11.893 | 176.17 | 419.45 | 0.09 | 0 | 0.65 | PASS |
| simple-30 | h264_nvenc | 3.792 | 10.566 | 237.33 | 368.62 | 7.92 | 100 | 0.95 | PASS |
| caption-heavy-60 | libx264 | 23.131 | 35.010 | 77.82 | 442.23 | 0.00 | 0 | 44.50 | PASS |
| caption-heavy-60 | h264_nvenc | 6.653 | 17.849 | 270.55 | 391.73 | 8.29 | 100 | 49.85 | PASS |
| multi-scene-30 | libx264 | 15.593 | 22.901 | 57.72 | 438.16 | 0.00 | 0 | 21.24 | PASS |
| multi-scene-30 | h264_nvenc | 9.570 | 17.537 | 94.04 | 380.65 | 4.22 | 100 | 23.99 | PASS |

All six completed exports were **PASS**, with actual h264_nvenc receipts on all three GPU runs (no mislabeled CPU fallback). Source FPS, 1080×1920 raster, yuv420p, AAC, A/V timing, decoded samples and final audio safety passed the shared gate. The caption-heavy assets passed the known-ASS raster check. Three full-HD CPU/GPU frame-pair SSIM samples per case were computed outside speed measurement: minimum 1.000000 (simple), 0.997014 (captions), 0.996681 (multi-scene). These demonstrate sampled encoder/color consistency relative to CPU output, not a universal perceptual-quality guarantee. Actual outputs, timestamps, thresholds, reports and measurements are retained in `output/task010-benchmark/results.json` and its case directories. CPU/GPU output sizes differ; no bitrate/size equivalence is promised.

## Verification

- Pre-change focused baseline: **77 passed**.
- Full Python suite, excluding `tests/test_mcp_stdio.py`: **1,474 passed, 2 failed** in 309.99s (`logs/task010-full.xml`). The unchanged pre-existing failures are `tests/test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed` and `tests/test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`. The three MCP stdio cases were excluded because of the previously observed startup timeouts; they are not verified here.
- Final focused Python checks after codec/queued-cancellation hardening: **79 passed** (`test_render_performance`, `test_export_quality`, `test_export_quality_api`, `test_ffmpeg_utils`; `logs/task010-final.xml`). Earlier relevant groups passed **91** core editor/runtime tests and **142** template/hook/caption/director tests; these overlap with the full run and must not be summed.
- Dashboard: **28 tests passed**. ESLint on changed frontend files passed; production build passed. Existing optional OpenPanel-variable, Browserslist-age and large-chunk warnings remain.
- Optional Remotion service: **19 tests passed**, including a real full-HD staged captioned worker export with H.264/yuv420p/AAC and faststart assertions; TypeScript production build passed after the native BT.709 fix. Existing media-component objectFit deprecation warnings remain.
- Six benchmark exports: **6 PASS**. Actual CPU/NVENC outputs and sampled comparisons are recorded below `output/task010-benchmark/`.

The complete Python suite is not green because of the two existing failures above. The final focused run and Remotion checks cover the changes made after that full-suite run.

Regression coverage includes successful real H.264/AAC output/faststart, NVENC-to-CPU replay with unchanged filters/timing/audio, no repair loop for unrelated failures, quality-tier mapping/preset rejection, thread-local CPU policy, capability initialization, output-clock parsing, clean binary waveform output, cancelled/timed-out encodes, queued cancellation and slot ownership, immutable output on failure, cache identity/passthrough, caption raster changes, missing-caption rejection/legitimate silence and cross-owner cancellation rejection. Existing template/director/scene/framing/audio/clip/editor suites were exercised. Remotion tests exercise real cancel signals and a real full-HD staged worker export in addition to queue/metadata checks.

## Changed files

| File | Change |
| --- | --- |
| `render_runtime.py` | Shared bounded FFmpeg execution, staging, progress, capability/encoder/cache policy, raster checks and receipts |
| `ffmpeg_utils.py` | Production-size NVENC probe, cooldown, validated speed presets, matching-tier CPU recovery, bounded cut attempt |
| `reframe_v2.py` | Reuse shared runtime; CPU-safe tiny preview selection |
| `recut.py` | Shared runtime for file cuts/joins |
| `subtitles.py`, `hooks.py` | Shared runtime for existing overlay encodes |
| `timeline_render.py` | Supported encoder selection, measured stage progress, policy-aware cache, exact source passthrough and audio copy |
| `timeline_api.py` | Persist encoder dependencies; refresh final cache receipt after mastering |
| `main.py` | Bounded workers, thread-local progress, stable CPU raw-frame fallback, strict requested-caption gate, persisted rendering settings |
| `editing_director.py`, `video_templates.py` | Reject failed required timed caption layers without replacing the existing layer pipeline |
| `export_quality.py` | Probe pixel format, enforce explicit codec contracts, carry valid rendering evidence through final validation/mastering |
| `generation_options.py` | Resume allowlist for nonsecret rendering policy |
| `app.py` | Capability endpoint, per-clip progress/status ingestion, authorized optional Remotion cancellation |
| `dashboard/src/App.jsx` | Measured export progress rows and source-preview data |
| `dashboard/src/components/ProcessingAnimation.jsx` | Measured encoding labels; remove invented active-analysis/transcription status during render |
| `dashboard/src/components/ExportQualityReport.jsx` | Actual encoder, fallback and overlay-check coverage |
| `dashboard/src/lib/renderProgress.js`, `renderProgress.test.js` | Validated progress presentation and regressions |
| `render-service/src/render-jobs.ts`, `render-jobs.test.ts` | Bounded FIFO jobs/settings/state and cancellation/real worker regression tests |
| `render-service/src/render-worker.ts` | Bounded CPU Remotion settings, native BT.709/yuv420p conversion, cancellation, staging, validation-before-completion and safe cleanup |
| `render-service/src/server.ts` | Validated dimensions/resources, status capacity, no-Docker static root, source job context and cancel endpoint |
| `benchmarks/render_exports.py` | Reproducible CPU/NVENC cases, resource metrics, validation and sampled frame comparison |
| `tests/test_render_performance.py` | New runtime/performance/safety/API tests |
| `tests/test_ffmpeg_utils.py` | Hardware-failure expectation now matches required CPU recovery |
| `tests/test_timeline_project.py` | Explicitly cancel after completed part for the cache-retention test; measured mid-pass cancellation is tested separately |
| `tests/test_subtitles.py` | Test the shared runner boundary while retaining font/filter command checks |
| `.env.example`, `LOCAL_README.md` | Configuration and operating instructions |
| `docs/TASK-010-RENDERING-PERFORMANCE.md` | This implementation/benchmark/change report |

No dependency, secret, migration, mandatory service or Git commit was added.

## Manual verification and remaining limits

1. Start the existing Windows/no-Docker app. Inspect `/api/render/capabilities`; verify initialized encoders/filters rather than relying on the GPU name. Select the existing full-HD portrait preset and render a representative clip with captions/hooks/templates. Watch actual frame/time progress and the final export report; inspect H.264/yuv420p/AAC, 1080×1920, source-appropriate frame rate and synchronization.
2. Repeat with `FFMPEG_ENCODER=x264` and `nvenc`/`auto`. Inspect `*.render.json` and `*.quality.json` for actual encoder and fallback. A GPU/driver failure should retry once on CPU; unrelated bad media must fail. Never simulate failure by removing or changing system GPU drivers; unit tests cover controlled initialization/session failure.
3. In the saved timeline, preview/export, cancel during encoding and reopen. Partial staging should be gone, validated cache parts retained, cancelled output unpublished. Make only a caption/style change and inspect segment-cache hits. Re-export without changes to verify final cache identity after mastering. Whole compatible canonical clips should report `source_passthrough_parts` instead of another video encode.
4. If using the optional Remotion service, inspect `/health` limits, submit concurrent jobs, cancel one through the authorized API and confirm 100%/done appears only after validation. Cancellation during bounded Python validation waits for that worker to finish before cleanup/publication is suppressed. The installed service uses CPU on Windows; do not interpret browser WebCodecs or this service as verified NVIDIA encoding.
5. Review benchmark MP4s and final audio at a fixed playback volume, especially fast motion/scene joins/word highlights. Interactive Windows dashboard clicking and new paid/Gemini source generation were not performed here. Actual FFmpeg outputs, automated API tests and the real Remotion worker render were verified.
6. Existing cut/source framing and freeform edit paths remain available. Cache/stream-copy optimization is deliberately conservative: trimmed frames, changed geometry and continuous-audio montage assembly can still require re-encoding. Legacy separate hook/caption passes are retained where combining them would change layer replacement behavior. Source/model analysis is not included in the six rendering benchmarks.
7. Overlay raster checks are bounded evidence for known ASS assets, not a semantic proof that every effect/person/object remains visible. Extremely small/brief/unsupported layers disclose incomplete coverage. Severe framing still relies on existing detector/source evidence. Technical validation samples frames rather than decoding every frame twice; unknown corruption can require manual playback review.
8. Encoder slots are per Python process; existing app-job and optional Node-worker limits must be chosen together on low-memory Windows PCs. GPU initialization can later fail under contention; explicit CPU recovery is slower and disclosed. Optional resource measurements can be unavailable on other systems and are then reported as null/unavailable.
9. Existing whole-generation job lifecycle remains; this task does not add a separate whole-AI-analysis cancellation workflow. Saved-render cancellation, generic FFmpeg cancellation, existing browser abort handling and optional Remotion job cancellation are supported. No later development task was started.

Suggested commit: `perf(render): add validated hardware fallback, bounded execution and cache reuse`
