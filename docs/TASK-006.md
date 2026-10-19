# TASK-006: Interactive timeline and selective regeneration

## Baseline inspection

Inspected the actual React `ClipEditor`, `ReframeEditor`, result-card caption
data, API render/EDL/transcript/subtitle/reframe routes, job and ownership
helpers, `recut.py`, caption timing/ASS generation, layout sidecars, export
validation, scene detection, dependencies and existing tests before editing.
No repository `AGENTS.md` was found. The related baseline suite passed **55
tests** (`test_recut.py` and `test_professional_captions.py`).

The editor already supported source/program monitors, draggable trims, word
snapping, splitting, removal, reordering and undo/redo. Recutting reused a clean
canonical clip when possible, or reframed from source. Missing pieces were a
saved draft/revision contract, caption/audio/scene tracks, editable caption
timing in the timeline, low-resolution composition previews, cancellation and
dependency-based artifact reuse. Whole-clip requests held an existing job lock
but did not provide an independent saved render status.

The change extends that editor and reuses its cut controls, limits, EDL order,
source lookup, authorization, metadata, caption generator, framing geometry,
layout sidecars, export validator and archive hooks. It adds three focused Python
modules and a timeline panel/helper rather than replacing the application.
No dependencies, paid API requests or Docker requirements were added.

## Implemented editor behavior

- The existing video-segment track remains interactive. A saved timeline panel
  adds a scrubber, playhead/end timestamps, waveform, caption blocks and scene
  markers. **Load waveform / scenes** explicitly samples the saved cuts.
- Select a caption block to edit its text and source-relative start/end times.
  Corrections apply to every use of that source phrase, including reordered or
  repeated segments. Blank text removes a phrase. Edited phrases use phrase
  timing and do not claim freshly aligned word timestamps.
- Caption presets reuse Clean Minimal, Bold Creator, Dynamic Highlight,
  Podcast and Cinematic, with top/middle/bottom safe placement.
- Crop controls offer preserved cached framing, a manually positioned crop with
  normalized X/Y centers, or full-image composition over a blurred background.
  Geometry uses the existing bounded crop/cover/contain helpers.
- Trims, splits, removal, reordering, caption overrides, crop and style share
  undo/redo. Drag trims commit one history step. History is capped at 50 and
  remains session-local; saved edit decisions reopen independently of history.
- **Save draft** stores decisions without rendering. **Preview 360p** generates
  a low-resolution output bounded by 360x640 without upscaling. **Export final**
  uses the current export's dimensions and frame rate. Both call the same
  compositor and caption generator. Final 1080x1920 output was tested directly.
- The classic action remains available for automatic subject tracking and
  per-scene framing. Its labels distinguish it from the timeline caption/crop
  export. New ranges lacking cached framing use a full-image blurred fallback;
  the new compositor does not rerun scene classification or subject detection.

Saved caption corrections also feed the existing transcript/subtitle modal,
classic recut and manual-reframe paths. Matching source transcript digests guard
against applying old phrase IDs to a changed transcript. `recut` now preserves
the existing `aligned` flag through timestamp remapping.

Changing cuts or crop marks editorial rankings stale. Cards suppress stale
scores and direct users to saved-analysis rescoring. TASK-005 rescoring clears
that flag without calling Gemini or rendering; caption-style-only changes do
not invalidate rankings.

## Project state and API

Each clip stores `editor_project_<index>.json` under its authorized job directory:
schema version, revision, server-derived source reference, source/clip identity,
ordered source segment decisions, caption overrides, crop/style settings, status,
progress/stage, render ID, result and error/quality details. Media/transcription
are referenced or reused rather than embedded in the draft. Source transcripts
and original clip files remain intact.

The API prefix is `/api/clip/{job_id}/{clip_index}/editor`:

| Method/path | Purpose |
|---|---|
| `GET` | Reopen saved decisions, caption phrases and status; identify stale drafts |
| `PUT` | Save `{revision, edits}` with optimistic concurrency checks |
| `POST /reset` | Reset to the current clip using `{revision}`; increments revision |
| `POST /features` | Load/cache waveform and sampled scenes for `{revision}` |
| `POST /run` | Queue `{revision, mode: "preview" or "final"}` |
| `POST /cancel` | Request cancellation of this clip's active editor render |

`edits` contains `segments`, `caption_overrides`, `crop` and `style`. Segment
times and caption override times are source-relative seconds; playback and the
caption track map them onto the assembled local timeline. Repeated source
segments are legal. All six routes reuse existing ownership/path controls.

Saves and starts use the same per-job lock as legacy edits. Revision mismatches,
active editor renders, unfinished generation and source/clip changes return
409. Metadata and draft writes are atomic. A stale draft needs an explicit
reset; it is not silently applied to a different clip. Malformed saved projects
return an understandable 409 while the existing clip remains available.

`EDITOR_TIMELINE_ENABLED=0` disables the new API; classic editor paths remain.
This is documented in `.env.example` and the Windows setup guide.

