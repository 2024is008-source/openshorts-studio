# OpenShorts quality and highlight improvements

TASK-001 adds bounded crop geometry, source-preserving backgrounds, conservative
scene/coverage routing, portrait vertical tracking, and configurable caption
safe areas. See [the TASK-001 report](docs/TASK-001.md) for its current checks;
the verification results further below are historical.

This copy keeps the original app structure intact and adds an OpusClip-inspired
quality path plus a whole-video highlight-summary mode.

## What changed

- **Clean social captions:** resolution-aware ASS captions, short phrase timing,
  selective green keyword emphasis, and safe escaping. The classic caption
  renderer remains available.
- **Studio export:** optional higher-quality H.264 settings and 48 kHz / 192 kbps
  AAC audio. Standard export remains the default API behavior for compatibility.
- **Subject-aware framing:** a `subject` preset biases scene selection toward a
  dominant speaker/face while preserving the existing balanced mode and manual
  reframe/editor controls.
- **Smart fill framing:** the dashboard now defaults to `editorial` on vertical
  output. On landscape group scenes, a detail crop fills the upper portion and
  a full-width view remains below it for context. This replaces the large
  blurred filler areas while retaining people near the edges. Clean captions
  sit above the context panel in these scenes. The balanced and subject presets
  remain available.
- **Hybrid clip discovery:** transcript selections can be combined with
  chapter-by-chapter Gemini visual moments. Timestamps are snapped to word
  boundaries and invalid, duplicate, or overlapping intervals are rejected.
- **Highlight summary:** the new `highlights` mode inspects the complete source
  in overlapping chapters, selects complete setup → development → payoff
  moments, and renders one chronological montage using the original speech and
  footage. No narration is generated.
- **Story continuity review:** the global planner now sees the actual dialogue
  inside each proposed moment and is instructed to follow one connected story.
  Nearby speech boundaries are included to avoid cutting a sentence in half.
  If an overlong AI plan must be shortened, the selected moments are reviewed
  again and metadata is rewritten for the moments that remain.
- **Durable processing:** analysis checkpoints live in `story_analysis.json`;
  each clip has a stable `clip_index` / `clip_id`; recovery, webhooks, editing,
  and archived links preserve those identities even when a render fails.
- **Dashboard controls:** creation mode, summary length, hybrid/transcript
  analysis, caption style, export quality, framing, and source-caption handling
  are exposed in the upload form.

## API options

`POST /api/process` accepts these additional fields:

| Field | Values |
| --- | --- |
| `generation_mode` | `clips`, `highlights` |
| `analysis_mode` | `transcript`, `hybrid` |
| `summary_seconds` | `30`–`180` |
| `caption_preset` | `classic`, `clean` |
| `quality_preset` | `standard`, `studio` |
| `framing_preset` | `balanced`, `subject`, `editorial` |

Highlight mode requires a Gemini video-analysis key. Hybrid mode falls back to
transcript selection if visual analysis is unavailable. Existing callers that
omit the new fields retain the old behavior.

## Verification

- Previous focused regression suite: **202 passed, 1 skipped**. The latest
  story-continuity patch passed targeted executable checks and compilation;
  `pytest` was not installed in the current runtime, so the suite was not rerun.
- Dashboard production build: **passed** (Vite emitted only existing environment,
  browser-data, and chunk-size warnings).
- Python bytecode compilation: **passed**.
- The editorial FFmpeg filter was rendered at 1080×1920 from a 1920×1080 test
  source and visually checked. Focused geometry, caption placement, and option
  checks passed. A source-video rerender is needed to judge shot selection.
- The supplied 58.5-second highlight was visually reviewed. It combines a
  sinking boat, a yacht tour, and a catch/game scene, and its final spoken line
  stops mid-thought. That review motivated the story continuity changes above.
- The complete test collection could not be run in this environment because the
  optional billing test dependencies (`sqlalchemy` and database drivers) are not
  installed. A direct `main.py` import also needs the app's normal media stack
  (`opencv-python`/`cv2`), which is not present in this lightweight test image.

## Suggested first run

TASK-004 adds professional caption presets, normalized word timing, sync and
line controls, safe placement and bounded caption rendering. See
[the report and sample-render instructions](docs/TASK-004.md).

TASK-003 improves sentence boundaries, story scoring, grounded local fallback,
selection caching, and approximate clip-duration presets. See
[the TASK-003 implementation and verification report](docs/TASK-003.md).

TASK-002 adds shared local post-render validation, completion/download gates,
dashboard quality reports, and revalidation without rerendering. See
[the technical change and verification report](docs/TASK-002.md). Its test results
supersede the older environment-specific testing limitations recorded above.

1. Install the existing Python and dashboard dependencies.
2. Configure `GEMINI_API_KEY` (and optionally numbered fallback keys).
3. Start the backend and dashboard as usual.
4. Try **One highlight summary** with **Video + speech**, **Clean** captions,
   **High quality**, and **Smart fill · no blurred margins**.

The original extracted app is unchanged; this directory is the improved copy.

TASK-005 adapts the existing editorial selection measurements into versioned,
weighted explanations. The dashboard adds thumbnails, evidence coverage, five
sorting modes, filters and rescoring of saved analysis without rerendering.
Missing metrics are never fabricated. See [the change report](docs/TASK-005.md)
for the formula, compatibility details, verification and remaining limits.

TASK-006 extends the existing editor with persisted revisioned drafts, caption
tracks, waveform and sampled scene markers, caption/crop controls, shared undo,
low-resolution previews and cancellable local rendering. Unchanged segment and
clean-assembly caches avoid rerunning unrelated AI stages. See
[the TASK-006 implementation report](docs/TASK-006.md).

The new scene-aware editing director TASK-001 freezes v2 analysis into a typed,
source-traceable EDL consumed by final rendering and saved-plan preview. It
reuses the existing scene, subject, layout, caption and audio-envelope helpers;
`EDIT_DIRECTOR=1` enables it without adding model requests. See
[the director report](docs/TASK-001-EDITING-DIRECTOR.md). Earlier numbered task
reports remain intact.
