# TASK-005 — AI emotion, story and highlight detection

## Baseline and smallest compatible change

Inspected `story_director.py`, `clip_selection.py`, `gemini_worker.py`,
`clip_ranking.py`, transcription timing, `main.py` selection/summary branches,
existing audio RMS analysis in `active_speaker.py`, saved job options, metadata
and dashboard score display. The related baseline passed **142 tests**.

The existing system already watched chapters in hybrid/highlights mode, reused
transcripts, snapped speech boundaries and provided ranking. Its optional scores
did not require timestamped supporting observations. Mode labels mostly controlled
editing strategy; they did not supply five explicit selection policies. Whole-source
analysis failure also stopped highlights mode even with usable timed speech.

This task extends those existing paths. No new selection service, renderer,
dependency, mandatory Docker step, cloud vendor, or paid request type was added.

## Selection and evidence

`STORY_MODE` (or CLI `--story-mode`) accepts:

| Mode | Selection policy |
| --- | --- |
| `challenge` | Rules/goals/stakes, attempts/setbacks and observed outcome |
| `emotional` | Personally meaningful source statements and connected observable reactions |
| `comedy` | Setup, unexpected development, punchline and retained reaction |
| `podcast` | A clear question/opinion, supporting exchange and takeaway |
| `educational` | A useful problem/fact, explanation/demonstration and conclusion |
| `auto` | Provider classifies from source meaning; offline uncertainty remains `general` |

The chapter video pass and batched transcript score/detail passes share these
policies. New optional `story` schemas describe source evidence, beats and ratings.
Legacy model responses and records still work.

- Transcript evidence must match complete timed source utterances, including
  negations and punctuation, within its declared interval. Unknown IDs, invalid
  timestamps, wrong quotes and retimed fragments cannot support a score.
- Chapter-local evidence and scene-cut times are converted to original source
  seconds. Final boundaries still use existing word/sentence-aware selection.
  Evidence outside the retained clip is discarded.
- Visual/audio evidence is accepted from the actual video-inspection path. A
  text-only detail pass can reuse those observations only with the same ID,
  timestamps, channel and description. It cannot invent a trophy, reaction or
  audible laugh from transcript context or RMS energy.
- Provider instructions prohibit inferred internal states from facial appearance.
  A conservative English state/intent term guard drops such media descriptions
  and unsupported reasons. Emotional-value ratings require spoken evidence;
  a smile alone cannot establish happiness or an emotional-value score.
  Quotes describing a speaker's own feelings remain attributed source speech.
- Ideas and ending rationales use retained source quotes or media descriptions;
  ungrounded free-form `idea`/`ending_note` prose cannot introduce unseen events
  into these report fields. Provider ratings remain labeled editorial judgments.
- Opening ratings need opening evidence; context ratings need initial context;
  progression needs distinct cited beats; ending ratings need a retained
  outcome/punchline/takeaway in the last quarter. Missing metrics stay null.
- Hook suggestions use the existing complete-utterance grounding rule. Long,
  partial or unsupported headlines are omitted. This does not change independent
  animated headline rendering or create new dialogue.

The existing score/weights and redundancy logic remain the ranking path. Grounded
ratings feed its existing components, with reasons identifying their evidence.
`value` covers emotional **or informational** value. Reports additionally expose
opening quality, context completeness, value, narrative progression, visual
relevance, ending completeness and distinctness from higher-ranked candidates.
Distinctness is 100 minus the existing overlap/text-similarity measure; it is not
a semantic proof that two stories differ. Scores are editorial heuristics, not
promises of audience response.

## Source media, caching and fallbacks

Hybrid/highlights analysis continues to inspect <=180-second proxies with audio,
8 fps video and bounded retries. Optional `STORY_AUDIO_ENERGY=1` reuses the local
`active_speaker.audio_envelope` implementation on those proxies, at one RMS sample
per second. It stores source-timed relative RMS, not inferred emotion or laughter.
Scene changes are provider-observed timestamps from inspected footage, validated
to source bounds; this adds no competing shot detector or frame-render pass.

Chapter checkpoints reuse successful inspection. Keys include source identity,
transcript, model, version, story mode and audio setting. The final clip-selection
cache also includes mode and existing generation/ranking settings. Changing a mode
or transcript deliberately invalidates affected analysis. Ordinary caption/style
edits do not rerun selection. Provider fallback outputs remain uncached by the
existing selection cache so a later healthy provider can retry. Existing upload,
retry and subprocess bounds remain in force; audio sampling is optional.

Without cloud analysis, normal clip mode uses the existing deterministic contiguous
speech candidates. Highlights mode now uses that same selector to retain **one
contiguous speech extract**, saved as the existing source recipe, with explicit
warnings about unmeasured visual/semantic story quality. It does not invent causal
links by stitching disconnected speech. Missing timed speech fails clearly.
Provider safety blocks continue to propagate and are not bypassed by fallback.

## Saved records and dashboard

Each selected candidate stores `story_mode` and versioned `story_report` with:

- Original source start/end, or `source_ranges` for a montage.
- Rank, available overall score and criterion breakdown.
- Extractive main idea, timestamped evidence and retained narrative beats.
- Grounded hook suggestion and ending rationale.
- Relevant scene-cut, relative audio and speech-coverage signals when available.
- Explicit limitations and evidence provenance.