## Dependency-aware rendering

| Edit | Reused work | Invalidated work |
|---|---|---|
| Caption text/timing | Source, analysis, transcription, unchanged video parts, clean assembly | Caption derivative |
| Caption style/position | Same as text edits | Caption derivative |
| Trim/split/remove/reorder | Source analysis and unaffected cached video parts | Changed parts, ordered assembly, mapped captions/features |
| Crop position/mode | Source analysis/transcription | Parts using changed geometry, assembly and captions |
| Source/media replacement | Unchanged original stored decisions only | Fingerprint-dependent artifacts; stale draft must reset |

Part keys include file identity, bounds, crop, size, frame rate, audio and
watermark requirements. Assembly keys include ordered part keys. Caption keys
include clean assembly, mapped transcription, layout ranges and style. Cache
receipts bind finished artifacts to their size/mtime; incomplete, empty or changed
files are misses. Published projects retain part keys so later style edits can
reuse parts even after the final output receives its delivery filename.

Parts are encoded consistently, joined using the existing concat command and
then captioned only when needed. Reassembly or caption burning may still encode
the whole final clip; this is necessary when its composite pixels change.
There is no claim of arbitrary frame-level patching of an encoded MP4.

Final delivery retains the existing `recut_..._<base>_clip_N.mp4` clean filename
and `subtitled_..._<clean>` derivative conventions. Immutable cache/delivery
files use hard links where supported, with a copy fallback. Clean video remains
available for restyling; layout sidecars travel with the files. A previous legacy
render cannot reuse a stale editor clean-file marker. Final exports pass the
existing TASK-002 gate before metadata/URLs/completion are published. Failed or
cancelled renders preserve the last accepted export.

No editor operation reruns Gemini, transcription or clip selection. FFmpeg,
FFprobe and the optional existing watermark helper perform local media work.

## Job management, safety and bounds

- Two render workers; per-job serialization and revision checks protect edits
  within the existing single-process local backend.
- Progress covers changed parts, captions and validation. Polling resumes on
  reopening; an absent in-process render ID converts a persisted active job to
  `interrupted`. Valid completed cache stages remain reusable.
- Render FFmpeg children check cancellation approximately every 200 ms and are
  killed/reaped on cancellation/timeout. Individual commands have a 180-second
  ceiling within a 600-second compositor command budget. Probe, watermark probe
  and technical validation retain their existing bounded checks, so cancellation
  can wait for one of those checks to return. Shutdown signals running jobs.
- Temporary render directories and concat manifests are unique and cleaned on
  normal completion, errors and cancellation. Completed caches follow existing
  job-directory retention. A hard process/power loss may leave a temporary
  directory until job retention or manual cleanup; no broad deletion is added.
- Waveform sampling uses 8 kHz mono PCM and reduces peaks to 600 bins. The
  scene track samples small frames at 2 fps and also marks edit joins. Its
  45-second FFmpeg budget is separate from renders; fast scene cuts can be
  missed. These are sampled boundaries, not a fresh semantic scene analysis.
- Existing limits remain 12 video segments, at least 0.5 seconds each, at most
  180 seconds total. Overrides are capped at 1,000 phrases, 400 characters and
  30 seconds per phrase. Coordinates are finite 0–1; captions and ranges must
  fit the available source duration. Preset/position/mode inputs are allowlisted.
- Clients cannot submit paths, filter strings or arbitrary FFmpeg arguments.
  Source/canonical references resolve only under the authorized job or matching
  upload directory. Commands use argument lists and generated cache filenames.
- Preview/final rendering reuse existing entitlement checks; final renders use
  existing managed-action reservation/commit/release hooks when billing is enabled.

## Changed files

| Files | TASK-006 change |
|---|---|
| `timeline_project.py` (new) | Validation, revisioned decision model, caption/source mapping, dependency identities and correction reuse |
| `timeline_render.py` (new) | Bounded cancellable FFmpeg, part/assembly/caption caches, waveform and sampled scenes |
| `timeline_api.py` (new) | Authorized project routes, status/recovery, locking, preview/final jobs and gated publication |
| `app.py` | Install router, reuse timeline caption corrections in existing paths, propagate ranking invalidation state |
| `main.py` | Optional cancellable runner hook for the existing watermark helper; default behavior preserved |
| `recut.py` | Preserve explicit word-alignment provenance through source/local remapping |
| `dashboard/src/lib/editorTimeline.js` (new) | Shared bounded undo/redo, edit snapshots, split and caption timeline mapping |
| `dashboard/src/components/SavedTimeline.jsx` (new) | Caption/waveform/scene tracks, styling/crop controls, saved revisions, previews and cancellation |
| `dashboard/src/components/ClipEditor.jsx` | Reuse original cut/preview controls with shared history and saved timeline |
| `clip_ranking.py`, `dashboard/src/lib/storySelection.js`, `dashboard/src/components/ClipScoreReport.jsx`, `dashboard/src/App.jsx` | Suppress invalidated rankings, clear state on rescore and synchronize final export results |
| `tests/test_timeline_project.py`, `tests/test_timeline_api.py` (new) | Model/cache/cancellation/render/project/API tests |
| `dashboard/src/lib/editorTimeline.test.js` (new), `dashboard/src/lib/storySelection.test.js` | Undo/edit/reopening mappings and stale-ranking behavior |
| `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`, `docs/TASK-006.md` | Flag, usage, design, limitations and verification |

