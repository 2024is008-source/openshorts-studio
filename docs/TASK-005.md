# TASK-005: Explainable AI clip ranking dashboard

## Inspection and smallest compatible change

Inspected the actual selection and cache in `clip_selection.py`/`main.py`,
`gemini_worker.StoryScores`, retained transcript/visual analysis, metadata and
ownership helpers in `app.py`, generation option restoration, and the React
gallery, score helper and result cards. Existing story selection already had
seven component ratings, boundary notes and redundancy handling. It averaged
available factors equally, assigned visual interest from visual-context presence
alone, and did not retain configurable weights or an evidence-aware breakdown.
The gallery showed a total and basic story notes but lacked ranking controls.

The implementation adapts those measurements rather than introducing a model,
new render path or service. `clip_ranking.py` handles weighting and explanations;
the existing story selector remains responsible for boundaries and selection.
No dependencies, paid APIs or Docker requirements were added. Tasks 001–004
remain intact. No credentials were read into reports, committed or logged.

## Implemented behavior and formula

Scoring version **1** uses these initial editorial heuristics, with no claim of
scientifically validated viral performance:

| Factor | Initial weight | Evidence used |
|---|---:|---|
| Hook | 25% | Valid provider rating, otherwise question/number cues in timed opening speech |
| Story | 25% | Mean of available standalone-context and narrative-completeness ratings/cues |
| Engagement | 20% | Valid provider emotional-engagement judgment only |
| Visual | 15% | Valid provider visual-interest rating plus retained inspected visual context |
| Pacing | 10% | Union of transcript speech intervals divided by clip duration |
| Ending | 5% | Valid provider ending rating, otherwise final speech punctuation |

The weighted base is `sum(score * weight) / sum(available weights)`, rounded to
one decimal. Missing, Boolean, nonfinite and out-of-range scores are unassessed,
never filled with an average or reverse-engineered from a legacy total. No
available positive-weight evidence produces a null overall score. Coverage is
the percentage of configured weight supported by valid available metrics.
Configured and effective weights are both stored. Overlapping speakers do not
double-count speech occupancy.

Existing duration-target adjustments (up to 12 points) and redundancy
adjustments (up to 10 points) remain explicit, named deductions. Final scores
are bounded to 0–100. Reapplying an adjustment does not accumulate it. Rescoring
compares each candidate with earlier candidates ordered by weighted base and
original index; source overlap above 65% of the shorter clip or matching ending
speech supplies the redundancy evidence. Every retained candidate remains
accessible. Generation keeps its existing diversity selection behavior.

Each report stores the version, overall/base scores, six nullable metrics,
weights, evidence coverage, reasons, adjustments, suggested improvements and an
analysis digest. The opening is actual retained speech. The strongest moment is
the highest-rated overlapping retained inspected moment, with source and local
clip timestamps; montage/EDL source ranges map to the concatenated timeline.
Unavailable moments remain unassessed. This is not frame-level action detection.

Reasons identify provider judgments, English lexical cues, punctuation and
transcript timing proxies separately. They do not claim to measure actual
audience response, semantic payoff, audio silence or off-frame action. Legacy
visual defaults without rating provenance are not reused as measured evidence.
Gemini component schemas now reject Boolean/coerced, nonfinite and invalid scores.

## Dashboard and compatibility

- Cards retain the video preview and duration, add a cached thumbnail poster,
  and display the overall score, summary, evidence coverage, breakdown, reasons,
  opening, strongest inspected moment and suggested improvements.
- Sort by overall, hook, story, duration or original source position in either
  direction. Unknown values remain last; ties use original clip identity.
- Filter by score, duration and evidence coverage, optionally excluding unscored
  records. Defaults keep legacy and unscored clips visible. Empty filters have
  an understandable message. Filtering affects the gallery; bulk actions still
  apply to all clips, as stated beside the controls.
- Edit the six weights and explicitly rescore saved analysis without rerendering.
  Old records retain their media, URLs, timing, subtitles, identifiers and job
  status. Legacy totals stay readable until rescored; absent evidence then
  produces an honest unknown result while preserving the original prediction.
- Scoring does not change TASK-002 technical export acceptance or completion.
  `CLIP_STORY_AWARE=0` retains the existing legacy selection path.

Optional generation defaults in `.env.example`:

```dotenv
CLIP_SCORE_WEIGHTS={"hook":25,"story":25,"engagement":20,"visual":15,"pacing":10,"ending":5}
```

Exactly six finite weights in 0–100 with a positive total are required; totals
are normalized to 100%. Invalid environment configuration uses defaults. Invalid
API weights return 400 without modifying metadata. Weights are restored with
generation options and included in the selection cache key; the story selection
cache version increases to 2. Regenerating with changed options may request AI;
the explicit rescore operation only reuses saved analysis.

## API and resource bounds

| Route | Behavior |
|---|---|
| `GET /api/jobs/{job_id}/ranking` | Read stored reports, preserving unknown legacy reports |
| `POST /api/jobs/{job_id}/ranking/rescore` | Body `{}` for configured defaults or `{"weights": {...}}`; save reports and return scores |
| `GET /api/clip/{job_id}/{clip_index}/ranking-thumbnail` | Owner-authorized cached JPEG; video preview remains available on thumbnail errors |

These routes reuse existing job/path/ownership controls. Rescoring uses the
per-job edit lock, rejects queued/processing jobs, allows at most 500 candidates,
and atomically saves metadata before updating in-memory scores. It performs no
Gemini, FFprobe, FFmpeg or render request. Reweighting leaves clip order and
export state intact; the dashboard sorts its view using original identities.

