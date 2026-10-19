# TASK-AI-ANALYSIS-003 — implementation and verification report

Date: 2026-10-19. Scope: existing OpenShorts Studio, opt-in adaptive analysis. No paid Gemini calls, provider changes, Git initialization, production model activation, or customer-media duplication were performed.

**Status:** checkpoints A–F implemented and exercised offline. Checkpoint G has an offline A/B/C artifact evaluator and scenario coverage tests; real-video comparative acceptance remains incomplete. Keep the existing production default.

## 1. Baseline architecture found

`main.py` owns transcription, selection and existing rendering. `story_director.py` maps hybrid/highlight sources using overlapping 180-second video chapters, spaced 177 seconds apart. Each chapter is encoded to a small H.264/AAC proxy. At or below 2 MiB, the existing transfer path uses inline video; larger payloads use the public Files API, processing-state polling and file references. Inline write failure can switch to Files API. Existing completed chapters, out-of-order results and short-section recovery checkpoints are retained.

Clip selection, ranking, scene detection, pacing, the existing Editing Director, automatic effects, editor timelines and FFmpeg/NVENC remain authoritative. The learning foundation uses SQLite and optional, disabled-by-default effect inference. Native WPF receives progress through the existing local bridge.

Baseline: **130 targeted tests passed in 18.08 seconds**, recorded in `build/amce-baseline.xml`. Original relevant source files were copied before modification to `build/backups/amce-20261019-170735`; no large customer videos were copied.

## 2. Causes of redundant analysis

Hybrid mode visually scans every chapter before knowing which candidate intervals need vision. Transcript candidate selection then performs separate reasoning over overlapping material. Retry/section recovery reduces failures but still has to inspect broad coverage. Earlier reference reuse was limited to a single request invocation; successful Files API references were deleted afterward. The six-stage presentation did not describe the new intermediate work.

The legacy route remains available. This task does not claim that an opt-in architecture fixes every provider/network failure in legacy jobs.

## 3. Files created and changed

New analysis package: `adaptive_analysis/__init__.py`, `runtime.py`, `media_index.py`, `transcript.py`, `candidates.py`, `gemini.py`, `pipeline.py`, `benchmark.py`.

Modified Python integration: `main.py`, `story_director.py`, `scene_detection.py`, `generation_options.py`, `app.py`, `desktop/processes.py`, `desktop/generation_drafts.py`, `desktop/generation_review.py`.

Modified native integration: `native/OpenShorts.Core/GenerationSettings.cs`, `GenerationReview.cs`; `native/OpenShorts.Desktop/GenerationWorkspace.cs`, `GenerationPanel.xaml`, `ClipperWorkspace.cs`, `ClipperWorkspaceView.xaml`, `ClipperReferenceWorkspace.cs`.

New tests: `tests/test_adaptive_analysis.py`, `tests/test_adaptive_benchmark.py`, `native/OpenShorts.Tests/AdaptiveAnalysis.cs`. New verification artifacts include this report, XML/TRX results, `build/amce-local/measure.py` and its synthetic fixture/results, plus the benchmark manifest/report under `build/amce-benchmark/`.

The existing effect categories, rendering engine, knowledge schema and ML activation gates were not replaced.

## 4. Local media index

Version 1 index stores source identity, FFprobe dimensions, source-time speech units/paragraphs, supplied speaker turns, speech intervals, existing CPU PySceneDetect boundaries, image-change bins and relative audio RMS bins. The full source SHA-256 invalidates caches when content changes. Index keys also include duration, ASR and retained measurements. Retained faces, subjects, crop paths and frame observations are reused when supplied; otherwise they are explicitly absent.

Motion analysis streams every decoded frame through PyAV using source PTS, retaining two 96 × 54 grayscale image buffers and half-second measurements. It does not infer subject velocity or physical camera movement. Audio RMS is relative energy, not a beat detector or sporting-event classifier. No object, ball, scoreboard, emotion or sport detector was invented or installed. The existing scene detector now accepts an optional per-frame cancellation/budget check; legacy callers are unchanged.

The index is reused from the selected library's `cache/video-analysis/adaptive` directory. It stores metadata rather than duplicate source video. Temporary verification proxies/stills are removed after the operation.

