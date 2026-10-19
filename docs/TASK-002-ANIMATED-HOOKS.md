# TASK-002: source-backed animated opening headlines

## Inspected baseline and smallest change

The existing `hooks.py` generated PNG overlays through FFmpeg. `HookModal.jsx`
already exposed an entrance animation, but server exports ignored it, used a
different top position, and could display the hook for the whole clip. Two
Remotion compositions had a separate, FPS-dependent animation implementation.
The scene-aware director retained source speech and face/crop decisions but
rendered its headline with a fixed ASS fade. Existing layer-prefix helpers
already supported replacing/removing burned hooks without stacking them.

This change extends those entry points with one typed headline decision and
one ASS animation renderer. It does not add another scene/clip-selection
pipeline, make additional Gemini requests, change the no-Docker setup, or add
dependencies. Existing Gemini hooks are ranking hints only when they match
retained speech. Scene boundaries and the existing director's content category
contribute to the deterministic opening ranking. These are editing heuristics,
not predictions of engagement or views.

## Behavior

- Suggestions quote complete, concise retained speech starting within the first
  three seconds. Supported categories are challenge, curiosity, emotional,
  question, fact, and funny. A category filter returns no suggestion when that
  category is unsupported. Generic speech without an opening cue or a matching
  retained Gemini hint is skipped.
- Missing/invalid timing, missing transcript, interrupted phrases, oversized
  phrases, and unsuitable openings produce no automatic headline. Quotes do not
  join across discontinuous source segments. Suggested moments include original
  source timestamps where available; footage is never silently reordered.
- Manual edits must remain a complete contiguous quote from retained speech,
  retaining negations and sentence boundaries. Capitalization,
  whitespace, and line breaks may change. Unsupported claims, paraphrases, and
  invented dialogue are rejected before rendering. "Verified" means supported
  by the retained transcript, not an independent fact-check of the speaker.
- Headline state is independent of caption state: text, start/end, position,
  size, color/background preset, and animation are configurable. The existing
  Arial Bold caption font preset is reused; the new renderer never downloads
  fonts. Windows DirectWrite fell back from bundled Noto during inspection, so
  the live preview and exports explicitly use Arial (local font, not redistributed).
- Fade, scale pop, slide in, short emphasis bounce, and highlight reveal use
  millisecond timing. `none` is supported too. Long text shrinks/wraps inside a
  bounded hook region, with escaped ASS control syntax.
- The default hook band is near the top, separate from normal subtitle bands.
  Retained output-space face envelopes and known editorial regions are protected.
  Top-positioned saved caption settings also block conflicting hooks. Placement
  tries another permitted band, then skips/rejects rather than covering known
  important content. Missing detections use the predictable top safe-area fallback.
- Existing **Automatic hooks** dashboard setting / `AUTO_HOOK=0` disables
  automatic headlines while retaining captions. Default automatic display is
  up to three seconds; `AUTO_HOOK_STYLE` selects an existing preset.
- Server replacement/removal restores exact saved ASS/SRT captions or the
  director's caption plan when available. Older clips retain the existing
  transcript-based caption fallback. Missing clean media returns a conflict
  instead of stacking/relabeling a burned hook. Failed caption restoration does
  not publish the replacement.
- All server hook exports pass the existing export-quality gate. Hook changes
  and previews share the existing per-job editor lock. Stale clip filenames are
  rejected. Preview rendering is limited to eight seconds, uses a 30-second
  FFprobe timeout and a 300-second FFmpeg timeout, and retains only a fixed
  completed/partial preview filename per clip. No preview changes clip metadata.

## Dashboard and API

Open a clip's existing hook editor. Choose a supported opening type or use the
best available suggestion, inspect the source speech, edit a quote, and set
timing, top-region offset, size, color preset, and animation. **Preview export
animation** renders the same ASS headline implementation used by server exports,
on clean video. It excludes caption restoration; the interface labels this.
The immediate Remotion preview approximates text metrics; its export path keeps
existing browser caption/effect layers and validates text before rendering.

Existing `/api/hook` request fields remain accepted. New fields are
`start_seconds`, `animation`, and `y` (normalized top-region offset .04–.26).
Older requests without an animation retain a static headline, and omitted
duration retains whole-clip display, subject to current source/safety validation.
Removal does not require the old text to pass new grounding rules.

Additional owner-checked endpoints:

- `GET /api/clip/{job_id}/{clip_index}/hooks?kind=question`: suggestion, source
  context, duration, protected regions, and an explicit no-suggestion message.
- `POST /api/hook/check`: validate a proposed hook and return resolved placement.
- `POST /api/hook/preview`: bounded preview using the same `HookRequest` fields.

Existing director EDL files remain readable through defaulted optional style,
animation, category, and placement fields. Director preview and final rendering
call the shared ASS event builder. Automatic headline metadata reflects the
chosen preset/animation and records a skipped hook when no known-safe band exists.

## Changed source files

