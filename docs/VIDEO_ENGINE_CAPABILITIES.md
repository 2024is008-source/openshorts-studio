# OpenShorts Studio — Video Engine Capability Report

**Source audit:** 18 October 2026. This describes capabilities found in the current
workspace. Availability in code does not mean a feature is enabled in every job,
selected by AI, exposed as an editor button, or verified on every source video.

## 1. Status key

| Status | Meaning |
| --- | --- |
| Integrated | Used by the main generation/editor pipeline when its conditions apply |
| Automatic | The director has an evidence-based rule that can select it |
| Optional | Requires a setting, module flag, suitable source, model, or provider |
| Adapter only | Rendering code exists, but there is no automatic selection rule or dedicated Add Effect control |
| Separate tool | Available through another tool such as AI polish, hooks, or Creative Studio |
| Unsupported | Not safely implemented as a timed effect; skipped rather than simulated |

**Important:** the engine has several effect paths. The new AI Auto Edit panel,
the older provider-based AI polish tool, native layout generation, and the
optional Remotion renderer do not expose identical effect sets.

## 2. Import and source preparation

| Capability | Availability and limitations |
| --- | --- |
| Local video import | Integrated file selection/import; validates media before processing |
| URL import/download | Downloader workflow for supported public platform/direct video URLs; platform access and downloader availability can affect success |
| Local formats | Import service allows MP4, MOV, MKV, WEBM, AVI and M4V |
| Import limits | Current desktop import module sets 2 GiB and 2 hours; this is an implementation limit, not a universal codec guarantee |
| Media information | Dimensions, duration, codec/audio information, thumbnails and source previews |
| Retained original | Original source/clean intermediates support rerendering and manual edits |
| Existing burned-in captions | Generation setting prevents adding another caption layer when the source is marked as already captioned |
| Recovery | Saved drafts, transcript checkpoints, cached analysis and completed intermediates where valid |

Sources: `desktop/video_import.py`, `desktop/import_worker.py`,
`generation_options.py`, `native/OpenShorts.Core/GenerationSettings.cs`.

## 3. Speech, story and scene understanding

| Capability | Actual implementation |
| --- | --- |
| Speech transcription | Faster-whisper default; word/segment timestamps and language metadata |
| Alternative ASR | Optional Parakeet backend; unsupported-language/model failures fall back to Whisper |
| GPU transcription | CUDA where available, serialized GPU work, CPU fallback on supported CUDA failures |
| Silence avoidance during ASR | Voice-activity filtering; this does not automatically remove all pauses from the edit |
| Transcript timing | Phrase/word timing, sentence-aware boundaries and virtual transcript remapping after cuts |
| Visual scene analysis | Gemini chapter analysis with structured moments, visual observations and source times |
| Story understanding | Setup, stakes, development, reaction, outcome, explanation, takeaway and related grounded story evidence |
| Story categories | Challenge, emotional, comedy, podcast, educational and general |
| Highlight selection | Candidate windows, complete-story boundaries, duration targets and redundancy-aware ranking |
| Highlight summary | Combines selected source segments into one summary; differs from generating separate clips |
| AI editing cues | Timed explanation, reveal, surprise, visible reaction, serious dialogue, action, spoken number and pause observations |
| Analysis cache | Reuses retained provider analysis; old caches without editing cues can legitimately produce no additional effects |
| Missing AI evidence | Deterministic/conservative fallbacks; no invented reaction, scene meaning or emotion |
| Advisory scores | Reweightable ranking reports and evidence; scores are not guarantees of audience or viral performance |

Scene detection uses **TransNetV2** when available and **PySceneDetect** as a
fallback. TransNetV2 can find boundaries associated with gradual changes as well
as cuts; this does **not** mean the editor can render arbitrary cross dissolves
or reliably label every transition type. Very short scenes can be merged to
avoid unstable camera changes.

Saved director scenes retain timing, framing type, detected subjects/important
regions, speech, observations, crop-path movement, relative audio peaks, quiet
intervals and confidence where available. Crop motion is not a measurement of
the physical camera, and loud audio is not proof of a music beat.