## 5. Transcript-first reasoning

All available transcript chapters are processed before any Gemini visual input. Bounded overlapping source-text groups retain IDs, absolute timestamps, ASR wording and optional speaker identifiers. Oversized untimed segments are divided without inventing word timing. Exact quote checks reject invented quotes and missing source IDs. Incomplete/fragmentary ASR cannot receive positive completeness merely from the model's flag.

A bounded hierarchy relates condensed chapter excerpts and existing candidate IDs; it does not resend the complete transcript as a global prompt. Chapter plans and narrative maps are cached. Cross-chapter references are retained; a distant setup/payoff link does not authorize silently skipping intervening footage. Existing editable summary assembly remains responsible for deliberate summaries.

ASR evidence is explicitly uncertain transcription, and editorial completeness is a model judgment rather than a verified factual outcome. Source text and footage are treated as data, not instructions.

## 6. Independent visual candidates

Local discovery uses measured image-change novelty/sustained activity, relative sound novelty and supplied speaker changes. A scene cut is only supplemental evidence near a measured cue. Candidates are padded for category context and distributed over the timeline before limiting their count. A portion of the shortlist is reserved for visual-only discovery, including silent footage.

These are plausible activity windows, not confirmed goals, wickets, reactions or prizes. Small-ball events, subtle actions and static meaningful visuals can still be missed by these generic measurements; real reference recall has not been measured.

## 7. Selective Gemini verification

The policy selects no visual request, three targeted stills, or a bounded short video. Sports and local action require temporal video. Normal windows include lead-in/outcome context; an explicitly uncertain response requesting more context can trigger one bounded expansion under the **same logical retry budget**. Still images cannot authorize action/reaction cues. Candidate intervals outside the inspected context are withheld rather than silently truncated.

Only sufficiently confident, classified observations without explicit uncertainty authorize visual candidates/cues. Proposed commentary titles are replaced by inspected descriptions, so commentary alone does not confirm a sporting outcome. Low-confidence or absent evidence grants no crop/effect authority. Safe isolated-subject observations can enable subject framing; shared action and uncertain sports tracking preserve the scene.

The adapter reuses existing Gemini key precedence and transport code. It checks model generation metadata and SDK Files/video-metadata support. This capability check does not independently establish the selected model's visual accuracy. Files references are scoped to the actual API-key fingerprint and encoded payload, polled before use, and checked for expiry. Expired references are replaced within budget. Authentication/permission/rate-limit failures remain distinguishable; adaptive code does not rotate keys to evade 429 quotas or silently select an old encrypted pool.

## 8. Categories and budgets

Native Analysis choices: `adaptive-economy`, `adaptive-balanced`, `adaptive-quality`. Advanced settings expose `auto`, podcast motivation/education/comedy, challenge, cricket, football and general categories, plus a bounded optional highlight instruction. These are analysis policies, not new editing categories.

Podcast prompts retain complete arguments/explanations/joke endings; challenge prompts retain rules/stakes/attempt/obstacle/payoff; sports prompts require temporal evidence and preserve shared action. All use existing supported editing strategies. No unsupported speed-ramp/freeze-frame records were added, and no effect remains a valid outcome.

| Profile | Video seconds submitted | Visual requests | Estimated input tokens | Analysis wall budget | Additional attempts | Candidate limit |
|---|---:|---:|---:|---:|---:|---:|
| Economy | 120 | 4 | 24,000 | 600 s | 1 | 24 |
| Balanced | 360 | 10 | 60,000 | 1,200 s | 2 | 40 |
| Quality | 720 | 20 | 120,000 | 1,800 s | 2 | 64 |

Explicit podcast categories start with 2/6/12 visual requests. Explicit cricket/football categories start with 60k/180k/360k estimated input tokens to accommodate denser temporal sampling. These are uncalibrated starting policies, **not measured optimal budgets**. Auto-category discovery does not silently raise an already chosen budget.

