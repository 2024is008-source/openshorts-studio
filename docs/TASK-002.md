# TASK-002: Automated export quality validation

## Inspection and smallest maintainable change

The baseline and TASK-001 were inspected before this task. `main.py` cuts source
segments, renders FFmpeg reframing and captions, then emits `CLIP_READY`.
`app.py` manages subprocess progress, metadata recovery, manual edits, subtitle
versions, downloads, social publishing, and archive restoration. The dashboard
also renders independent browser Remotion exports. The optional `render-service`
uses a Node worker with Remotion. Existing presence-based artifact checks could
accept nonempty but invalid, wrongly sized, mistimed, or missing-audio files;
browser/Node outputs did not share a technical acceptance contract.

The change adds one standard-library Python validator reused by these paths,
with JSON sidecars and existing job/clip metadata fields. It retains the current
renderers, UI workflow, Gemini integration, and no-Docker startup scripts.

## Implemented behavior

- FFprobe checks readability, nonzero size, MP4 container when applicable, video
  stream, expected dimensions/display aspect (including sample aspect ratio),
  frame rate, duration, expected audio, and audio/video start/end alignment.
  Bitrate uses stream/container data or a recorded size/duration estimate.
- Bounded FFmpeg windows sample the beginning, end, middle, periodic positions,
  and supplied scene transitions. Decode errors and required sample timeouts
  fail. Blank black/white frames, newly introduced dark borders, reference-backed
  freezes, unexpected silence, and extreme PCM clipping produce warnings.
- An aligned reference suppresses warnings for intentional black/white/static
  content. Legitimate silent/no-audio clips are accepted. Stereo sampling avoids
  mistaking phase-inverted stereo for silence. Unknown audio expectations are
  explicit warnings. No dark pixels are rewritten.
- Technical FAIL prevents `CLIP_READY`, successful completion, published edit
  URLs, normal download/ZIP, and social upload. Known failed MP4s are blocked by
  the media guard and excluded from artifact upload. A render exception retains
  an explicit failure rather than accepting a leftover file.
- PASS and WARNING are accepted; WARNING remains visible. Mixed jobs retain
  accepted clips while exposing failed reports. New clip metadata requires a
  fresh accepted sidecar during recovery. Historical metadata without the new
  requirement remains readable for compatibility; its normal export/recheck
  is validated before delivery.
- FFmpeg edits, caption changes/removal, hooks, translations, and reframing use
  the common post-render gate. Browser Remotion validates the actual Blob before
  exposing its download URL; rejected bytes can be rechecked without rerendering.
  The optional Node worker reports `validating` before `done` and retains FAIL
  reports on errors. Actual rendering now receives the same input props used
  when selecting its composition metadata.
- Cache identity includes file size, nanosecond modification time, validator
  version, thresholds, and expected contract. Atomic sidecar writes avoid partial
  JSON. Rechecking preserves the original expected contract. Old-version checks
  do not replace the current clip. Reports and sample measurements omit keys and
  raw FFmpeg error output.
- Only a probe timeout is retried, once, within the same deadline. No automatic
  rerender/repair is attempted; corruption and preset mismatches require explicit
  correction. Each explicit recheck has its own finite budget.

## Reports and APIs

`<export>.quality.json` contains `version`, `clip_id`, `file`, `status`
(`PASS|WARNING|FAIL`), `accepted`, `checked_at`, `fingerprint`, `expected`,
`measurements`, `thresholds`, `attempts`, and `problems`. Each problem contains
`code`, `severity`, `message`, `timestamps` in seconds, and suggested `action`.
Expected fields include `width`, `height`, `aspect`, `fps`, `duration`,
`audio_expected`, and optionally `speech_expected`. Sampled diagnostics and
effective duration tolerance are recorded for review.

- `GET /api/clip/{job_id}/{index}/quality`: fresh cached report, or null.
- `POST /api/clip/{job_id}/{index}/quality`: optional JSON `force` and `filename`;
  rechecks current/selected version without rendering. Returns the report,
  including FAIL; consumers must check its verdict. Updating the current version
  also persists its metadata/job status. An older version is checked separately.
