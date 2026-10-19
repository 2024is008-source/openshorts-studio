# TASK-006 — Intelligent clip boundaries and professional pacing

## Inspection and change

Inspected `clip_selection.py` speech units/boundaries/fallbacks, existing grounded
story evidence, `recut.py` source recipes and FFmpeg assembly, job options/API,
dashboard duration controls, director preview and saved timeline rendering.
The relevant pre-change baseline passed **152 tests**.

Existing selection already snapped words and sentence punctuation, but could keep
an incomplete ending. Transcript timing gaps were not measured silence. Source
recipes already supported internal cuts, so this change adds a final source-clock
pacing pass in `pacing.py` and reuses those recipes throughout rendering. It does
not create a second clip selector, new renderer, model, or cloud request.

## Delivered behavior

The final generation pass expands boundaries onto complete timed speech, including
overlapping speakers. A nearby connected continuation can finish an incomplete
sentence; it cannot jump over an observed scene cut, a different known speaker,
or a long gap to borrow an unrelated statement. If a connected complete ending
is unavailable, the candidate is rejected with a reason. Rejected candidates are
recorded in metadata; a job with no valid candidates fails clearly.

Grounded setup/stakes, outcomes, punchlines, takeaways, reactions and timed visual/
audio evidence are retained. A nearby inspected story can extend a candidate only
when it shares an actual timed evidence anchor. No unrelated scene is selected
just because it has an exciting label. Missing semantic evidence stays uncertain;
the pass does not fabricate story resolution. Existing watched visual ranges are
preserved conservatively when precise evidence is unavailable.

Scene alignment chooses only a nearby cut in speech-free edge margins, never a
time inside an utterance or past protected context. Sentence and word alignment
stay independent of render FPS. Source-clock decisions become the existing
`recipe.segments`; output time is their summed duration. No empty timeline segment
or black filler is added. Overlapping boundary extensions merge instead of
replaying dialogue. Automatic pacing rejects an out-of-order/overlapping input
recipe; the existing human editor still supports deliberate reordering.

### Modes

| Mode | Speech lead/tail | Internal quiet-gap policy when enabled |
| --- | --- | --- |
| Fast | 0.10 / 0.20 s | Gaps >=1.0 s; retain 0.4 s total |
| Balanced | 0.15 / 0.35 s | Gaps >=1.8 s; retain 0.8 s total |
| Emotional | 0.35 / 0.85 s | Preserve internal pauses |
| Educational | 0.20 / 0.55 s | Gaps >=2.5 s; retain 1.2 s total |

Lead/tail values are constrained by neighboring speech, known story evidence,
source limits and safe scene boundaries. Existing 15/30/45/60/custom length
targets remain soft: complete speech/context can exceed the target band, up to
the existing 180-second export limit. A meaningful ending is never truncated to
hit an exact target. Short sources can yield a complete shorter clip rather than
failing solely because the default minimum is 15 seconds. The existing 0.5-second
minimum recipe fragment still applies.

### Silence and repeated dialogue

**Shorten verified pauses** is optional and off by default. It requires all of:

- FFmpeg-measured quiet audio covering the proposed removal, at <=-42 dBFS for
  at least 0.35 seconds; transcript gaps alone do not authorize a cut.
- Complete adjacent sentences from the same identified speaker.
- No intervening scene change, protected visual/audio action or reaction.
- No intersection with any timed speech, including another speaker.
- Valid retained fragments within the existing source recipe limits.

Known emotional/comedy story timing is protected even under a faster pacing mode.
Missing speaker IDs, failed/missing audio, timeouts and unknown context preserve
pauses. No diarization dependency was added; typical transcripts without speaker
labels therefore receive boundary improvements while internal shortening remains
conservative. Exact repeated adjacent wording is flagged with source timestamps
for review, **not automatically deleted**: repetition can be emphasis or dialogue.

Silence sampling decodes only audio from selected ranges <=180 seconds, with a
45-second timeout. Successful measurements are cached by source identity/range/
threshold/version in `pacing_silence.json`, bounded to 64 entries. Failures are not
cached as silence. A normal single-range clip with shortening off does not incur
a new silence decode. Multi-range recipes use measurement to establish expected
audio before choosing the continuous assembly path.

### Audio, captions, preview and export

Paced multi-range clips seek only retained source regions, concatenate decoded
video/audio, and encode audio once. This avoids repeating AAC encoder priming/
padding at each join. Existing loudness normalization is applied once to the
assembled audio; 8 ms audio fades soften internal joins. Resampling to a common
zero origin preserves delayed source audio rather than shifting its first word
to the beginning of the picture. Straight video cuts remain the default; no new
automatic zooms or visual transitions are inserted.

The continuity decision is stored in `recipe.pacing_audio_continuity` and in the
director audio decision. Initial generation, saved director preview, rerender/
reframe, and saved timeline preview/final assembly reuse it. Cached timeline parts
remain reusable; continuity assembly gets a distinct cache key. No transcription,
Gemini selection or detector pass is rerun for an ordinary editor/style change.

Original timestamps remain in source recipes and `pacing_report`. Word transcripts
are remapped by the existing `recut.virtual_transcript`. Complete segment-only
utterances now survive that mapping without invented word timing. Partial coarse
utterances are not turned into fabricated word alignment. Word emphasis metadata
also survives source remapping. Source story reports retain their evidence, with
an explicit note that scores describe the analysis before pacing adjustments.

## Controls and compatibility

- Dashboard: **Pacing** selector and **Shorten verified pauses** checkbox beside
  generation settings. Existing duration targets remain in advanced controls.