Allowlisted `.env` overrides: `AMCE_MAX_VIDEO_SECONDS`, `AMCE_MAX_VISUAL_REQUESTS`, `AMCE_MAX_INPUT_TOKENS`, `AMCE_MAX_JOB_SECONDS`, `AMCE_MAX_RETRIES`, `AMCE_MAX_CANDIDATES`, `AMCE_MAX_TEXT_REQUESTS`. Optional `AMCE_COST_CEILING` requires explicit `AMCE_INPUT_PRICE` and `AMCE_OUTPUT_PRICE` per million tokens. Do not configure guessed pricing. Limits are saved with resumable job options. Preflight checks occur before encoding/uploading; transport switching does not reset retries. Every generation submission, including repeated inference using an uploaded reference, counts against submitted duration and estimated token limits. Unique logical-window duration is reported separately.

## 9. Fusion and ranking

Finite in-source bounds are mandatory. Fusion combines overlapping text/local/retained candidates and preserves provenance and uncertainty. Expansion invalidates a previously complete boundary judgment. Ranking uses existing clip scoring plus explicit editorial importance, completeness judgment and inspected visual support, followed by overlap deduplication. Each selection retains its explanation, evidence channels and verification status. Scores are not promises of virality.

## 10. Knowledge and ML

Existing SQLite storage receives source references, boundaries, category, provenance/evidence types, selected status, explanation and skip reasons. Records and receipts are **unreviewed**. Shared storage receives no full source videos or complete transcript/quote payloads from this adapter. Collection preferences are respected; optional database failure does not break clipping. No new columns/migration were needed for typed records in the existing generic tables.

Native workers use `<selected library>/learning/editing-knowledge.sqlite3` via `OPENSHORTS_LEARNING_DIR`; source-only execution retains the existing learning location policy. Existing human feedback, dataset generation, model registry and privacy/deletion controls remain authoritative. No unreviewed decision is a positive training label, no synthetic model was promoted, and no new ML highlight ranker was activated. Existing validated optional effect inference remains downstream in the current director.

## 11. Gemini tokens and requests

**Live paid requests for this task: zero. Live token/cost/quality comparisons: not measured.** Mocked tests check accounting and that resumed identical operations can perform zero new text/visual requests. They are not provider token measurements.

`amce-metrics.json` records attempted text/visual generations, actual reported token usage when present, estimated input reservations, provider cost estimates, optional configured pricing reservations, submitted/unique video duration, cache hits and additional attempts. File-upload time is measured separately; inline HTTP upload and inference time cannot be separated by this SDK boundary and are not presented as isolated upload timing. Monetary reservations and actual usage can differ; completed provider responses cannot be retroactively uncharged.

## 12. Local latency and resources

Latest `build/amce-local/result.json` measures a **generated 4-second, 640 × 360, 30 fps test pattern**, not customer footage or a comparative highlight benchmark:

| Measurement | Result |
|---|---:|
| Frames decoded for motion | 120 / 120 |
| Motion/audio index wall time | 0.505 s |
| Process CPU time during that pass | 0.578 s |
| Motion pass alone | 0.343 s |
| Existing CPU encode | 0.340 s, libx264 |
| Existing NVIDIA encode | 0.391 s, h264_nvenc |
| Output duration, both encoders | 4.000 s |
| CPU fallback | Neither run required it |

Whole measurement-process peak working set was 56,057,856 bytes, including imports/decoders; this is not isolated detector RAM. Committed/private process memory is separately retained in the JSON. Long-video latency, GPU quality equivalence and human preference are not inferred from this fixture. Existing regression tests exercise actual preview/final replay, output checks and CPU fallback after simulated NVENC failure.

## 13. Caching, recovery and progress

Cache scope includes source identity, model, category/user constraints, schema/prompt versions and visual encoding recipe. A manifest resolves visual observations through an additional payload-identity key. Validated observations/chapter reasoning are reused without re-encoding or another paid generation. Matching legacy chapter checkpoints can seed adaptive candidates/observations only after the exact legacy source/model/transcript identity check; changed sources are rejected. Adaptive metadata cache is capped at 512 JSON records; uploaded-reference metadata is bounded and expires locally after 46 hours, with server state checked before use.

Cancellation/budget checks cover source hashing, decoded frames, scene detection, audio, requests and retry boundaries. Request timeouts are capped by remaining analysis budget. Existing native cancellation still terminates its owned worker; atomic completed checkpoints survive. A blocking SDK/decoder call may finish cleanup before control returns; this is not an exact real-time deadline guarantee. Failed windows do not erase validated earlier work. No transcript-only replacement is used to invent missing sports evidence.

