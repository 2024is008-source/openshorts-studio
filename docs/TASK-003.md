# TASK-003: Story-aware clip selection and boundaries

## Inspected implementation and root problems

Inspected `clip_selection.py`, `story_director.py`, `gemini_worker.py`,
`main.py`, `hooks.py`, `hook_grounding.py`, `transcribe_backends.py`, `recut.py`,
the generation API/resume settings, dashboard input/results, dependencies, and
selection/story/provider tests before editing.

The existing transcript path scores overlapping windows across the whole source
in batches, shortlists windows, and requests detailed clip ranges. Word snapping
avoids mid-word cuts but can still end an unfinished thought. A single
`predicted_score` controlled ranking, with early trimming before validation.
Errors or missing keys returned no clips. Hybrid mode already inspects every
180-second video chapter and supplies visual moments, but its text selector did
not receive that evidence. Visual chapter caches omitted transcript identity.
The duration API supported min/max bands, with no named target presets.

The smallest compatible change extends those existing helpers and call sites.
No new model, narration, cloud dependency, paid API, or architecture was added.
Existing transcription, rendering, hook compositing, and export validation remain
in use; their implementations were reused rather than replaced.

## Implemented behavior

### Complete source context and AI contracts

- All transcript windows are still scored in batches; shortlisted payloads now
  include timestamped sentences, relevant existing visual evidence, and bounded
  source opening/ending context. Hybrid analysis still watches all chapters.
  Transcript-only mode explicitly leaves visual evidence unassessed.
- The prompt asks for setup/context, conflict/challenges, humor, unexpected
  results, emotions/reactions, pacing, and resolution. It favors natural source
  openings and factual short text hooks. No generated narration is introduced.
- Optional structured `story_scores` describe the editorial factors below.
  Gemini worker JSON recovery and the in-process provider path both validate
  parsed output against the requested Pydantic schema. Nonfinite times and
  out-of-range ratings are rejected. Absolute/source-window bounds are checked
  before any cut adjustment; visual-only ranges are rejected rather than clamped
  from invalid coordinates into apparent valid clips.
- Duplicate shortlist IDs are removed. If window scores are unusable, the bounded
  shortlist is spread across the source rather than restricted to its beginning.
- Existing provider retries/batching remain bounded. Isolated blocked window IDs
  survive batch splitting and cannot be reintroduced through local fallback.

### Speech and visual boundaries

- Build sentence units from actual word timestamps, punctuation, speaker labels
  where supplied, and observed pauses. Adjacent ASR segments that continue the
  same unpunctuated utterance are joined. No new speaker diarization is claimed.
- Missing/invalid timestamps are skipped, never synthesized from text length.
  Valid timed segments can be used when word timestamps are unavailable, with
  reduced timing confidence recorded in the report.
- A cut may extend up to three seconds backward and six seconds forward to
  finish nearby speech; it is rejected if the complete sentence cannot fit the
  duration band. Overlapping speech is included as a union and checked again for
  partial-word/phrase boundaries. Up to 150 ms lead and 250 ms tail use actual
  available gaps and cannot cross adjacent speech.
- Unused leading/trailing speech pauses are trimmed. An explicitly inspected
  visual candidate keeps its quiet opening/reaction/payoff after the last word.
  Quiet scenes without intersecting speech retain their visual boundaries.
- Available `scene_cuts` in analysis can adjust speech-free boundaries by up to
  400 ms. No extra whole-video scene detection/decode is launched solely for this
  task; ordinary hybrid input uses the watched visual moment boundaries already
  produced by the existing analysis. Source-wide shot-cut metadata is optional.
- Candidate boundaries are finalized before ranking and trimming. Candidates
  remain contiguous source clips; existing highlight montage recipes retain
  their chronological source segments.

### Explainable scoring and diversity

Each selected story-aware clip has `selection_score` and `selection_report`.
The old `predicted_score` field remains available for compatibility. The dashboard
labels the displayed number **selection**, with a breakdown under **story
selection · why this clip**, and explicitly disclaims a prediction of views.

| Factor | Evidence / fallback |
| --- | --- |
| Hook strength | Provider judgment, otherwise question/number cues in actual first three seconds of word-timed speech |
| Standalone context | Provider judgment, otherwise an explicitly labeled English opening-pronoun/conjunction heuristic |
| Narrative completeness | Provider judgment, otherwise complete-ending punctuation and opening-context cues |
| Visual interest | Existing watched visual evidence; null when unavailable |
| Emotional engagement | Optional provider judgment; null when unavailable |
| Pacing | Measured speech occupancy in the selected range |
| Ending quality | Provider judgment, otherwise a sentence-ending punctuation cue |
| Redundancy | Temporal overlap and lexical similarity of ending/payoff speech |