Clips retain source-order numbering for compatibility; `story_report.rank` records
recommendation order. The existing score panel exposes source evidence and missing
metrics, including summary clips without weighted rankings. React escapes source
text. Rescoring updates rank/score; a source-range change marks old story evidence
stale and the panel hides those explanations. Reanalysis is needed for a new
semantic assessment after changing source content. Pure per-shot scores are not
averaged into a claimed montage-wide story score; that measurement stays null.

## Changed files

| File | Change |
| --- | --- |
| `story_director.py` | Shared modes/schema, evidence grounding, audio context, scene times, cache version and contiguous summary fallback |
| `clip_selection.py` | Apply grounded ratings, save source reports and ranks, retain signals |
| `gemini_worker.py` | Optional shared story schema for transcript detail and silent-video responses |
| `main.py` | Mode-aware prompts/cache/CLI, silent-video grounding, highlights outage integration and saved options |
| `clip_ranking.py` | Grounded reason text, report rank/score synchronization and stale evidence flag |
| `generation_options.py` | Preserve safe story settings during job recovery |
| `dashboard/src/components/ClipScoreReport.jsx` | Story evidence, source timing, missing-metric and stale-state display |
| `tests/fixtures/story_modes.json` | Deterministic source text for five modes |
| `tests/test_multimodal_story_detection.py` | New source-grounding, mode, audio, cache, ranking and fallback cases |
| `render-service/src/story-evidence.test.ts` | Dashboard SSR compatibility/escaping tests using its own React runtime |
| `.env.example`, `LOCAL_README.md`, this report | Configuration and technical documentation |

Reviewable fixture output: `output/task005-story-reports.json`. These are synthetic
test utterances and stubbed provider judgments, **not real Gemini analysis** or
an accuracy benchmark. Output and test logs remain ignored by Git.

## Verification

- Baseline: **142 passed**, `logs/story-task005-baseline.xml`.
- Focused story/ranking/Gemini regression run: **186 passed**,
  `logs/story-task005-focused-final.xml`; the final full suite also includes the
  additional facial-state guard fixture added afterward.
- Reverification after the repeated TASK-005 request: **187 passed**, including
  that additional guard fixture, `logs/story-task005-recheck.xml`. Existing
  implementation was retained; no additional application changes were needed.
- Full Python result: **1,324 passed, 2 pre-existing failures**, with **35/35 new
  story-detection tests passed**, `logs/story-task005-full.xml`. The failures are
  `tests/test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  and `tests/test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`.
  Command: `.venv\Scripts\python.exe -X utf8 -m pytest tests --ignore=tests/test_mcp_stdio.py -q --junitxml=logs/story-task005-full.xml`.
  Three previously documented MCP stdio startup timeout tests are excluded.
- New tests cover five modes, fabricated/retimed quotes, facial-state claims,
  observed smiles, audible observations versus RMS, missing evidence, omitted
  outcomes, invalid AI scores/times, meaningful ranking, duplicates, outage recipes,
  repeatability, cache invalidation, chapter offsets, source edits and missing timing.
- A real FFmpeg-generated two-level tone verifies measured relative RMS without
  emotion/laughter labels. No speech recognition model or cloud request is needed.
- Render service: **14 tests passed**, including two SSR evidence-panel tests and
  the existing real Remotion export; `npm run build` passes.
- Dashboard: **20 tests passed**, production build passes, changed component
  ESLint passes. Full lint retains the **11 existing errors** in `public/op1.js`,
  `seo/render.js`, `Legal.jsx`, `PricingPage.jsx`, and `lib/consent.js`.
- Existing optional OpenPanel configuration, Browserslist-age and build chunk-size
  warnings remain. No interactive dashboard session, live Gemini call or semantic
  quality benchmark on the reference exports was performed.

## Manual verification

1. Start the existing Windows app with `STORY_MODE` set to a mode above. Choose
   hybrid analysis to inspect real video/audio; transcript mode leaves visual
   observations unassessed. Alternatively use the CLI:
   `python main.py -i "D:\path\licensed-source.mp4" -o output/story-review --story-mode challenge`.
2. Compare candidates against original source timestamps. Open **Story evidence**
   on the existing score panel; inspect opening, supporting beats, actual payoff,
   quotes/observations and null metrics. Confirm the saved JSON matches the panel.
3. Run the same source/settings again to check cache reuse; change transcript or
   mode to check invalidation. For repeated modes, expect fresh affected analysis.
4. Disable cloud access and generate from a timed transcript. Verify fallback
   warnings, contiguous source recipe, complete speech edges and no fabricated
   events. Missing timing/silent unanalysed footage should fail clearly.
5. Review comedy punchlines, emotional self-statements, challenge stakes/outcomes,
   explanations and podcast exchanges by listening and watching. A visible smile
   should stay an observed expression, never become a known internal state.

Semantic coherence still depends on the provider and available context. Strict
quote/range/reference checks cannot prove every visual description or rating
reason is correct. The English term guard is conservative and is not a general
emotion/intent classifier; provider instructions and human review remain necessary.
RMS can include music/noise; sparse 8 fps proxies may miss brief reactions or cuts.
No automatic laughter model, facial emotion diagnosis, diarization or new object
detector was added. Offline sentence/chronology cues do not establish real story
resolution. Unknown modes/data use safe defaults; unmeasured attributes stay null.
Existing legacy scores remain available for compatibility with their retained
provenance. No later task was started.

Suggested commit: `feat: ground story highlights in multimodal source evidence`
