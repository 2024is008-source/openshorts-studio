# TASK-004: Professional animated captions and word synchronization

## Inspection and design

Inspected `subtitles.py`, `clean_captions.py`, the transcription contract and
continuation merging, `recut.virtual_transcript`, FFmpeg/libass burning, both
Remotion caption implementations/types, subtitle editor presets, automatic
caption generation, API metadata, layout sidecars and existing caption tests.

Existing timing was duplicated across FFmpeg and Remotion. End timestamps could
extend past a trim; malformed/overlapping words were not normalized. The editor
redistributed every corrected word uniformly across the entire speech span,
including silence. Remotion added a rounded block-start offset to sequence time,
causing frame-rate-dependent drift. Font size was fixed in the modal, browser
bottom placement differed from the safer server margin, and the two Remotion
type copies had drifted.

The change retains the transcription models, no-Docker launchers, existing
renderers, legacy styles, Gemini integration and TASK-002 export gate. Two small
Python modules provide testable timing/placement and the professional ASS path;
the existing collector reuses normalization. Remotion helpers/components mirror
that contract in both existing source trees. No dependency or model download was
added, and no paid API was used for implementation/testing.

## Features implemented

- Clip-relative timestamps derive from measured absolute source words. Ends are
  clamped to clip duration; nonfinite, reversed or missing word times are skipped.
  Existing Whisper continuation fragments are merged without losing punctuation.
  Overlap truncates the earlier word at the next measured start. Equal-start
  words become an unaligned phrase because independent word highlighting cannot
  be justified. Timed segment text provides a phrase fallback; no per-word
  alignment is invented. Input transcripts are not mutated.
- Existing EDL remapping remains authoritative for concatenated trims. Edited
  captions cannot extend subtitle timing past the original clip duration.
  Professional captions support ±1000 ms sync adjustment; positive delays text.
- Punctuation, 450 ms gaps, duration, display width and a six-word cap group
  aligned words into readable phrases. Combining marks and wide CJK characters
  contribute to width calculations. Professional captions have 1–3 explicit
  lines, conservative fitting for long words, and short reading holds only where
  there is silence before the next caption. Words remain unhighlighted during
  silence. Extremely long unaligned phrases still need manual review.
- Word corrections retain observed slots and pauses. Insertions/deletions share
  existing slots rather than stretching across silence; they are explicitly
  marked approximate and do not receive a false precise-word highlight.
- Active word colors, restrained glow, a 3% emphasis motion, optional phrase
  fade, outlines, shadow and an independently drawn translucent background use
  existing ASS/libass. Unsupported effects safely fall back to static color.
  Browser time uses the global `frame/fps` clock; no rounded sequence-start
  offset is added. Render quantization remains at one video frame (ASS uses
  centiseconds); available transcription alignment remains the accuracy limit.
- The editor provides five professional presets and customization for font,
  size, text/highlight colors, outline, shadow, background, position, animation,
  maximum lines and sync. Effective server settings persist with clip metadata
  and reload into the editor. Bulk requests forward the new settings.
- Existing legacy presets stay available with their previous server renderer.
  Their browser dimmed inactive words, uppercase and word-box styles remain
  supported. Advanced line/shadow/sync controls are shown for professional looks.
  Existing Clean green-keyword and Classic auto-caption styles are preserved;
  they benefit from the shared timing fixes.

### Presets

| Preset/API identifier | Default font/1080p size | Emphasis |
| --- | --- | --- |
| Clean Minimal / `clean-minimal` | Arial, 52 px | White, soft phrase fade |
| Bold Creator / `bold-creator` | Arial, 68 px | Yellow, restrained pop |
| Dynamic Highlight / `dynamic-highlight` | Arial, 60 px | Green, restrained glow |
| Podcast / `podcast` | Arial, 54 px | Gold, dark translucent background |
| Cinematic / `cinematic` | Georgia, 50 px | Warm neutral, soft fade |

Font size scales with output dimensions and is capped against frame height. Font
families are restricted to the existing installed/system choices on the server;
unknown professional fonts fall back to Arial. No font file was added,
redistributed or fetched. Arial/Georgia and the other system families rely on
the user's OS font installation/license; libass/browser font fallback remains
available when a family or script is missing.

### Placement, performance and reliability

Professional text centers inside a conservative horizontal band with a 12% top
and 20% bottom exclusion, allowing for line height. Split scenes prefer their
seam; editorial/blurred compositions prefer the existing content boundary.
Position is selected once per phrase to avoid word-by-word movement.