Known factors are averaged. Target-duration deviation subtracts at most 12
points. Greedy diversity selection reevaluates candidates after each pick:
overlap above 65% of the shorter range or ending-speech similarity of at least
80% excludes a duplicate; smaller lexical similarity costs up to eight points.
Scores are editorial heuristics, not a scientifically validated viral predictor.
Reports include source excerpts, timing confidence, speech coverage, sentence
ending evidence, visual availability, pause measurements, and review notes.

### Fallback, cache, and compatibility

- Missing keys, unavailable text providers, and unusable proposals trigger a
  deterministic scan of at most 256 starting sentence positions across the
  transcript. It chooses complete source endings near the duration target and
  uses only an extracted source quote for title/hook; descriptions stay empty.
  The origin is labeled `deterministic_transcript_fallback` and no provider viral
  score is invented. It may return fewer/no clips for insufficient evidence.
- A highlight planner outage can use complete, previously inspected moments in
  chronological order, with source-derived metadata and an explicit review
  warning. If full visual inspection itself failed, highlights still fail
  honestly rather than claiming complete source analysis.
- Highlight budget repair no longer rewards source-edge coverage when no
  inspected story role supports it. This fixes the previously failing
  story-budget repair regression while retaining metadata review of the actual
  chosen montage.
- Successful text selections are atomically cached in `clip_selection.json`.
  Identity includes selection version, transcript/timestamps, source size/mtime,
  visual analysis, model/local endpoint, duration settings, story flag and clip
  count settings. A cache hit makes no new selection request and reports no new
  provider cost. Provider-outage fallback is not cached, so later runs can use AI.
- Visual chapter cache version 2 additionally includes transcript identity,
  preventing corrected transcripts from reusing stale chapter interpretation.
- `CLIP_STORY_AWARE=1` is the default. `0` retains legacy word snapping/ranking
  while keeping safe timestamp checks and optional local fallback. Existing
  transcript, hybrid, highlights, silent-video, local-LLM, hook and export paths
  remain available. No credentials are stored in the new cache identity data.

## Duration presets and API

The dashboard advanced controls offer Auto, around **15**, **30**, **45**, **60**
seconds, and **Custom** (10–150 seconds). `POST /api/process` accepts optional
`clip_target_seconds` in JSON or multipart form. Existing `clip_min_seconds`,
`clip_max_seconds`, and `target_clips` remain compatible.

A target derives a band from 75% to 120% of target, clamped to existing platform
limits and widened to at least five seconds. Explicit min/max override those
defaults and must contain the target. A target is a preference inside that band,
not a demand to cut a story at an exact second. Invalid/nonfinite values return
HTTP 400 before job enqueue. The target/band/story flag are persisted in the
resume options and output metadata.

For direct CLI runs, set `CLIP_TARGET_SECONDS` with a compatible existing
`CLIP_MIN_SECONDS`/`CLIP_MAX_SECONDS` band; API submissions derive the band for
you. For example:

```powershell
$env:CLIP_TARGET_SECONDS='30'
$env:CLIP_MIN_SECONDS='22.5'
$env:CLIP_MAX_SECONDS='36'
```

## Changed files

- `clip_selection.py`: validated speech units, sentence boundaries, scores,
  diversity ranking, deterministic fallback, batch exclusion tracking, cache key,
  finite duration settings, safe transcript windows, updated best-score helper.
- `story_director.py`: safe timed segments, transcript-aware visual cache,
  invalid visual moment rejection, inspected-summary fallback and budget repair.
- `gemini_worker.py`: optional score schema, finite/rating constraints, grounded
  story prompt, validation after JSON text recovery.
- `main.py`: source context/visual payloads, integration, caching, fallback,
  blocked-window tracking, validation ordering, metadata/resume settings.
- `generation_options.py`, `app.py`: soft targets and request/resume validation.
- `dashboard/src/components/MediaInput.jsx`, `dashboard/src/App.jsx`: duration
  preset/custom controls and API field.
- `dashboard/src/components/ResultCard.jsx`: editorial score and evidence report.
- `dashboard/src/lib/storySelection.js`, `dashboard/src/lib/storySelection.test.js`,
  `dashboard/package.json`: consistent ranking/display for new and legacy clips,
  finite-score checks, and the expanded native Node test command.
- `tests/test_story_selection.py`: new story/timing/provider/cache/preset tests.
- `tests/test_process_handover.py`: API target and recovery-manifest coverage.
- `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`,
  `docs/TASK-003.md`: flags, usage, verification, limitations and change report.