- API: `/api/process` accepts `pacing_mode` and `trim_silence` in JSON/forms;
  malformed settings fail before processing. The safe options survive recovery.
- CLI: `--pacing-mode fast|balanced|emotional|educational`, `--trim-silence` or
  `--no-trim-silence`.
- Environment: `PACING_ENABLED=1`, `PACING_MODE=balanced`,
  `PACING_TRIM_SILENCE=0`, `PACING_ALLOW_INCOMPLETE_END=0`.
  The last flag explicitly permits intentional incomplete endings. Setting
  `PACING_ENABLED=0`, or using the existing `CLIP_STORY_AWARE=0`, retains legacy
  generation. Existing manual edit decisions do not trigger automatic re-selection.

Saved `pacing_report` includes source segments before/after adjustment, mode,
output duration, removed quiet intervals, possible repeated dialogue, warnings,
audio availability/join choice and boundary validation. Sentence completion is
null when no usable speech timing exists, rather than falsely claiming certainty.

## Changed files

| Files | Purpose |
| --- | --- |
| `pacing.py` | Final boundary/beat protection, modes, cached silence measurement and recipe planning |
| `clip_selection.py` | Complete short-source candidates below the configured minimum |
| `recut.py` | Continuous A/V joins, preserved source audio offset, coarse/word caption remapping |
| `main.py` | Final pacing validation, CLI, stored reports/recipes and rendering integration |
| `app.py`, `generation_options.py` | API/recovery controls and continuity preservation on rerender/reframe |
| `editing_director.py` | Backward-compatible saved audio continuity decision |
| `timeline_api.py`, `timeline_render.py` | Matching director/timeline previews and final assembly/cache decisions |
| `dashboard/src/App.jsx`, `dashboard/src/components/MediaInput.jsx` | Pacing controls and request fields |
| `tests/test_professional_pacing.py` | New decisions, media, failure, continuity and API/editor tests |
| `.env.example`, `LOCAL_README.md`, this report | Controls, limitations and manual verification |

No dependency files, credentials or Docker setup were changed. Old recut hooks
keep their call contract unless continuity is explicitly enabled; this was checked
against the existing layout-sidecar compatibility regression.

## Verification

- Baseline: **152 passed**, `logs/pacing-task006-baseline.xml`.
- New pacing suite: **51 passed**, `logs/pacing-task006-final.xml`.
- Focused editor/director/recut/pacing run: **89 passed**,
  `logs/pacing-task006-final-focused.xml` (before the last additional safety cases).
- Additional focused story/caption/director compatibility run: **194 passed**,
  `logs/pacing-task006-focused.xml`.
- Real FFmpeg cases verify measured silence, valid frame dimensions/content on
  both sides of joins, source audio energy, aligned A/V durations and preserved
  delayed-audio timing. Real editor preview/final exports pass the quality gate.
- Dashboard: **20 tests passed**, production build passes, changed JS/JSX lint
  passes. Repository-wide lint retains **11 pre-existing errors** in `op1.js`,
  SEO rendering, `Legal.jsx`, `PricingPage.jsx`, and `lib/consent.js`. Optional
  OpenPanel settings, Browserslist age and chunk-size build warnings remain.
- Python compilation checks pass for all modified Python modules.
- Pacing/layout compatibility: **63 passed**, `logs/pacing-task006-compatibility.xml`.
- Final full Python suite: **1,375 passed, 2 pre-existing failures**, including
  **51/51 new pacing tests passed**, `logs/pacing-task006-full-final.xml`.
  The failures are `tests/test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  and `tests/test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`.
  Command: `.venv\Scripts\python.exe -X utf8 -m pytest tests --ignore=tests/test_mcp_stdio.py -q --junitxml=logs/pacing-task006-full-final.xml`.
  Three documented MCP stdio startup timeouts are excluded. An earlier full pass exposed an old
  layout-sidecar render hook receiving an unnecessary new keyword; forwarding
  the new option only when enabled fixed that compatibility issue.

## Manual verification and remaining limitations

1. Generate licensed speech footage in each pacing mode. Try 15/30/45/60/custom
   targets, fast speech, overlapping speakers and a short source. Listen to the
   first/last words and inspect known setup/payoff/reaction timestamps.
2. Enable verified-pause shortening on a transcript with identified speakers.
   Compare `pacing_report.removed_silence` against source audio/video. Emotional
   or comedic pauses, reactions and speaker exchanges should remain.
3. Inspect the saved recipe and export, then use the existing director or timeline
   preview and final export. Confirm duration, captions and audio timing match,
   including source audio that starts after the first video frame.
4. Try an unfinished source sentence: generation should reject it with a reason.
   Use `PACING_ALLOW_INCOMPLETE_END=1` only for an intentional incomplete ending.
   Disable cloud access to verify that existing source-only fallback still works;
   disable silence measurement/unplug FFmpeg to verify no guessed quiet cuts.

Accuracy depends on available ASR/word timing, punctuation and supplied scene/story
evidence. Unknown source context cannot be semantically proved; there is no new
forced aligner, diarization or speech/laughter classifier. Low-volume unrecognized
speech/noise and between-sample visual reactions still need human review when
shortening pauses. Cut times are subject to source frame precision; VFR/abrupt
source resolution changes retain existing renderer limits and quality gating.
Repeated dialogue is detected conservatively and retained. No live Gemini request,
real-speech accuracy benchmark or interactive dashboard usability session was run;
synthetic media verifies technical timing/continuity, not narrative quality.
No later development task was started.

Suggested commit: `feat: add speech-aware clip pacing and continuous audio joins`