Optional existing OpenCV Haar detection samples three delivered-output frames,
not source-coordinate face boxes. It uses at most six seconds, two seconds per
FFmpeg seek, and no extra AI request/model download. Normalized face regions
influence the choice among safe top/middle/bottom positions. A size/mtime/duration
cache in `<video>.caption-regions.json` avoids repeated sampling for unchanged
files. `CAPTION_FACE_PLACEMENT=0` disables this pass. Missing dependencies,
unreadable frames and detector failure return to layout-safe positioning.

Faces can be missed between samples or in profile, and every candidate position
can overlap a face. This is a best-effort avoidance heuristic, not a guarantee.
The editor receives the same layout/face regions used by the server path.

FFmpeg caption burns now have `CAPTION_RENDER_TIMEOUT` (default 300 s, bounded
30–900 s). Failed/interrupted subtitle exports receive a FAIL quality sidecar,
so partial files cannot later be selected as successfully captioned output.
The existing post-render quality gate still runs before URL publication. No
automatic repair loop or retranscription is introduced; dubbing retains its
existing fresh-transcription workflow and now supports professional rendering.

## API additions

`POST /api/process`: existing `caption_preset` accepts the five identifiers above
in addition to `classic` and `clean`.

`POST /api/subtitle` retains the existing fields and adds:

- `caption_preset`: optional professional identifier; absent preserves legacy.
- `max_lines`: integer 1–3; `shadow`: 0–8.
- `sync_offset_ms`: integer -1000..1000.
- Optional `aligned` on submitted words (default true for existing callers).

Existing `font_size` means 1080p pixels on the professional path; legacy sizing
remains unchanged. Preset-only API requests use actual preset defaults, while
explicit fields override and are sanitized/clamped. Unknown presets are rejected;
invalid line/sync limits return HTTP 422. Unsupported animation names degrade to
static rendering. Transcript responses add `aligned`, `splitRanges`,
`editorialRanges`, `faceRegions`, and saved `captionSettings`, retaining existing
`captions`, `durationSec` and language fields.

## Changed files

- `caption_timing.py`: normalized absolute/relative timing, overlap handling,
  phrase segmentation, Unicode width and safe placement.
- `caption_renderer.py`: professional ASS styles/options, active words, geometry,
  optional cached local face regions and fallback handling.
- `subtitles.py`: shared normalized collector, centisecond rollover, bounded
  FFmpeg burning. `clean_captions.py` was inspected and reuses this collector.
- `main.py`, `generation_options.py`: automatic professional caption presets.
- `app.py`: API controls, normalized transcript output, clip clamps, dubbing
  integration, saved settings, local regions and interrupted-render reporting.
- `dashboard/src/components/SubtitleModal.jsx`, `MediaInput.jsx`, `ResultCard.jsx`,
  and `dashboard/src/App.jsx`: presets, editing/customization, preview and request
  integration, saved-setting restoration and bulk forwarding.
- `dashboard/src/lib/captionEditing.js`, `captionEditing.test.js`: timing-preserving
  text edits and preset definitions/tests.
- `dashboard/src/remotion/lib/captions.ts`, `lib/types.ts`, and
  `compositions/Subtitles.tsx`, plus their matching files under `remotion/src`:
  millisecond clock, grouping, placement, animation, line limits and schemas.
  Mirrored type synchronization retains existing hook/style fields.
- `render-service/src/captions.test.ts`, `composition-metadata.test.ts`: timing,
  safe placement and real captioned Remotion render verification.
- `tests/test_professional_captions.py`, `test_caption_api.py`: timing/style/API
  tests and real FFmpeg rendering.
- `examples/caption_samples.py`, `screenshots/task004-caption-presets.png`:
  reproducible full-HD samples and reviewed contact sheet.
- `.env.example`, `LOCAL_WINDOWS_SETUP.md`, `IMPROVEMENT_NOTES.md`,
  `docs/TASK-004.md`: usage, flags, verification and limitations.

## Verification and samples

| Check | Result |
| --- | --- |
| Python regression excluding MCP stdio | 1,068 passed, 2 existing failures, 207.09 s |
| Final caption/API/subtitle/layout/export integration selection | 87 passed, 81.64 s |
| Final caption timing/render/sampling/cache selection | 26 passed, 2.06 s |
| Dashboard native Node tests | 9 passed |
| Final dashboard production build | Passed, 13.60 s |
| Dashboard lint | Same 11 baseline errors, none in TASK-004 changed source |
| Render-service tests | 10 passed, including actual captioned Remotion export and quality gate |
| Render-service TypeScript build | Passed |
| Standalone Remotion TypeScript no-emit check | Passed |
| Changed Python syntax / mirrored Remotion sources | Passed / matched |
| Five sample exports | 1080×1920, 30 fps, 2.5 seconds each; FFprobe checked and contact sheet reviewed |