WPF displays eleven stages from source preparation through export validation. Adaptive events expose actual subtask counts, stage elapsed time, cache reuse and retry state; overall running progress and remaining time stay unestimated. The processing surface accommodates additional rows and Advanced settings scroll. Existing render/validation events remain authoritative; the adaptive edit-planning stage hands the plan to the existing director and does not measure all later director internals.

## 14. Verification evidence

Baseline: 130 Python tests passed. Final combined regression suite: **359 passed, zero failed, in 53.74 seconds**, recorded in `build/amce-final.xml`. After the final extractive-summary metadata guard, **44 focused adaptive/benchmark tests passed** in 4.09 seconds (`build/amce-acceptance-final.xml`); these overlap the combined suite and must not be added as distinct tests. Native: **60 tests passed**, zero failed/skipped, in `build/amce-native-tests/amce-native-final.trx`. WPF Release build succeeded with **zero warnings and zero errors** into `build/amce-native/`.

Coverage includes no speech, silent activity, multiple-speaker signals, incomplete ASR, fabricated quotes, uncertain/false sports cues, all-frame motion, overlap fusion, absent visual evidence, invalid timestamps, zero visual budget, shared retry/transport limits, WriteTimeout/ReadTimeout, 429 without quota rotation, cancellation/resume, expired files, cache corruption/change invalidation, legacy checkpoint reuse, credential precedence, learning safety, saved settings, effect regeneration and manual overrides, preview/final replay, CPU exports and NVENC recovery. Existing PySceneDetect `get_frames()` deprecation warnings are unrelated to the new behavior.

The initial sandbox test invocation hit Windows atomic-replacement permissions; rerunning with the authorized normal host test environment passed. One context test expected 25 seconds instead of the source-clamped 23-second unique window; it was corrected, and submitted duration additionally counts every inference attempt. A local measurement command initially used a non-UTF-8 console; the reproducible harness now sets UTF-8. No task-related failure is intentionally left unfixed in the passing suites.

## 15. Incomplete acceptance and limitations

- Real A/B/C comparisons on the same seven authorized video categories have **not** been run. `build/amce-benchmark/manifest.json` and `report.json` explicitly record missing artifacts/references; acceptance is false. `python -m adaptive_analysis.benchmark <manifest> <report>` evaluates saved existing/transcript/adaptive plans against explicit reference intervals. Human story completeness, preference and false-event counts must be supplied; absent data stays null. Synthetic scenario tests establish no quality improvement.
- Paid Gemini multimodal latency, token reduction, timeout-rate improvement and long-video highlight recall remain unmeasured. Additional paid comparisons require separate approval.
- No calibrated dedicated ball/action/scoreboard detector or new learned highlight-ranking model exists. Retained tracking measurements may be absent; safe wide/context-preserving layouts are then preferred.
- Visual operations cap individual windows at 60 seconds. Longer candidates without contained inspection evidence are withheld, not silently declared complete. Very short/subtle events can escape generic novelty discovery. Stills cannot establish temporal outcomes.
- Global narrative links preserve source references; they do not prove story completeness or automatically authorize discontinuous edits. Existing summary/pacing validation can reject a candidate after analysis.
- The WPF application was built and native contracts tested; a full live seven-category native UI/customer workflow acceptance session and packaged-installer rebuild were not performed.
- Budget estimates are safeguards, not exact provider billing predictions. Local defaults require real-video calibration. No production model is ready for activation solely from this task's synthetic tests.

## 16. Recommended default and trying the build

**Keep the existing `transcript` default and `hybrid` fallback unchanged.** Do not promote adaptive mode until the real-video comparison and human acceptance are complete.

The compiled native application is `build/amce-native/OpenShorts.Desktop.exe`. It uses the existing source/engine setup. In generation settings, explicitly select an adaptive profile; select the category and optional instruction in Advanced. Start with an appropriate test source and review uncertainty/receipts before approving an output. The new route continues through the existing editable timeline, effects and local renderer.

No API keys were changed, printed in this report or embedded in new source files.
