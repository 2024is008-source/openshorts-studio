# Autonomous editing director — implementation report

The existing Gemini → clip selection → v2 framing → caption/template → quality
pipeline now stores and applies scene-aware effect decisions. There is no new
generation service or competing renderer. Default profile: **Balanced**.

## Effects and evidence

Timed adapters cover smooth pushes/pulls, punch-ins, snap zooms, controlled zoom
bounce, restrained shake, motion blur, fades, kinetic captions, word pop/reveal,
grounded keyword/number emphasis and dialogue normalization. Existing face/subject
tracking, scene-aware crop, split/inset/wide/blur layouts, source-backed hooks,
natural cuts, loudness mastering and imported-music ducking remain the foundation.
Tracking effects reuse the existing subject path; they do not identify a new
reaction target or create another tracker.

Automatic choices are deliberately narrower than the available adapters:

| Evidence | Automatic choice |
| --- | --- |
| Timed explanation | Gentle push, if retained faces/objects remain inside the crop |
| Timed surprise | Brief bounded punch-in; exact spoken quote can receive emphasis |
| Visible reaction | Bounded snap zoom when the existing subject crop is safe |
| Reveal | Controlled pull-back within the validated composition |
| Action | Reuse existing subject tracking and preserve context |
| Spoken number | Emphasize an exact retained quote containing a digit |
| Serious dialogue/story | Keep natural timing; suppress added camera/text effects |
| Explicit pause + measured quiet interval | Cinematic fade only at the shot opening |
| Missing/uncertain evidence | Preserve the existing composition; add no effects |

Gemini's existing schema adds bounded timed cues with visible evidence, exact
speech quotes and confidence. Chapter-local timestamps are converted once to
source time. Source selection maps them to assembled clip seconds. The saved
scene records include subjects, important regions, speech, observations, crop
motion, relative audio peaks, quiet intervals, transition provenance and
confidence. Crop-path motion is not presented as physical camera motion, and
loudness peaks are not presented as music beats.

Each effect stores its ID, type/category, source scene, clip-local interval and
duration, intensity, easing, normalized anchor, optional subject target, reason,
confidence, editable parameters, origin and enabled state. Limits bound count,
spacing, magnification, shake, duration and evidence sensitivity. Animations
return to their base composition inside the shot; face/object bounds veto zoom.
Caption reservations include the additional camera movement envelope.

## Editor and persistence

Video Editor → **Properties → AI Edit** provides enable/category switches, all
five profiles, editable limits, regeneration, removal, effect selection, timing,
intensity, and preview. Camera and text decisions appear on the existing timeline.
Existing undo/redo and autosave include these decisions. Regeneration retains
manual overrides and uses cached observations without transcription or Gemini.
Trim/reorder maps retained effects through source ranges; animations intersected
by a trim are skipped rather than played in fragments.

Preview/export share the same decisions and filter/caption adapters. Template
generation and caption-free delivery retain visual effects. A separate clean
base prevents effects from accumulating during later exports. Cache keys include
effect decisions; text-only changes reuse video segments. Manual crop changes
disable inherited extra camera effects because their previous geometry no longer
proves that the new crop is safe. Filter failures have one fallback to the base
composition with a local skip receipt; cancellation continues to propagate.
Existing post-render quality validation remains mandatory.

## Validation and performance

- 250 targeted Python regression checks passed, plus the final scene/effect
  checks recorded in the task response; 55 native unit tests passed.
- CPU and actual NVIDIA NVENC effect encodes passed frame-rate, duration, output
  size and audio-availability checks. Preview/final API tests passed the output
  quality gate, including caption-free effects and later effect removal.
- Native acceptance passed undo/redo, manual override preservation, regeneration,
  save/reopen, rendered preview, responsive layout and native video playback:
  `build/auto-director-native-final/auto-edit-result.json` and `visual-result.json`.
- A 500-run tiny synthetic decision fixture averaged about **0.20 ms** per call
  on this host, with no decoder or provider calls. This is not an end-to-end video
  benchmark. A visual-effect pass adds an encode only when needed; valid parts
  and effects are cached. Provider analysis latency was not benchmarked.
- No paid Gemini calls were made, no models or dependencies were downloaded,
  and no API credentials were embedded.

## Remaining limits

This does **not** implement all 35 requested effects as independently editable
timed layers. Whip pans, freeze frames, speed ramps, slow motion, cross dissolves,
beat cuts and directional transitions remain skipped. Whoosh/impact/pop assets
are not bundled. Existing layout/hook/music controls manage their native
composition; arbitrary timed overrides of those controls are skipped explicitly.
Noncentral extra zoom anchors are skipped. Motion blur and shake adapters are
available but are not selected automatically without a suitable implemented rule.
Gradual-transition classification and new reaction-subject selection are not
implemented. Fresh Gemini response quality has not been tested against paid
requests. Old caches without new cues use the deterministic fallback.

## Updated files

- `auto_edit.py`, `assets/auto_edit_profiles.json`: decisions, safety limits,
  interpolation, timeline mapping, shared effect adapters and skip receipts.
- `story_director.py`, `editing_director.py`, `main.py`: validated cue analysis,
  retained plans and generation/template integration.
- `caption_renderer.py`, `video_templates.py`: timed caption animations.
- `timeline_project.py`, `timeline_render.py`, `timeline_api.py`: persistence,
  cache dependencies, regeneration and shared preview/export.
- `native/OpenShorts.Desktop/AutoEditWorkspace.cs`, `AutoEditPanel.xaml` and
  `AutoEditPanel.xaml.cs`: editor controls and effect rows.
- `MainViewModel.cs`, `EditingWorkspace.cs`, `EditorStudioWorkspace.cs`,
  `EditorInspector.xaml`, `EditorAssetsPanel.xaml`, `EditorTimelinePanel.xaml`,
  `TimelineSurface.cs`: existing history, controls and timeline integration.
- `EditorVisualTest.cs`, `tools/prepare_auto_edit_smoke.py`,
  `tests/test_auto_edit.py`, `tests/test_auto_edit_api.py`: local acceptance tests.

Suggested commit: `feat: add evidence-driven auto-edit decisions and native editor controls`

Follow-up verification (18 October 2026): after explicit user authorization,
a short Gemini sample exposed and verified fixes for SDK schema compatibility,
per-shot context and word-timed emphasis. See
[output diagnosis and live verification](OUTPUT_EFFECT_DIAGNOSIS.md). Earlier
test notes above describe the scope at the time they were written.
