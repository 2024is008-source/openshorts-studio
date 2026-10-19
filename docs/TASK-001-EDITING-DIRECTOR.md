# TASK-001: AI scene-aware editing director

Date: 2026-10-16, Asia/Colombo. This is the new director task. The earlier
`TASK-001.md` smart-reframing report and Tasks 002–006 are preserved.

## Inspection and design

Before editing, inspected the current Gemini chapter schema/cache and selection
in `story_director.py`, `gemini_worker.py`, `clip_selection.py` and `main.py`;
v2 scene classification, subject trajectory and native FFmpeg layouts;
`layout_picker`, split/editorial/screencast/inset layouts; caption timing and
ASS rendering; hook grounding; audio envelopes/punch-ins; the saved timeline,
preview, ownership and technical export gates. No `AGENTS.md` was found.
The relevant baseline suite passed **122 tests** before changes.

The existing v2 renderer already performed an analysis pass followed by an
FFmpeg render pass. However, it kept scene layouts, trajectories and source
timing in transient Python arrays. Captions/hooks were decided independently
afterward, and a preview could not replay the complete generated decisions.

The smallest compatible change freezes that analysis/render boundary into a
validated EDL, adds a replay function beside the current v2 renderer, and routes
directed generation and its preview through it. Existing detectors, classifiers,
geometry, caption generator, selection, metadata, caching and export validation
are reused. There is no second AI planner, transcription engine or scene
classifier. The previous renderer remains the feature-flag fallback.

## Reference inspection

Both supplied Downloads videos were accessible and probed locally:

| Reference | Duration | Technical format |
|---|---:|---|
| Eating A Store For $1,000,000 Challenge!.mp4 | 17.72s | 1080x1920, H.264, AAC, 30000/1001 fps |
| One Million Calorie Challenge_ Running for Family!.mp4 | 30.30s | 1080x1920, H.264, AAC, 30000/1001 fps |

Inspected sampled contact sheets at four-second intervals. Visible patterns
include cropped portrait subjects, preserved wide shots over blurred backgrounds,
bold white/active-color phrase captions and short top headlines. The calorie
reference also alternates reaction close-ups and full-body/action views. These
are sampled visual observations; full audio, transcript accuracy and detailed
frame-by-frame pacing were not reviewed. Unfilled black cells in the first
contact sheet are contact-sheet placeholders, not evidence of black video frames.
Local sheets are ignored artifacts at
`screenshots/reference-director/reference-0.jpg` and `reference-1.jpg`.
The reference footage was not uploaded to a service, used as unrelated material
in generated clips, or added to tests/distributable assets.

## Configuration and compatibility

```dotenv
EDIT_DIRECTOR=1
EDIT_DIRECTOR_STRATEGY=auto
```

Direction is opt-in, default off. Restart the existing Windows backend after
changing its environment. `EDIT_DIRECTOR=0` retains the previous generation
path and v1/v2 fallback behavior. Directed renders use v2 and surface invalid
decisions/render failures rather than silently replacing a validated plan with
an unrelated v1 composition. Existing horizontal exports retain their original
passthrough path. Directed portrait output defaults to 1080x1920; square remains
square. Explicit `REFRAME_OUTPUT_SIZE=source` retains the existing source-size
policy. H.264 and source-appropriate frame rate are retained; mapped audio is
encoded as AAC. Legitimately silent sources do not gain invented audio.

`EDIT_DIRECTOR_STRATEGY` accepts `auto`, `challenge`, `emotional`, `comedy`,
`podcast`, `educational`, or `general`. Configuration is included in resumable
job options. `auto` uses valid overlapping `editing_kind` labels from retained
Gemini video analysis, or `general` when those labels are absent. It does not
trigger a new Gemini request. Existing optional hybrid/highlights analysis and
its cache/usage policy remain unchanged. Old caches remain usable; missing new
fields are not a reason to purchase another analysis.

## EDL contract