Thumbnail extraction is a separate bounded FFmpeg operation using the existing
two-slot quality worker: one frame, five-second subprocess timeout, maximum 1 MiB
JPEG, scaled within 240x426. Cache keys include video fingerprint and selected
timestamp; unique temporary files avoid concurrent write collisions. Known
failed exports are not presented as valid thumbnails. Existing job-directory
retention governs these cached images.

## Changed files

| Files | Change |
|---|---|
| `clip_ranking.py` (new) | Versioned weights, nullable metrics, explanations, duplicate deductions, timeline mapping and deterministic rescoring |
| `clip_selection.py` | Reuse ranking reports in story selection, correct overlapping-speech occupancy, remove invented visual score, invalidate old cache |
| `gemini_worker.py` | Strict bounded story score validation |
| `main.py`, `generation_options.py` | Generation report propagation, cache weights, option persistence and other-mode fallback reports |
| `app.py` | Owner-authorized ranking/rescore/thumbnail routes |
| `dashboard/src/lib/storySelection.js` | Compatible score lookup, duration, stable sorting and filtering |
| `dashboard/src/components/ClipRankingControls.jsx` (new) | Sort/filter/weight/rescore controls |
| `dashboard/src/components/ClipScoreReport.jsx` (new) | Evidence-limited score explanations and moment playback |
| `dashboard/src/App.jsx`, `dashboard/src/components/ResultCard.jsx` | Gallery integration, identity-preserving score updates and thumbnail posters |
| `tests/test_clip_ranking.py`, `tests/test_ranking_api.py` (new) | Boundaries, invalid/missing evidence, duplicates, deterministic updates, access control and real thumbnail caching |
| `dashboard/src/lib/storySelection.test.js` | Sort/filter and legacy compatibility tests |
| `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`, `docs/TASK-005.md` | Configuration, usage and technical change report |

The repository has no committed baseline and all source files are untracked;
this list identifies TASK-005 edits, not every file shown by `git status`.
Nothing was staged or committed.

## Verification

Executed in the existing Windows no-Docker environment on 2026-10-15:

- Existing story/provider checks before the new tests: **112 passed**.
- Final focused ranking/API/selection/story suite: **142 passed in 24.14s**.
  Command: `.venv\Scripts\python.exe -m pytest -q tests/test_clip_ranking.py tests/test_ranking_api.py tests/test_clip_selection.py tests/test_story_selection.py tests/test_story_director.py --junitxml=logs/task005-focused.xml`.
- Broad Python regression: **1,112 passed, 2 failed in 116.47s**.
  Command: `.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py --junitxml=logs/task005-regression.xml`.
  This run preceded the final malformed-evidence/provenance tests and related
  defensive legacy-record changes; these passed in the final focused run above.
- Dashboard `npm test`: **13 passed**, including all five sorting modes,
  missing values, stable identities, combined filters and legacy compatibility.
- Dashboard `npm run build`: **passed**, 9.73s. Existing optional OpenPanel
  environment, Browserslist-age and large-chunk warnings remain.
- Dashboard `npm run lint`: **11 existing errors**, none in TASK-005 files:
  `public/op1.js` (5), `seo/render.js` (1), `src/Legal.jsx` (1),
  `src/components/PricingPage.jsx` (1), `src/lib/consent.js` (3).

The two broad-suite failures match the established baseline:
`test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
expects completion from metadata without rendered media, and
`test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
does not invoke restoration on this Windows environment.
`test_mcp_stdio.py` remains excluded because of its baseline subprocess setup
timeouts; it was not changed. No additional regression failure was observed.

API tests verify no subprocess call during rescoring, unchanged media bytes,
unchanged completed-job status and URLs, identical repeated reports, invalid
weight rejection, non-owner rejection and real FFmpeg JPEG/cache behavior.
Pure ranking tests cover 0/100 boundaries, normalized weights, missing/invalid
scores, legacy provenance, multiple-speaker occupancy, duplicate candidates,
EDL timestamps and JSON-safe malformed evidence.

## Remaining limitations and manual verification

The six factors are initial editorial heuristics. Transcript occupancy cannot
distinguish music, intentional pauses or real silence. Punctuation and English
opening cues do not establish semantic completeness. Visual/engagement metrics
remain unavailable when the original analysis did not retain valid ratings.
Reweighting cannot recover missing evidence. EDL rescoring uses virtual speech
timing; visual interest may remain unassessed while retained visual moments can
still supply a correctly mapped timestamp. Scores with different coverage should
be compared cautiously.

Live Gemini/cloud generation and interactive browser appearance were not
exercised for TASK-005. Automated helper/API tests and a production frontend
build verify the implemented paths; human visual review remains outstanding.
No new frame-level framing detector or audience-outcome model was introduced.

Manual checks:

1. Start the existing Windows backend/dashboard launchers and open a completed
   job. Check thumbnail/video fallback, duration and the expanded score table.
2. Open an old job without `ranking_report`: confirm it remains visible and
   carries a legacy explanation rather than invented component scores.
3. Try every sort and both directions; filter by score/duration/evidence and
   restore **All records / Include unscored**. Confirm editor/download actions
   continue targeting the same clips after sorting.
4. Change weights and click **rescore without rerendering**. Check coverage and
   reasons, reload the job, and confirm reports persist. Repeat with the same
   weights to verify reproducibility and unchanged video files/export status.
5. For a job with retained rated visual moments, click the strongest moment and
   verify source/local timestamps, including a montage with multiple source ranges.
6. Check a transcript-only or silent job: unmeasured visual/engagement/opening
   factors and unavailable moments must say **Not assessed**.
7. Submit all-zero weights and try a processing job; verify clear errors and
   unchanged stored metadata. Verify normal subtitle/edit/export actions still work.

Suggested commit message: `feat: add explainable clip ranking and saved-analysis rescoring`