Sources: `transcribe_backends.py`, `subtitles.py`, `scene_detection.py`,
`story_director.py`, `clip_selection.py`, `clip_ranking.py`, `auto_edit.py`.

## 4. Framing, split screens and composition

| Layout or technique | Availability | Conditions / meaning |
| --- | --- | --- |
| Face-aware portrait crop | Integrated | Fits and follows retained face detections with headroom and crop bounds |
| Subject tracking | Integrated | Existing subject/face tracking and person fallback; not semantic identity recognition |
| Smooth camera follow/pan | Integrated | Smoothed crop trajectories, reset at shot boundaries |
| Center/static crop | Integrated | Used when a stable centered crop is appropriate |
| Full video + blurred background | Integrated | Complete source image remains visible over a filled blurred background |
| Context-preserving wide view | Integrated | Preserves people, objects, action or distributed content that a narrow crop would remove |
| Two-person stacked split | Optional + guarded | Needs enabled split routing, adequate retained scene evidence and independent usable crops |
| Speaker-based alternating cuts | Optional | Mouth-motion plus relative audio activity; requires speaker signal/cut settings and reliable evidence |
| Screencast composition | Optional | Full-width content plus presenter area; dedicated analysis/routing, not a generic two-face split |
| Existing webcam inset handling | Optional | Detects an existing off-center/corner presenter region for separate composition |
| Editorial detail + context | Explicit choice | Detail view plus wide context; not automatically forced just because a scene is uncertain |
| Per-scene crop override | Manual | Existing scene crop controls and focal points |
| Crop / contain / preserve | Manual | Saved editor crop modes |
| Automatic layout picker | Optional provider tool | Can enable suitable layout modules; shadow mode records recommendations without applying them |

### Why split may not appear

Two detected people are insufficient. Automatic split promotion requires:

1. An enabled split-analysis path.
2. Explicit retained visual evidence supporting independent speaker views over
   most of the shot (currently at least 80% coverage).
3. Crop overlap no greater than 0.15 IoU.
4. At least 90% of each own face inside its panel and no more than 10% of the
   other primary face leaking into that panel.
5. No overriding requirement to preserve a shared action, object, demonstration
   or interaction; reliable optional speaker checks must also agree.

When these fail, the engine preserves the shared scene. The editor cannot
currently add an arbitrary timed split/PiP composition through an Auto Edit
effect record. A real native layout and a record named `smart_split` are different.

Sources: `reframe_v2.py`, `framing_geometry.py`, `split_layout.py`,
`active_speaker.py`, `screencast_layout.py`, `camera_inset.py`, `layout_picker.py`,
`editing_director.py`.

## 5. Complete 35-effect matrix

This matrix covers the previously requested effect list. It is not a claim that
all 35 are implemented as independently editable timed layers.