`editing_director.EditPlan` is a strict Pydantic schema. Its generated JSON
schema is available to Python callers via `EditPlan.model_json_schema()`.
The final clean clip stores a validated `<clean-clip>.mp4.edit.json` sidecar.
Clip metadata records `edit_decision_file`, `editing_strategy` and the generated
delivery filename. The plan includes:

- Schema version and source basename/file identity, source dimensions/duration,
  selected source segments and their assembled clip intervals.
- Source and local timestamps for every shot and caption. Ordered segments
  remain traceable even in a montage or reordered timeline.
- Shot layout, concrete renderer capability, bounded source regions and crop
  keyframes. Each shot's keyframes restart at local time zero.
- Caption text/timing/alignment provenance and the professional style reference.
  The existing ASS phrase/highlight implementation consumes these words.
- A short opening-source quotation and its display interval when `AUTO_HOOK=1`.
  The EDL does not use an unverified model-written headline. If source speech is
  unavailable, it does not invent a headline. `AUTO_CAPTIONS=0` is respected.
- Relative audio-energy windows, measured quiet intervals, neutral gain and
  the decision to retain original audio. Quiet windows do not imply that a
  pause should be removed. Missing audio analysis is explicitly unavailable.
- An explicit preserve-ending strategy, final boundary and speech-punctuation
  evidence, without claiming that punctuation establishes semantic resolution.
- An empty optional-transition list: natural source cuts are preferred.

The existing clip selector remains responsible for selecting complete stories
and aligning boundaries. This task coordinates its selected segments; it does
not introduce a competing selector or fabricate new dialogue/payoffs.

### Layouts and policy

| Public layout | Existing capability reused | Decision |
|---|---|---|
| TRACK | v2 crop/sendcmd and existing camera/tracker | Follow the primary subject with shot-local bounded keyframes |
| CENTER | Static v2 crop | A stable centered trajectory needs one keyframe |
| BLUR | Existing cover/contain blurred composition | Preserve the full image where a crop is unsafe/unknown |
| SPLIT | Existing split geometry | Two independent detected/manual source regions |
| EDITORIAL | Existing detail+context, screencast or camera-inset geometry | Preserve context alongside subject/detail |

Native screencast/inset/full-width capabilities are explicit validated renderer
variants of those five public layouts, rather than removed working modes.
Audio speaker-cut trajectories replay as TRACK decisions. Context-preserving
BLUR always fills the output with source-derived cover/contain geometry.

| Strategy | Concrete coordinated policy |
|---|---|
| Challenge | Bold Creator captions; unsafe/unknown wide shots use detail plus full context; selected challenge/result order preserved |
| Emotional | Cinematic captions; preserve selected reactions, spoken conclusion and intentional pauses |
| Comedy | Dynamic Highlight captions; preserve setup, punchline and reaction timing from selected source edits |
| Podcast | Podcast captions; use stable tracked/centered shots and only independently detected two-person splits |
| Educational | Clean Minimal captions; unsafe wide shots preserve demonstrations/objects via full-context editorial composition |
| General | Clean Minimal captions and conservative existing subject/context routing |

An explicit supported `CAPTION_PRESET` overrides the strategy's caption style.
These are conservative editorial policies, not claims of genre recognition or
automatic semantic quality beyond the retained analysis.

The existing Gemini chapter response now optionally supplies a closed-enum
`editing_kind` and strict Boolean `preserve_context`. The latter is honored only
for an overlapping inspected moment with retained visual evidence. It forces
context preservation before tracking. Optional invalid or missing metadata is
ignored or rejected by the existing structured-response validation, with the
general/director fallback using valid existing detector output.

## Scene and caption behavior

- Reuse the existing shot detector and subject classifier/face/person detection.
  Tracking resets at every shot even if the old `SCENE_CUT_RESET` setting is off.
  Selected segment joins are also explicit reset boundaries when visual scene
  detection did not find a cut there.
- Scene layouts are fixed across a shot, avoiding per-frame layout oscillation.
  Existing camera smoothing and missing-subject fallback remain in use.
- Regions/keyframes are clamped from existing geometry, then validated against
  source dimensions. No trajectory interpolates through a different shot.