The repository still has no committed baseline and all files are untracked;
this table lists TASK-006 edits rather than all `git status` entries. No files
were staged or committed. No subsequent development task was started.

## Verification results

Verified on the existing Windows no-Docker environment, 2026-10-15:

- Focused Python suite: **128 passed in 31.81s**.
- Full Python regression (excluding baseline MCP stdio timeouts): **1,142 passed,
  2 failed in 135.88s**. Both failures match the established baseline:
  `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  expects completion without rendered media, and
  `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
  does not invoke restoration on this Windows environment. No new regression
  failure was observed.
- Dashboard unit tests: **18 passed**.
- Final production dashboard build: **passed in 8.60s**. Existing optional
  OpenPanel settings, old Browserslist data and chunk-size warnings remain.
- Dashboard lint: **11 baseline errors, zero warnings**. Errors remain in
  `public/op1.js` (5), `seo/render.js` (1), `src/Legal.jsx` (1),
  `src/components/PricingPage.jsx` (1) and `src/lib/consent.js` (3).
  TASK-006 frontend files are lint-clean.
- Python compilation of the changed backend modules: **passed**.

The tests exercise trims, split/reorder/removal, caption corrections/timing,
crop coordinates, undo/redo, project reopening, stale revisions/source identities,
invalid/path-like inputs, missing dependencies, interrupted status, shutdown,
cancelled child processes and cleanup, cached audio/scene samples, rejected
exports, caption-only reuse after publication, and stale-ranking rescoring.
Real FFmpeg tests check preview/full-HD dimensions and normalized crop colors,
caption rendering, technical acceptance and reuse of unaffected parts.

Commands from the repository root (use the existing `.venv`):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py --junitxml=logs/task006-regression.xml
.\.venv\Scripts\python.exe -m pytest -q tests/test_timeline_project.py tests/test_timeline_api.py tests/test_recut.py tests/test_professional_captions.py tests/test_caption_api.py tests/test_clip_ranking.py tests/test_ranking_api.py --junitxml=logs/task006-focused.xml
```

From `dashboard`: `npm test`, `npm run build`, `npm run lint`.
JUnit logs are ignored local artifacts. The known MCP stdio setup timeouts remain
excluded. The established two Python baseline failures are metadata-only job
completion and Windows static-file restoration; baseline dashboard lint has
11 errors outside TASK-006 files.

## Remaining limitations and manual verification

Interactive browser appearance, real human footage, cloud archive/restore of
draft files, managed billing and watermark delivery were not exercised end to
end for this task. Automated state/API/media tests and the frontend build are
the verified scope. Drafts/caches persist in local job directories and expire
with their existing retention; they are not a new permanent project library.
The existing local job system uses process-local locks/workers; running multiple
backend processes would require shared job coordination, which was not added.

Manual crop applies to the whole assembled clip. Use the existing per-scene
reframing editor for individual-scene subject positioning. Automatic tracking
remains in the classic path. Waveforms/scenes load on request, and feature
sampling itself is bounded rather than a separate cancellable render job.
Undo history is not persisted across page reloads. Preview and final share
decisions but differ in resolution, compression and font rasterization.

Manual checks:

1. Start the existing Windows backend and dashboard; open a generated clip's
   editor. Drag an edge, split with **S**, remove/reorder segments and check
   undo/redo plus the source/program playheads.
2. Load waveform/scenes; check their alignment against audible speech and cuts.
   Changing cuts must mark those samples stale until reloaded.
3. Select a caption block, correct its text/timing, choose a preset, move crop
   X/Y and undo/redo each change. Preview before applying the final export.
4. Save, close and reopen the editor. Check the same draft revision and decisions.
   A completed preview should reconnect; final export should update the clip.
5. Open two editors for one clip. Save in one; saving the other should return a
   revision conflict. An active render should reject competing saves immediately.
6. Start a render and cancel. Verify status and the unchanged last accepted
   video, then retry; valid completed parts should be reused.
7. After a successful final export, change only caption style and export again.
   Inspect `result.cache.segment_hits` in the saved project/API result. It should
   match the segment count while no Gemini/transcription/selection runs occur.
8. Reopen the original subtitle modal and confirm timeline text corrections.
   Trim/crop changes should hide stale editorial scores until saved-analysis
   rescoring. Test normal downloads, square/horizontal exports and classic framing.
9. Change the source or render through a legacy editor; the saved draft should
   require reset rather than silently apply to the replacement media.

Suggested commit message: `feat: add saved clip timelines and selective editor rendering`