| # | Effect | Current status / actual behaviour |
| --- | --- | --- |
| 1 | Smooth zoom in | Automatic for suitable explanation cues; bounded push and release |
| 2 | Smooth zoom out | Automatic for a suitable reveal; stays within validated framing |
| 3 | Fast punch-in | Automatic for a grounded surprise cue, subject to crop safety |
| 4 | Snap zoom | Automatic for a grounded visible-reaction cue, using the existing subject crop |
| 5 | Zoom bounce | Adapter only; controlled pulse, not automatically selected by a dedicated rule |
| 6 | Smart camera pan | Existing tracking/crop path; Auto Edit does not independently invent a new pan trajectory |
| 7 | Face tracking | Existing detection/tracking; the similarly named effect adapter reuses that framing |
| 8 | Subject tracking | Existing tracking; action cue may add bounded emphasis along the retained path |
| 9 | Controlled camera shake | Adapter only; capped strength; no dedicated automatic shake rule |
| 10 | Motion blur | Adapter only; two-frame blend, not optical-flow motion reconstruction |
| 11 | Whip pan | Unsupported |
| 12 | Freeze frame | Unsupported as an automatic timed effect |
| 13 | Speed ramp | Unsupported |
| 14 | Slow motion | Unsupported as an automatic timed effect; no optical-flow slow-motion generation |
| 15 | Smart split screen | Native guarded layout; not a free-standing Auto Edit override |
| 16 | Picture-in-picture | Existing inset/screencast handling; arbitrary imported B-roll PiP is unavailable |
| 17 | Blurred background | Integrated native layout |
| 18 | Scene-aware crop | Integrated framing plus manual scene overrides |
| 19 | Context-preserving wide layout | Integrated conservative layout |
| 20 | Kinetic captions | Existing caption animation plus timed adapter; not every clip gets this effect |
| 21 | Word pop | Caption animation/preset and timed adapter |
| 22 | Keyword highlight | Automatic exact-quote emphasis when supported by a cue and retained speech |
| 23 | Animated hook | Existing source-backed hook tool/generation path; standalone timed Auto Edit override is delegated/skipped |
| 24 | Important number highlight | Automatic when the supported quote actually contains spoken digits |
| 25 | Text reveal | Existing caption animation plus timed adapter |
| 26 | Clean jump cut | Native segment assembly and source cuts; not randomly inserted effect spam |
| 27 | Fade | Timed adapter; automatic rule is restricted to a cinematic opening pause with measured quiet evidence |
| 28 | Cross dissolve | Unsupported as an editable timed transition |
| 29 | Beat-synchronized cut | Unsupported; loudness emphasis is not true music-beat synchronization |
| 30 | Directional motion transition | Unsupported |
| 31 | Dialogue normalization | Integrated audio mastering; optional timed record currently runs a mastering pass, not a dialogue-separation model |
| 32 | Music ducking | Existing audio controls with a separate imported stem; standalone timed override is delegated/skipped |
| 33 | Whoosh | Unsupported; no bundled licensed accent asset |
| 34 | Impact accent | Unsupported; no bundled licensed accent asset |
| 35 | Pop sound | Unsupported; caption word-pop animation does not imply a pop sound |

**Adapter-only is not a manual Add Effect feature.** The current native panel
edits existing generated/saved records; it does not expose every adapter type in
a new-effect picker. Noncentral additional zoom anchors are currently skipped.

### Additional effects in the separate AI polish tool

`editor.py` / `edit_builder.py` implement `zoom_in`, `punch_in`, `zoom_pulse`,
`color_pop` (contrast/saturation), `bw_moment` (black-and-white), short `flash`,
and `vignette`. This is a separate provider-based tool, not the new automatic
scene director. It validates/caps edits, rejects overlapping zooms and drops
zoom reframing when captions/hooks are already burned in. Its colour effects
are not automatically selected by the new director.

## 6. Caption and text styles

**12 caption presets:** clean-minimal, bold-creator, dynamic-highlight, podcast,
cinematic, openshorts-dynamic, creator-bold, clean-podcast, minimal, green-pop,
teal-reveal and paper-focus.

Caption controls include:

- Word highlighting/karaoke-style active words, pop, fade, glow, scale, reveal
  and bounce; static text and background/box styling are also represented.
- Font family, size, uppercase, text/highlight/outline colours, outline width,
  shadow, background colour/opacity and inactive-word opacity.
- Top/middle/bottom position; phrase length, maximum words/lines, line spacing,
  sync offset and minimum phrase duration.
- Phrase text corrections, phrase retiming and aligned word timing/emphasis
  where the original alignment supports it.
- Resolution-aware sizing, safe margins and face/layout-aware placement,
  including split seams and blurred-background compositions.
- SRT/ASS generation and burned-in caption output; removing a generated caption
  layer uses retained clean media where available. It is not general inpainting
  that can erase arbitrary text already present in an original video.

**Font choices in code:** Anton, Arial, Verdana, Impact, Georgia, Courier New,
Helvetica and Noto Serif. Actual appearance depends on installed/bundled fonts.

Hook text supports six styles (classic, dark, yellow, red, outline,
outline_yellow), three sizes, top/center/bottom positioning, and six entrance
modes: none, fade, scale-pop, slide-up, spring and highlight-reveal. Automatic
hook wording must be grounded in retained source speech.