`hooks.py`, `hook_grounding.py`, `transcribe_backends.py`, and `recut.py` were
inspected and reused; no changes were needed in their rendering/transcription
implementations. Dependencies and API keys were not changed. No live Gemini or
other paid calls were used by the test suite.

## Verification

| Check | Result |
| --- | --- |
| Python regression excluding MCP stdio | 1,040 passed, 2 existing failures, 213.07 s |
| Final focused story/provider/controls/hooks/API suite | 168 passed, 56.48 s |
| Dashboard native Node tests | 6 passed, including new/legacy editorial ranking |
| Python syntax checks for all six changed Python modules | Passed |
| Final dashboard production build | Passed, including final gallery-ranking changes, 31.86 s |
| Dashboard lint | Same 11 baseline errors; no errors in changed TASK-003 source files |

The broad run preceded the final shortlist deduplication/source spreading and
fallback cost-accounting refinements; the final focused suite includes explicit
tests for those changes and passed afterward. It covers interrupted sentences,
ASR continuation, multiple/overlapping speakers, long pauses, late payoff,
quiet visual reactions, scene-cut fallback, invalid/missing timestamps, ordinary
nonviral material, provider failures/blocks, overlapping/redundant candidates,
duration presets, source/transcript cache invalidation, and legacy mode.

The previous story-budget repair failure now passes. Two unrelated failures from
the baseline remain: `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
(expects a metadata-only job to be complete), and
`test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
(Windows restorer invocation). `test_mcp_stdio.py` remains excluded because its
baseline setup timed out after 300 seconds; its setup was not changed here.

Baseline lint errors remain in `public/op1.js` (5), `seo/render.js` (1),
`src/Legal.jsx` (1), `src/components/PricingPage.jsx` (1), and
`src/lib/consent.js` (3). Existing build warnings concern optional OpenPanel
variables, old Browserslist data and large chunks. JUnit details are retained in
ignored `logs/task003-*.xml`. No full-suite or lint clean result is claimed.

Reproduce from the project root using the existing `.venv`:

```powershell
$env:PYTHONUTF8='1'
$env:AWS_EC2_METADATA_DISABLED='true'
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py
```

Focused coverage: `test_story_selection.py`, `test_clip_selection.py`,
`test_story_director.py`, `test_generation_controls.py`, `test_gemini_retry.py`,
`test_gemini_block_split.py`, `test_llm_backend.py`, `test_process_handover.py`,
`test_sparse_speech.py`, and `test_hooks.py`. In `dashboard`, run `npm test`,
`npm run build`, and `npm run lint`.

## Remaining limitations and manual checks

Sentence punctuation, timestamp gaps and lexical cues are imperfect proxies for
story understanding. Gap trimming reuses ASR timing; it does not measure the
waveform with a new silence detector. Segment-only timing is less precise. The
English context heuristic is labeled and does not claim multilingual pronoun
resolution. Emotional/visual importance and a satisfying ending still require
judgment; fallback cannot establish causal story completeness. Model metadata is
prompt-grounded, not a factual entailment proof. Reviewing the source remains
necessary for publication. Missing timestamps cannot safely support speech cuts.

No live Gemini visual quality benchmark, new source-wide cut detector, new
diarization system, browser interaction test or paid API exercise was performed.
The existing render/export tests check technical compatibility; they do not
prove a clip will engage an audience. Cache identity uses file metadata rather
than a full source-video content hash.

1. Start the normal no-Docker backend/dashboard. Use a source containing a setup,
   two-speaker exchange, long pause, reaction and late payoff. Select hybrid
   analysis and an around-30-second target.
2. Listen to the first three seconds and last sentence/reaction of each result.
   Expand **story selection** and compare source excerpts, evidence availability,
   duration, scores and warnings to the footage. Check that overlapping/repeated
   payoff clips are reduced without losing the distinct story.
3. Try 15/45/60 and a custom 37-second target; verify endings are complete within
   the allowed band, rather than exactly at the nominal duration. Set explicit
   limits to confirm incompatible targets receive a readable validation error.
4. Reuse the same source/transcript/job output directory to verify cache reuse;
   correct transcript timing or change target to confirm invalidation. Interrupt
   and resume a job to confirm duration settings survive.
5. Test local CLI text selection with no Gemini keys, and a timed ordinary
   transcript with no obvious hook. Verify source-only fallback metadata and the
   absence of invented narration. Compare `CLIP_STORY_AWARE=0` for legacy behavior.
6. Confirm existing hook overlays, captions, clip edits and TASK-002 quality
   reports still work after selection. Judge visual-only material manually.

Suggested commit: `feat: add grounded story-aware clip selection and duration targets`
