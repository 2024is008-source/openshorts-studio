# TASK-004 — Advanced animated captions and word synchronization

## Inspection and scope

Inspected the existing Whisper/Parakeet transcription adapters, word alignment,
`caption_timing.py`, `caption_renderer.py`, `subtitles.py`, `clean_captions.py`,
source-to-clip mapping in `recut.py`, director caption delivery, timeline styles,
the subtitle API/editor, both mirrored Remotion caption implementations, export
validation and tests. The initial caption/transcription/hook baseline passed
103 tests (`logs/captions-task004-baseline.xml`). No new renderer, alignment model,
paid request, dependency or Docker requirement was introduced.

The existing pipeline already normalized overlapping words and supported five
older looks. Missing pieces were configurable phrase grouping/spacing, reveal
and restrained emphasis animations, continuous animation clocks across highlight
events, durable caption corrections, precise rendered previews and reuse of
final-audio alignment for dubbed clips. ASS shadows previously inherited the
optional background opacity, making shadows invisible with a transparent box.
Replacing captions on a director export could also remove its mixed headline.

## Delivered behavior

- Current looks: **OpenShorts Dynamic**, **Creator Bold**, **Clean Podcast**,
  **Cinematic**, **Minimal**. The older preset IDs remain valid.
- Professional captions use the existing FFmpeg/libass renderer. The live
  Remotion component uses matching timing, grouping, style and placement inputs.
- Default words are white. Active words use the preset/custom color only within
  measured aligned word intervals; green, yellow and cyan are selectable. Silent
  gaps and phrase-only estimates never acquire invented word highlights.
- Smooth pop, word scale, fade, word reveal, static and restrained bounce modes
  are available. Phrase animations use elapsed phrase time across successive ASS
  events. Emphasis is a small scale pulse on an explicitly marked timed word;
  the editor allows users to mark words based on their intended meaning.
- Words per phrase: 1–12, default 6. Minimum display: 150–1000 ms, default 450.
  Punctuation breaks respect that reading interval where possible. Silence,
  available frame width, maximum phrase duration and upcoming speech still bound
  groups; the setting cannot guarantee reading time for arbitrarily fast speech.
- New controls favor one/two lines; stored three-line configurations still work.
  Line spacing is 1.0–1.6, default 1.25. Existing safe font choices, color,
  outline, background, shadow, position and ±1000 ms sync controls remain.
- Captions fit frame width and mobile-safe vertical bounds. Placement checks
  detected faces over the whole phrase interval and reserves the saved headline
  band. Split/editorial placement uses existing layout metadata. Text moves once
  per phrase rather than once per highlighted word.
- New ASR results incorporate the audio stream's observed delay relative to the
  container origin exactly once. Set `CAPTION_MEDIA_CLOCK=0` for the legacy
  decoded-audio clock. Old cached transcripts are not silently reinterpreted.
- Source trim/recut offsets remain traceable through existing transcript mapping.
  Render duration clamps caption events to the final media. Dubbed clips receive
  one local transcription of their final audio, then reuse that saved alignment.
  Explicit corrections take precedence over ASR. Restyling cached dubbed captions
  neither reruns ASR nor charges for a new transcription.
- Text corrections and emphasis persist in metadata `caption_track` version 1,
  with source signature, media identity and alignment basis. Timing repairs are
  stored without the display sync offset, preventing repeated offset application.
  Changed source windows/media invalidate the cache; malformed tracks safely fall
  back. The original source transcript is retained.
- Caption replacement preserves the existing independently editable headline.
  Missing clean media produces an actionable conflict instead of stacked burns.
- `POST /api/subtitle/preview` renders up to eight seconds with the same ASS/burn
  code as final export and runs the existing quality gate. Preview leaves clip
  metadata/publication untouched. It requires a professional preset; uncached
  dubbed audio must be aligned by applying captions once first. Re-render the
  preview after changing settings. Per-job locks serialize caption/edit writes;
  stale input filenames are rejected.

## Changed files

| Area | Files |
| --- | --- |
| Timing/rendering | `caption_timing.py`, `caption_renderer.py`, `transcribe_backends.py`, `subtitles.py` |
| API and compatibility | `app.py`, `generation_options.py`, `editing_director.py`, `timeline_project.py` |
| Dashboard | `dashboard/src/App.jsx`, `dashboard/src/components/{SubtitleModal,ResultCard,MediaInput,SavedTimeline}.jsx`, `dashboard/src/lib/captionEditing.js` |
| Mirrored live/render components | `dashboard/src/remotion/{compositions/Subtitles.tsx,lib/captions.ts,lib/types.ts}`, `remotion/src/{compositions/Subtitles.tsx,lib/captions.ts,lib/types.ts}` |
| Regression tests | `tests/test_advanced_animated_captions.py`, `dashboard/src/lib/captionEditing.test.js`, `render-service/src/captions.test.ts` |
| Samples/docs/config | `examples/caption_samples.py`, `LOCAL_README.md`, `.env.example`, this report |