Sources: `caption_renderer.py`, `caption_timing.py`, `subtitles.py`, `hook_layer.py`,
`hook_grounding.py`, native caption/hook inspector controls.

## 7. Templates, profiles and pacing

**Five bundled video templates:** OpenShorts Creator Energy, OpenShorts Minimal
Studio, OpenShorts Story Focus, OpenShorts Podcast and OpenShorts Challenge.
Templates combine existing typography, colours, safe areas, hooks and caption
styling. Custom project styles can be saved and applied in batches. Automatic
template/framing choices can be overridden manually.

**AI Auto Edit intensity profiles:**

| Profile | Max effects | Camera gap | Max zoom | Max shake | Duration range |
| --- | ---: | ---: | ---: | ---: | --- |
| Minimal | 2 | 8 s | 1.04× | 0 | 0.6–5 s |
| Balanced (default) | 5 | 5 s | 1.10× | 0.002 | 0.35–5 s |
| Dynamic | 8 | 3 s | 1.14× | 0.004 | 0.25–4 s |
| Cinematic | 4 | 7 s | 1.07× | 0 | 0.8–6 s |
| Custom | Editable within validated bounds | Editable | Up to 1.18× | Up to 0.006 | Validated |

These are limits, not promises to fill the clip with that many effects.
Additional settings control evidence thresholds, effect categories and enablement.
Interpolation supports linear, ease-in, ease-out, ease-in-out, smoothstep and
controlled overshoot, with timing expressed in seconds.

**Pacing modes:** fast, balanced, emotional and educational. Measured optional
silence trimming, speech-aware clip boundaries, protected story moments and
continuous-audio assembly are separate from speed ramps. Emotional pacing
preserves meaningful pauses rather than indiscriminately removing silence.

Sources: `assets/video_templates.json`, `video_templates.py`,
`assets/auto_edit_profiles.json`, `auto_edit.py`, `pacing.py`, `recut.py`.

## 8. Audio engine

Integrated or explicitly configured features include loudness measurement and
normalization, true-peak limiting/checks, dynamic-range targets, optional mild
noise reduction, fades, volume, mute, and sidechain ducking of an imported music
stem. Presets include natural, dialogue and original; actual normalization
enablement is controlled separately, so the name “original” is not a guarantee
of bit-for-bit audio passthrough.

The engine measures silence, clipping risk and stream timing. It does not
separate music already mixed into dialogue into clean stems. It does not
automatically generate licensed music, voice effects or sound accents.

Sources: `audio_mastering.py`, `timeline_render.py`, native Audio inspector.

## 9. Native timeline and review workflow

- Select source ranges; trim, split, reorder, remove and concatenate them.
- Linked original audio, waveform, sampled scene markers and thumbnail filmstrip.
- Timeline zoom/pan, snapping, playhead seeking and native video playback.
- Caption/word editing, crop/focal controls, hook tools and template choices.
- AI effect list, reasons, enable switches, intensity/timing edits and effect preview.
- Undo/redo, autosave, saved revisions, conflict detection, reopen/reset and recovery.
- Regenerate effects from retained cues without retranscription or another
  Gemini request; preserve compatible manual effect overrides.
- Duplicate generated clips, preview, export selected/all clips and reopen
  results in Video Editor.
- Import/preview project image, video and audio assets. This is **not** a full
  freeform multi-layer compositor for arbitrary B-roll, masks and image overlays.
- Safe-zone/crop guides, fullscreen preview and adjustable editor panels.

The saved `.edit.json` director plan and saved editor project are distinct but
connected records. A clean base is retained so removing effects does not require
trying to reverse a burned-in effect.

Sources: `timeline_project.py`, `timeline_api.py`, `timeline_render.py`,
`native/OpenShorts.Desktop/AutoEditWorkspace.cs`, `TimelineSurface.cs` and editor panels.

## 10. Rendering, export and quality checks