- Source joins near a frame boundary retain their exact source decisions and
  avoid creating artificial subframe shots. Numeric source-map values are
  rounded consistently for deterministic serialization.
- Reuse measured face boxes from the existing tracking analysis, map them to
  output crop/layout coordinates, and pass their conservative occupancy envelopes
  to the existing caption placement helper. Split/editorial bands and headline
  space are reserved through the same caption geometry. Missing detections use
  the existing mobile safe-area fallback.
- Audio energy is measured with the existing envelope helper. When punch-ins
  are enabled, the existing punch-in policy consumes that same envelope instead
  of decoding it a second time. Crop zoom boxes are frozen into the EDL.

## Validation and security

Before rendering, validate finite bounded dimensions/fps, valid selected source
ranges, contiguous clip coverage, shot-to-segment references and source mapping,
renderer/layout compatibility, independent split regions, region bounds, ordered
shot-local crop keys, caption source/timing references, grounded hook content,
audio ranges/gain and the final ending boundary. No EDL can reference a missing
selected segment, unsupported filter/transition or arbitrary source path.

Replay checks prepared media dimensions/duration and validates output aspect.
It constructs FFmpeg arguments from allowlisted capabilities and numeric
geometry, never AI filter strings. Small outputs below NVENC's size limit use
local libx264 rather than failing after a successful GPU probe.

API replay additionally requires existing job ownership/entitlement checks,
valid in-job sidecar paths, an unchanged generated clip and matching retained
source basename/fingerprint. A manually edited clip rejects the old plan as
stale. Missing or malformed sidecars return clear 404/409 errors. No API keys,
absolute source paths or credentials are stored in the plan.

## Shared final and preview path

`reframe_v2.render` performs its existing analysis, compiles the EDL and calls
`render_decisions`. Generation then calls `editing_director.render_layers` for
the EDL's captions/headline, and the existing quality gate validates the complete
export before publishing `CLIP_READY` and completed status. The directed branch
does not call legacy hook rewriting or independently decide captions afterward.
Watermark, clean/derived filenames and metadata conventions are retained.

The existing saved timeline editor adds an expandable **Generated editing
decisions** report and **Preview generated director EDL** action:

- `GET /api/clip/{job_id}/{clip_index}/editor/director` returns the stored plan.
- `POST /api/clip/{job_id}/{clip_index}/editor/director-preview` reconstructs the
  selected source segments and calls the same `render_decisions` and
  `render_layers`, bounded to a 360x640 preview with preserved aspect.

Replay does not invoke scene/subject detection, Gemini, transcription or clip
selection. It uses the existing quality worker and per-job edit lock, allows
clips up to 180 seconds, bounds FFmpeg commands to 120 seconds within a
300-second command budget, validates the preview and caches it by the full
decision digest. Owned temporary files are cleaned. Final media, job completion,
draft edits and metadata are not changed by preview.

The regular timeline preview continues to represent new manual edits. Generated
EDL replay is labeled explicitly as the saved generation, not unsaved timeline
changes. Retained source is required; ordinary video playback remains available
when replay cannot be reconstructed.

## Changed files

| Files | Change |
|---|---|
| `editing_director.py` (new) | Strict EDL models, deterministic source mapping, strategies/context adaptation, audio evidence, saved decisions and shared caption/headline consumption |
| `reframe_v2.py` | Freeze existing detector analysis, reset at cuts/joins, replay EDL via existing native geometry, AAC mux, tiny-preview encoder fallback |
| `main.py` | Opt-in generation context, EDL/layer rendering and existing validated completion publication |
| `story_director.py` | Optional structured genre/context fields in existing Gemini response/prompt |
| `punch_in.py` | Reuse an already measured audio envelope without changing the old policy |
| `recut.py` | Optional internal encoder arguments for low-resolution directed source assembly; defaults preserved |
| `generation_options.py` | Restore nonsecret director settings across interrupted jobs |
| `timeline_api.py` | Read/replay saved generated decisions with ownership, source validation, caching and existing export checks |
| `dashboard/src/components/SavedTimeline.jsx`, `ClipEditor.jsx` | Generated decision inspection and program-monitor preview integration |
| `tests/fixtures/director_signals.json` (new) | Deterministic transcript, source segments and retained visual-context fixture |
| `tests/test_editing_director.py`, `tests/test_director_api.py` (new) | Schema/strategy/source mapping/cuts/layout/media/generation/API regression coverage |
| `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`, this report | Configuration, usage, technical changes and verification |