| Files | Change |
| --- | --- |
| `hook_layer.py` | Typed decisions, source mapping/ranking, grounding, safe placement, text fit, ASS animations, bounded render/preview |
| `hooks.py` | Extend existing overlay entry point with the new renderer; retain the standalone PNG helper |
| `main.py` | Source-backed auto generation and directed hook metadata |
| `editing_director.py` | Shared animated layer and context-region protection |
| `app.py` | Owner-checked suggestions/check/preview; validated, locked export; saved caption restoration |
| `dashboard/src/components/HookModal.jsx` | Source suggestions, edit controls, source context, rendered preview |
| `dashboard/src/components/ResultCard.jsx` | Validation and persistence of hook controls through existing export paths |
| `dashboard/src/remotion/compositions/HookOverlay.tsx`, `remotion/src/compositions/HookOverlay.tsx` | Five time-based entrances, display start/end, safe top positioning |
| `dashboard/src/remotion/lib/types.ts`, `remotion/src/lib/types.ts` | Backward-compatible hook schema fields |
| `tests/test_animated_hooks.py`, `tests/test_animated_hook_api.py` | New deterministic and real-media regressions |
| `tests/test_editing_director.py` | Expect complete quotes and suppression over important opening content |
| `.env.example`, `LOCAL_README.md`, this document | Configuration and technical/verification notes |

## Verification

Baseline hook tests: **37 passed** before changes. Focused hook/director suite:
**122 passed** (including real exports, 24/30/60 fps timing and audio, special
characters, multiline/long text, category selection, missing context, ownership,
stale inputs, face avoidance, preview immutability, and saved caption restoration).
After final quote-boundary/caption-asset refinements, **86 hook/director tests
passed**; the final malformed-media/API check passed **38 tests** (three already
verified real-animation cases deselected). An additional disable-auto-hooks
regression passed and confirmed caption decisions are unchanged.
Final ownership/EDL/caption-preservation review: **17 passed**. The hook-only
director regression also passed: replacing a headline cannot turn disabled
captions back on. Python compilation checks passed for all changed modules.
Full regression in UTF-8 mode: **1,228 passed, 2 existing failures** in
`test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
and `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`.
The three previously documented MCP stdio setup timeouts remain excluded.
The initial run without UTF-8 mode had five additional locale-only failures:
existing tests open UTF-8 Python source using Windows CP1252. Running Python with
`-X utf8` resolves those without changing unrelated code.

Dashboard: **18 tests passed**, changed-component ESLint passed, production build
passed, and Remotion TypeScript check passed. Full dashboard lint retains the
same **11 baseline errors** in `public/op1.js`, `seo/render.js`, `src/Legal.jsx`,
`src/components/PricingPage.jsx`, and `src/lib/consent.js`. Existing OpenPanel
configuration, Browserslist age, and bundle-size warnings remain.

A clearly labeled synthetic scale-pop sample was rendered and visually inspected:
`screenshots/animated-hooks/scale-pop-1080x1920.mp4` (H.264, AAC, 1080×1920,
30 fps), with a still at `screenshots/animated-hooks/sample.png`. These ignored
local verification artifacts use synthetic visuals/tone and do not represent a
transcription or edited export of the reference videos.

Commands (repository virtual environment on Windows):

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/test_animated_hooks.py tests/test_animated_hook_api.py tests/test_editing_director.py tests/test_director_api.py tests/test_hooks.py tests/test_hook_layers.py tests/test_hook_grounding.py -q
.venv\Scripts\python.exe -X utf8 -m pytest --ignore=tests/test_mcp_stdio.py -q
cd dashboard
npm test
npx eslint src/components/HookModal.jsx src/components/ResultCard.jsx
npm run lint
npm run build
cd ../remotion
npx tsc --noEmit
```

## Manual checks and remaining limits

1. Start the existing Windows app and open a clip containing a retained transcript.
2. Open its hook editor; select a source suggestion, insert a line break, and
   try all five entrances. Adjust start/end and the top offset.
3. Render the preview, then save. Check the actual clip at the start/end boundary,
   on moving faces, and with split/editorial layouts. Confirm caption text/style
   and audio remain present. Replace and remove the headline without stacking.
4. Attempt an unsupported claim, a category without evidence, invalid timing,
   and a restored clip missing clean media: expect a useful error/no suggestion.
5. Disable Automatic hooks and generate a fresh clip: verify no headline while
   captions continue. Reopen an older clip and confirm accessibility.

No automated detector guarantees that every important object, moving face, or
non-Latin glyph is covered correctly. Legacy detection samples output frames;
undetected information still requires the rendered-preview check. Placement
protects measured regions only. Installed font fallback determines scripts not
covered by bundled fonts. Paraphrased headlines and visual-only/no-speech hook
generation are intentionally unavailable because reliable semantic verification
is absent. No fresh Gemini call or human browser interaction was used in the
automated verification; complete interactive UX and reference-video editorial
quality remain manual checks. This task does not alter clip boundaries or
promise a stronger opening when the source has none.

Suggested commit: `feat: add source-backed animated hook editing and previews`