| Capability | Notes |
| --- | --- |
| Main native render path | FFmpeg with OpenCV/detection-assisted planning and libass captions |
| CPU encoding | H.264/libx264 |
| NVIDIA encoding | H.264/NVENC where initialization succeeds; supported failures can fall back to CPU |
| Output | Native export delivers MP4; this is not a general list of every FFmpeg codec |
| Export resolutions | 1080×1920, 1080×1080, 1920×1080, 720×1280, 1280×720 or current clip size |
| Export frame rates | Source, 24, 25, 30, 50 or 60 fps |
| Export quality | Fast, balanced, high; generation also exposes standard/studio choices |
| Generation formats | Vertical, horizontal and square; native generation does not currently expose 4:5 |
| Shared decisions | Preview and final render reuse the saved effect/layout decisions at their respective sizes |
| Cache | Segment, clean-assembly, effect and caption caches with dependency/identity checks |
| Runtime controls | Bounded encoder concurrency/threads, progress, cancellation, timeouts and retry/fallback handling |
| Export validation | Video/audio availability, duration, resolution/aspect, frame rate, codec/container/decode checks and synchronization |
| Visual QA | Sampled blank frames, suspicious borders and possible accidental freezes; these are targeted checks, not human understanding of every frame |
| Publication gate | Failed required quality checks prevent publishing an invalid export |

**Additional renderer in the repository:** Remotion compositions support base
video, subtitle and hook overlays, timed zoom centres, brightness, contrast and
saturation with interpolation. This requires the separate JS/render-service
runtime and is not proof that the native application is using it. The runtime
capability report identifies its encoding path as libx264, not Windows NVENC.

Sources: `ffmpeg_utils.py`, `render_runtime.py`, `export_quality.py`,
`remotion/src/compositions/`, `remotion/src/lib/types.ts`, native `ExportWorkspace.cs`.

## 11. Adjacent provider-dependent creative tools

Creative Studio includes source/title analysis, title refinement, face-reference
frame selection, thumbnail concepts/generation, thumbnail text, and description
generation. Dubbing/translation is implemented through ElevenLabs. Product/UGC,
voice and actor workflows also have separate native/provider integrations.
They require their configured providers and are not local video effects or
automatic features of every clipping job. No live service availability or
provider pricing was checked for this report.

Sources: `thumbnail.py`, `translate.py`, native `CreativeWorkspace.cs`.

## 12. Practical limits and how to interpret an output

1. **An effect name in a schema is not proof it rendered.** Check the saved
   layout/effect decisions, enabled categories, skip reasons and output receipt.
2. **An old analysis cache may have no editing cues.** The director then adds
   no unsupported semantic effects, even if generation itself succeeds.
3. **Split is conditional, not compulsory.** Shared action and overlapping crops
   should remain one coherent view. A split should add distinct information.
4. **Serious/emotional material suppresses added effects.** Minimal editing can
   be intentional, but a missing analysis signal is a separate issue.
5. **Source quality and detection matter.** Missing faces, occlusion, poor light,
   fast movement and limited resolution can force a wide/blur fallback.
6. **Adapter-only features are not all selectable in the native UI.** Adding a
   type to a record is insufficient when the renderer delegates or skips it.
7. **No full human-editor judgement is guaranteed.** The current rules preserve
   evidence and avoid unsafe changes; they do not guarantee a compelling story,
   perfect reaction selection, or platform performance.

## 13. Verification scope

This report is a read-only source audit, not a new end-to-end certification of
every feature listed. The preceding implementation work recorded passing Python
and native regression tests, native save/reopen/undo/preview checks, and actual
CPU/NVENC exports. Those checks do not establish that a particular new user job
received appropriate scene analysis or visibly used each feature. That requires
inspection of that job's media, settings, cached analysis and saved decisions.

Follow-up, 18 October 2026: a user-authorized 30-second Gemini sample and local
render verified per-shot framing decisions and grounded number emphasis. A
controlled split fixture and native fallback-warning acceptance also passed.
See [output diagnosis and verification](OUTPUT_EFFECT_DIAGNOSIS.md) for the
actual failure, changes, evidence and limits. This does not certify all effects.