Generated local artifacts: `screenshots/task004-advanced-caption-presets.png` and
five 1080×1920 MP4/ASS/PNG examples under `output/task004-caption-samples/`.
These use synthetic backgrounds and fixture words; they are appearance/timing
examples, not a real-speech alignment benchmark. Both output directories and
test logs remain ignored by Git; regenerate samples with
`.venv\Scripts\python.exe -X utf8 examples/caption_samples.py`.

## Verification

- Focused Python caption/transcription/hook/director/timeline run: **204 passed**,
  including real libass renders and existing director preview/final compatibility.
- New frame tests sample actual encoded outputs at 24, 30 and 60 fps for green,
  yellow and cyan. They establish highlights during speech, no highlight in gaps
  or after speech, and frame-safe placement. Other cases cover punctuation, word
  offsets, invalid/overlapping alignment, delayed AAC, phrase grouping, all six
  animations, spacing, faces appearing mid-phrase, editable saved tracks,
  read-only previews, input limits, dubbed timing reuse and independent headlines.
- Dashboard: **20 tests passed**; all modified JS/JSX files pass ESLint; production
  build passes. Whole-dashboard lint retains **11 pre-existing errors** in
  `public/op1.js`, `seo/render.js`, `Legal.jsx`, `PricingPage.jsx`, `lib/consent.js`.
- Render service: **12 tests passed**, including a real Remotion export. Standalone
  Remotion `npx tsc --noEmit` and render-service `npm run build` pass. A ten-second
  input also produced an independently probed **8.000-second, 1080×1920** native
  caption preview. Browser launch/build checks require normal
  filesystem/browser access on this Windows sandbox; restricted attempts failed
  and successful runs used that access.
- Production build retains existing optional OpenPanel configuration,
  Browserslist age and chunk-size warnings.
- Final full Python suite: **1,289 passed, 2 pre-existing failures**, including
  **31/31 new caption tests passed**. The failures are
  `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
  and `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`.
  Command: `.venv\Scripts\python.exe -X utf8 -m pytest tests --ignore=tests/test_mcp_stdio.py -q --junitxml=logs/captions-task004-full-final.xml`.
  Three documented MCP stdio startup timeout cases are excluded. An earlier run
  caught an invalid decimal duration in the new delayed-audio fixture; it was
  corrected before this final run. No new test failures remain.

## Manual verification and limitations

1. Start the existing Windows app, open a generated clip's subtitle editor and
   choose each current preset. Try green/yellow/cyan, the six animations, one/two
   lines, phrase size, spacing and sync adjustment.
2. Correct text, mark a timed word for emphasis, render the first-eight-second
   preview, then apply. Reopen: text, emphasis and settings should persist. Try
   applying the style to multiple clips; text corrections must remain per clip.
3. Compare speech and highlights during fast speech, pauses, sentence endings and
   trimmed/recut footage. Inspect full-HD export on a phone for line readability,
   safe margins and detected face/headline clearance. Live font metrics are an
   approximation; the rendered preview is the export appearance reference.
4. Change captions on a clip with an existing headline and confirm the headline
   retains its text/timing. Check a dubbed clip: apply once, restyle, then reopen;
   no repeated transcription should occur unless the underlying media changes.

Accuracy is bounded by existing ASR timestamps. No forced aligner, speaker
diarization or automatic semantic emphasis model was added. Container start-time
correction does not repair internal audio discontinuities or inaccurate legacy
transcripts. Adding/removing words uses approximate timing inside observed slots;
those words are deliberately not presented as precisely aligned. Timeline/source
changes invalidate saved per-clip corrections rather than guessing new timing.
Font availability/glyph fallback depends on the installed Windows fonts; no fonts
are downloaded or bundled here. Extremely long unbroken tokens shrink to fit and
may need manual text/line editing for comfortable reading. Face placement is best effort from existing
bounded samples, not a guarantee for undetected or between-sample subjects. If
every safe band contains important content, manual positioning/reframing is still
needed. No interactive end-to-end dashboard session or real-speech ASR accuracy
benchmark was performed; API/render tests and synthetic frame inspection are
the verified coverage. No later development task was started.

Suggested commit: `feat: add synchronized animated caption presets and export previews`