- `POST /api/quality/browser-export`: multipart `file`, `job_id`, `clip_index`,
  JSON `expected`; validates browser bytes and cleans temporary files. Missing
  expected audio is derived from the server source and cannot be disabled by the
  client. FAIL returns HTTP 422. Render/edit delivery gates likewise return 422
  with structured report details; busy/unavailable validation does not accept
  output. Existing ownership and entitlement checks still apply.

The Node bridge invokes `export_quality.py` without a shell. It uses
`PYTHON_EXECUTABLE`, otherwise the repository `.venv`, otherwise platform Python.
Remote sources with no available local audio reference should provide
`audioExpected`; otherwise the report explicitly warns that it is unknown.

## Resource bounds and configuration

| Setting | Default | Allowed range |
| --- | --- | --- |
| `QUALITY_DURATION_TOLERANCE` | 0.35 s | 0.05–2 s |
| `QUALITY_AV_TOLERANCE` | 0.35 s | 0.05–2 s |
| `QUALITY_MAX_SAMPLES` | 8 | 3–12 |
| `QUALITY_TIMEOUT_SECONDS` | 45 s | 10–60 s |

Duration tolerance also allows two frames. FPS tolerance is the larger of 0.5
fps and 2%; display-aspect tolerance is 1%. Each sample covers at most 0.5 s,
four grayscale frames at longest edge 192, and stereo PCM at 8 kHz. Sampling
uses two decoder threads, one filter thread, a per-command timeout of at most
six seconds, and one shared wall-clock deadline. Media above 8K pixel count or
16384 pixels per dimension is rejected before sampled decoding. FFmpeg has a
256 MiB single-allocation limit; only local-file input protocols are enabled.
The API admits two validation workers, waits at most five seconds for a slot,
and retains the slot until a cancelled worker actually exits. Browser uploads
use the application's existing maximum file size and are removed afterward.

## Changed files for this task

- `export_quality.py`: shared validator, reports, cache, CLI.
- `main.py`, `app.py`, `s3_uploader.py`: render/export/status/recovery gates,
  APIs, safe media delivery, archive handling.
- `dashboard/src/App.jsx`, `dashboard/src/components/ResultCard.jsx`,
  `dashboard/src/components/ExportQualityReport.jsx`,
  `dashboard/src/lib/exportQuality.js`, `dashboard/src/lib/renderInBrowser.js`:
  dashboard reports, recheck controls, server/browser export acceptance.
- `dashboard/package.json`, `dashboard/eslint.config.js`,
  `dashboard/src/lib/exportQuality.test.js`: test command and client tests.
- `render-service/src/export-quality.ts`, `render-service/src/render-worker.ts`,
  `render-service/src/server.ts`, `render-service/src/export-quality.test.ts`,
  `render-service/src/composition-metadata.test.ts`, `render-service/package.json`:
  shared CLI bridge, status gate, worker props, and tests.
- `tests/test_export_quality.py`, `tests/test_export_quality_api.py`: real-media,
  unit, and API tests. `tests/test_reframe_endpoint.py` and
  `tests/test_rerender_endpoint.py` stub the validation seam for their deliberately
  fake render bytes; the new integration tests exercise the real validator.
  `tests/test_media_path_guard.py` verifies the new wrapper still uses the
  original media allowlist.
- `.gitignore`, `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`,
  `docs/TASK-002.md`: generated-build exclusions, configuration, and documentation.

## Verification

Tested on Windows with Python 3.11 in `.venv`, FFmpeg/FFprobe 9, and Node 24.
New real-media fixtures cover valid exports, damaged/missing files and streams,
resolution/aspect/FPS/duration errors, A/V timing, stereo phase inversion,
dark/white/static content, silence/clipping, decode failures, cache invalidation,
resource limits, and one bounded retry. API tests cover ownership, browser-byte
validation/cleanup, failed edits, ZIP/social gating, recovery, and media guards.

Commands from the repository root:

```powershell
$env:PYTHONUTF8='1'
$env:AWS_EC2_METADATA_DISABLED='true'
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py
```

In `dashboard`: `npm test`, `npm run build`, `npm run lint`.
In `render-service`: `npm test`, `npm run build`.

The optional Remotion projects initially installed incompatible patch versions
(service 4.0.446, standalone 4.0.535, dashboard 4.0.447). For verification, local
node_modules were aligned to 4.0.447 using `npm install --no-save
--package-lock=false` for service `remotion @remotion/bundler @remotion/renderer`
and standalone `remotion @remotion/cli @remotion/google-fonts
@remotion/layout-utils @remotion/media @remotion/player` (each with `@4.0.447`).
No package declarations/lockfiles were changed for that existing version issue.
Keep all Remotion package patch versions aligned when reproducing these tests.

| Check | Result |
| --- | --- |
| Final Python regression, excluding `test_mcp_stdio.py` | 984 passed, 3 existing failures, 142.15 s |
| Focused validator/API/media guard/reframe/rerender/marker/phantom checks | 102 passed, 37.64 s |
| Final validator/API run, including four malformed-sidecar cases and social failure propagation | 44 passed, 36.74 s |
| Render-service tests | 7 passed, including a real Remotion render accepted by Python and a mismatched preset rejected |
| Render-service TypeScript build | Passed |
| Dashboard export gate tests | 3 passed |
| Dashboard production build | Passed |
| Dashboard lint | Same 11 baseline errors; none in TASK-002 changed source files |

The final four malformed-sidecar cases were added after the broad run; their
validator/API selection was rerun successfully. The unchanged baseline Python
failures are:

- `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  expects a metadata-only job with no real clip to be completed.
- `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
  does not invoke its restorer on Windows.
- `test_story_director.py::test_summary_plan_repairs_provider_plan_that_exceeds_budget`
  receives a different story-summary string.

`tests/test_mcp_stdio.py` was excluded because baseline MCP setup timed out after
300 seconds; its three setup errors were documented in the baseline/TASK-001.
Dashboard lint errors remain in `public/op1.js` (5), `seo/render.js` (1),
`src/Legal.jsx` (1), `src/components/PricingPage.jsx` (1), and
`src/lib/consent.js` (3). Build warnings remain for optional OpenPanel variables,
old Browserslist data, and large chunks. These unrelated checks were not claimed
as passing. JUnit details are retained under ignored `logs/task002-*.xml`.

## Limitations and manual verification

Targeted sampling cannot prove every frame is decodable or detect every short
freeze/silent interval. A static image without an aligned moving reference is
not declared frozen. Content heuristics are warnings because fades, dark scenes,
letterboxing in the source, and still slides can be intentional. This task adds
no semantic model/OCR for judging face clipping, text importance, or aesthetics.
Size/mtime caching assumes application-controlled files; it is not a content hash.
Live Gemini generation, R2 recovery, social upload, and interactive browser codec
compatibility were not exercised against external services. No keys or paid
requests were used. Client build/unit tests do not replace a real browser UI check.

1. Start the normal backend/dashboard. Generate a clip with speech and captions;
   confirm its result card has PASS/WARNING and matching preset measurements.
2. Export a browser caption/hook version; confirm validation finishes before its
   download becomes available. Stop FFprobe temporarily and confirm it blocks
   delivery with a readable error; restore it and use recheck.
3. On a disposable generated job, replace its output with a damaged file. Recheck
   and confirm FAIL, failed job/clip state, and blocked download/ZIP/social upload.
   Restore the original bytes and recheck without generating again.
4. Try intentionally dark footage, a silent clip, and a static slide. Check that
   legitimate content is accepted and any uncertain heuristic remains WARNING.
5. Try wrong-resolution and missing-audio substitutes; inspect problem codes,
   timestamps, thresholds, and corrective actions. Reopen/restart the application
   to verify the accepted report requirement survives recovery.

Suggested commit: `feat: validate rendered exports before delivery and expose quality reports`