The full run preceded the last settings-restoration/interrupted-output refinements
and caption API tests. Those paths were tested in the final focused selection.
The final bounded face-sampling/cache test was added afterward and all caption
tests were rerun successfully. No complete regression pass is claimed.

Unrelated baseline failures remain:
`test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
(expects metadata-only completion without a video), and
`test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`
(Windows restore invocation). `test_mcp_stdio.py` remains excluded because its
baseline setup timed out after 300 seconds.

Lint errors remain in `public/op1.js` (5), `seo/render.js` (1), `src/Legal.jsx` (1),
`src/components/PricingPage.jsx` (1), and `src/lib/consent.js` (3). Existing build
warnings cover optional OpenPanel environment variables, outdated Browserslist
data and large chunks. JUnit details are retained in ignored `logs/task004-*.xml`.

The full regression command excludes the previously documented MCP setup
timeouts:

```powershell
$env:PYTHONUTF8='1'
$env:AWS_EC2_METADATA_DISABLED='true'
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/test_mcp_stdio.py
```

Focused tests cover fast/slow speech, silence, punctuation, nonfinite/missing and
overlapping timing, trim/offset clamps, segment fallback, long words, CJK/Cyrillic,
split/editorial placement and face collision, mirrored sources, preset settings,
API validation/persistence, interrupted output, and real libass renders at
24/25/30/60 fps. Native Node tests verify edit timing and settings; Remotion tests
exercise the new helpers and an actual captioned render through TASK-002's gate.

Generated and visually reviewed five 2.5-second MP4 style samples at **1080×1920,
30 fps**; all five were confirmed with FFprobe. They use synthetic background
media and supplied demonstration timestamps, not a claim of measured ASR
accuracy against a real speaker.

![Professional caption presets](../screenshots/task004-caption-presets.png)

Samples are under the ignored `output/task004-caption-samples/` directory:
`clean-minimal.mp4`, `bold-creator.mp4`, `dynamic-highlight.mp4`, `podcast.mp4`,
`cinematic.mp4`, plus ASS, PNG and transcript files. Recreate with
`.\.venv\Scripts\python.exe examples/caption_samples.py`.

## Remaining limitations and manual verification

Alignment quality is limited by the existing ASR. A segment-only fallback cannot
identify the spoken word; inserted/deleted text needs manual timing review.
Extremely long unbroken text may shrink to remain inside bounds. Fonts/glyphs,
complex scripts and antialiasing can differ by OS and between libass and Chromium;
the renderers have equivalent timing/safe areas, not guaranteed pixel parity.
Fast speech can outrun comfortable reading; minimum holds never obscure later
speech just to satisfy a display-duration target. Sampled face avoidance cannot
guarantee every face stays clear. Legacy presets retain their original layout
behavior; choose a professional preset for the new placement/line controls.

No new alignment model, paid API, forced retranscription or font installation was
added. Interactive browser/export codec behavior, live dubbed-provider workflows
and publication on actual mobile platforms still need manual checks. Tiny API
fixtures use x264 because their 64×36 height is below NVENC's supported minimum;
the full-HD samples use x264 as well.

1. Generate a portrait clip, choose each new preset, and compare its opening,
   fast speech, pause and ending against the audio. Test 24/25/30/60 fps exports.
2. Open subtitles; change font/size, colors, outline/shadow, opacity, position,
   animation, line limit and ±100 ms sync. Confirm preview and server export;
   close/reopen to check saved settings. Try apply-to-all and TASK-002 validation.
3. Correct one word and confirm later words do not shift into silent gaps. Add
   words and inspect the explicitly approximate timing. Try a trimmed/EDL clip.
4. Test two speakers in split layout, blurred/editorial framing, a detected face
   in the lower safe area, and detection disabled/unavailable. Review text bounds
   on a real mobile player with platform controls visible.
5. Compare older Classic/Clean/editor presets and existing hook/caption/export
   workflows. Try timed segment-only text, missing timing and non-Latin scripts;
   inspect fallback fonts and flag text that needs manual alignment.

Suggested commit: `feat: add professional caption presets and reliable word timing`