The repository has no committed baseline and all files are untracked. This is
the task-specific changed-file list; nothing was staged or committed.

## Verification

Verified on the existing Windows/no-Docker environment:

- Pre-change baseline: **122 passed** in the related scene, framing, story and
  caption tests.
- Final focused suite: **147 passed in 45.96s**. Includes the real CLI generation
  body with deterministic selection, actual media rendering/technical validation,
  all seven native layout adapters, source mapping, missing AI, invalid decisions,
  cut resets, tiny-preview encoding, API ownership/staleness and cached replay.
- Full Python regression: **1,187 passed, 2 failed in 143.73s**. Both failures
  match the established baseline:
  `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  expects completion without rendered media; and
  `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
  does not invoke restoration on this Windows environment. No additional
  regression failure remains in this run.
- Dashboard unit tests: **18 passed**. Production build: **passed**, with the
  existing optional OpenPanel settings, Browserslist-age and large-chunk warnings.
- Dashboard lint: **11 baseline errors, zero warnings**: `public/op1.js` (5),
  `seo/render.js` (1), `src/Legal.jsx` (1), `src/components/PricingPage.jsx` (1),
  `src/lib/consent.js` (3). Changed director UI files have no lint findings.
- Changed backend module compilation: **passed**.

The final media assertions use the validator's actual `DARK_BORDERS` finding
code to check unintentional dark edges on all seven layout adapters; this
strengthened assertion was rerun separately after the full suite.

Commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_editing_director.py tests/test_director_api.py tests/test_recut.py tests/test_story_director.py tests/test_reframe_v2.py tests/test_punch_in.py --junitxml=logs/editing-director-focused.xml
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py --junitxml=logs/editing-director-regression.xml
```

From `dashboard`: `npm test`, `npm run build`, `npm run lint`.
Python compilation checks include all changed backend modules. Logs and sample
contact sheets are ignored local artifacts. Existing MCP stdio setup timeouts
remain excluded; these transport tests were not changed.

## Remaining limitations and manual checks

Real-media tests use synthetic footage with deterministic detections, including
the real CLI generation body and real FFmpeg preview/final output. Live Gemini
classification, subjective quality on the entire references, interactive browser
appearance, cloud sidecar archival/restoration and managed billing remain
unverified. The local sidecar persists with existing job-directory retention.

Semantic story completeness still depends on the existing selector and available
Gemini context. Missing quiet/face data does not prove silence or subject
absence. Quiet intervals are relative-energy evidence, not absolute silence or
an automatic removal instruction. Automatic gain remains neutral; no unrequested
music, transitions, dialogue or visual inserts are added. Genre policies do not
claim scientifically established engagement gains.

Manually verify:

1. Enable the director, restart the normal no-Docker app and generate clips from
   licensed footage. Test both transcript-only and existing hybrid modes.
2. Inspect the saved `.edit.json`: source ranges, local shots, independent crop
   keys, caption source timestamps, style, hook quotation and ending strategy.
3. Open the existing editor and preview the generated EDL. Compare its layouts,
   crop direction, captions and headline interval with the final export.
4. Try a challenge/educational full-context moment, moving single subject,
   simultaneous two-person shot and face-free shot. Confirm context is retained
   and framing resets at unrelated cuts and montage joins.
5. Confirm unknown/silent footage produces no invented hook/audio, captions
   remain in safe regions and source darkness is preserved.
6. Edit the clip afterward; old generated replay must return a stale-plan
   message. Test normal timeline preview, subtitles, download and legacy modes.
7. Disable the flag and verify the prior export flow remains available.

Suggested Git commit message:
`feat: coordinate scene-aware editing with validated source-traceable EDLs`
