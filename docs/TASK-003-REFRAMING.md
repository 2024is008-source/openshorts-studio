# TASK-003: professional automatic reframing and layout switching

## Inspection and diagnosis

The existing pipeline already provides TransNetV2 shot detection with a
PySceneDetect fallback (`scene_detection.py`), MediaPipe faces and YOLO person
fallback (`main.py`), optional mouth/audio speaker evidence (`active_speaker.py`),
and bounded crop/blur/split/editorial rendering (`reframe_v2.py`,
`framing_geometry.py`, `split_layout.py`). `layout_picker.py` enables existing
layout modules from retained Gemini analysis; this change adds no AI request.
The opt-in editing director freezes decisions for preview/final replay.

Baseline related regressions: **131 passed** before implementation.

Remaining problems identified in the inspected code:

- Horizontal-only matching updated the identity list while iterating detections,
  allowing two faces to claim the same ID. Vertically separated people and
  crossing trajectories were especially ambiguous. Old identity history was
  retained indefinitely.
- Pan speeds were per-frame, so identical motion played differently at different
  frame rates. Saved EDL keys could contain almost every rendered frame.
- A face crop could keep the head while cutting off an action, body, or useful
  object. Long detection loss could retain an off-centre crop indefinitely.
- Split selection considered the biggest two faces even in groups; fixed median
  panels could crop walking/crossing participants. Missing speaker evidence was
  treated as evidence that the second person was silent.
- Optional punch-ins and split tightening could unnecessarily enlarge already
  soft low-resolution footage.

## Implementation

This extends existing analysis and render entry points; no second tracking or
editing pipeline, dependency, model download, cloud service, or Docker requirement
was introduced.

### Shot-local identity and framing

`SpeakerTracker` now uses one-to-one 2D association, area compatibility, and
bounded velocity prediction. Identity state expires after approximately one
second and resets on scene cuts. These are local geometric track IDs, not face
recognition or proof of who is speaking. Area/hysteresis still prioritizes a
dominant visible subject. The existing optional mouth/audio signal is used only
when at least three windows and 60% of windows are attributed. Unknown activity
keeps a useful split rather than declaring someone silent.

Camera speed scales by elapsed time. Size-aware horizontal margins start a pan
before a large face leaves the crop. Existing headroom geometry is reused for
vertical placement; caption reserves never move a face crop. Brief occlusions
hold the last target. Sustained missing subjects or repeatedly untrackable
motion change the whole shot to context layout, without mid-shot layout flapping.
Smart mode resets on cuts even if the legacy cut-reset switch was disabled.

### Timestamped keyframes and replay

Smoothed analysis paths become compact, shot-relative keyframes containing
`time`, `x`, `y`, `width`, and `height`. Piecewise-linear simplification uses a
two-source-pixel tolerance, evaluated in windows of at most one second to bound
work. Renderers reconstruct even, bounded FFmpeg crop commands from that saved
path; they do not independently detect subjects or choose a new crop at every
rendered frame. Even-coordinate quantization can add up to two more source
pixels of deviation. Static paths store one keyframe. Each shot begins at zero.

Directed preview/final rendering share these exact decisions. Existing EDLs
default to `interpolation: "hold"`; new smoothed paths use `"linear"`.
Intentional active-speaker hard cuts remain hold paths, so interpolation does
not turn an editorial cut into a pan. Non-directed v2 renders also use the same
compaction/interpolation helpers and retain `<output>.framing.json` with output
geometry, selected layouts and timestamped crop paths. That diagnostic receipt
is not a replacement for the complete director EDL.

### Context, objects and layouts

The existing local YOLO model checks full bodies and configured object labels
only in cropped, face-bearing TRACK shots, at most once per roughly .75 seconds
(rounded to the next face-detection opportunity). Confidence must be at least
.55 and regions must exceed minimum size thresholds. Two or more context
samples with at least half extending outside the crop select BLUR/context for
the whole shot. The existing editorial preset/director may compose that context
as EDITORIAL. Manual crop/layout overrides bypass this new context pass.

Object labels are a conservative preservation policy, not a semantic claim that
every detected item is important. By default selected action/screen objects are
bicycle, sports ball, skateboard, surfboard, tennis racket, laptop and TV.
Only labels supported by the installed model are queried. Standard COCO weights
do **not** identify treadmills or supermarket shelves: treadmill action can be
preserved through full-body evidence; wide/no-face supermarket shots retain the
whole image through existing context routing. The tests do not claim a newly
trained treadmill/shelf detector.

Measured protected regions are retained in the directed EDL and passed to the
existing caption/headline placement logic. Evidence is bounded to 32 boxes per
shot; late detections merge into an envelope instead of being forgotten.
Caption/UI safe zones remain independent from subject crop geometry.

- TRACK follows a dominant visible subject with a smoothed shot path.
- CENTER is a stable intelligent portrait crop when the crop is centred.
- BLUR keeps the entire source over a cover-scaled source background.
- SPLIT retains two independent useful regions only with stable coexistence;
  groups and sustained movement that a static panel cannot cover are rejected.
- EDITORIAL reuses the existing detail-plus-context composition when enabled.

Source crop bounds, even dimensions, and cover/contain backgrounds remain in
force. No dark-pixel replacement or new black padding is used. Low-resolution
sources (<480 pixels on the shorter axis) get no extra optional punch-in or
split tightening. Other smart-mode punch-ins are capped at 15%. Full-HD output
is still an upscale for small sources; lost source detail cannot be recovered.

## Configuration and compatibility

```dotenv
REFRAME_OUTPUT_SIZE=fullhd
REFRAME_KEYFRAMES=1
REFRAME_SUBJECT_CONTEXT=1
REFRAME_OBJECT_CLASSES=bicycle,sports ball,skateboard,surfboard,tennis racket,laptop,tv
```

`REFRAME_KEYFRAMES=0` retains dense hold-path decisions.
`REFRAME_SUBJECT_CONTEXT=0` skips the additional local body/object inference.
An empty `REFRAME_OBJECT_CLASSES` list checks bodies only. Optional context
detector errors disable that pass for the remainder of the clip and retain
existing face/context routing. `SMART_REFRAME=0` retains the legacy context/zoom
policy. Flags are persisted through existing job options/recovery.

`SPLIT_LAYOUT`, `AUTO_LAYOUT`, `SPEAKER_SIGNAL`, `SPEAKER_CUT`, `PUNCH_IN`,
`EDIT_DIRECTOR`, and existing balanced/subject/editorial presets retain their
existing enablement semantics. This does not force optional split/editorial
features over an operator's chosen mode. Automatic v2 failures retain the v1
fallback (including mixed-resolution sources); explicit manual decisions still
fail visibly. The fallback does not gain a persisted keyframe path.

## Changed files

| File | Change |
| --- | --- |
| `main.py` | 2D identity association, time-based camera, headroom/margins, existing-YOLO context regions, recovery settings |
| `framing_geometry.py` | Compact timestamped paths, deterministic interpolation, one-to-one association, bounded evidence |
| `reframe_v2.py` | Shot resets, body/object/dropout context routing, speaker confidence, shared path replay and framing receipt |
| `editing_director.py` | Backward-compatible interpolation/protected-region schema, sparse shot keys, protected caption/headline regions |
| `split_layout.py` | Reject groups/unstable pairs, avoid low-resolution tightening |
| `active_speaker.py` | Distinguish reliable evidence from unknown activity |
| `punch_in.py` | Bounded optional zoom and low-resolution safeguard |
| `generation_options.py` | Resume allowlist for framing settings |
| `tests/test_professional_framing.py` | Deterministic identities, scene detection/fallback, motion, occlusion, objects, low resolution and real renders |
| `tests/fixtures/framing_scenes.json` | Reproducible requested scene cases |
| `.env.example`, `LOCAL_README.md`, this report | Configuration and technical/manual verification |

## Verification

Commands use the existing virtual environment and Windows UTF-8 mode:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/test_professional_framing.py tests/test_reframe_v2.py tests/test_smart_reframe.py tests/test_scene_cut_reset.py tests/test_speaker_tracker.py tests/test_split_layout.py tests/test_active_speaker.py tests/test_editing_director.py tests/test_director_api.py tests/test_punch_in.py tests/test_reframe_endpoint.py tests/test_generation_controls.py -q
.venv\Scripts\python.exe -X utf8 -m pytest --ignore=tests/test_mcp_stdio.py -q
.venv\Scripts\python.exe -m compileall -q main.py reframe_v2.py framing_geometry.py editing_director.py split_layout.py active_speaker.py punch_in.py generation_options.py
```

Final focused framing/editor suite: **240 passed**. Full repository suite in
UTF-8 mode: **1,254 passed, 2 existing failures**, with the three previously
documented MCP stdio setup timeouts excluded. The existing failures remain:

- `tests/test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`
- `tests/test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`

Python compilation checks passed for all changed modules. No frontend source or
dependencies changed, so frontend lint/build was not repeated for this task.
Existing deprecation warnings remain. Local XML results are in ignored
`logs/layout-switching-baseline.xml`, `logs/layout-switching-final-focused.xml`
and `logs/layout-switching-full.xml`.

Synthetic test figures stand in
for detector observations; real FFmpeg decoding, encoding, source cuts, crop
commands, full-HD raster checks, and low-resolution preview replay are exercised.
This verifies geometry and routing, not detector accuracy on arbitrary footage.
A copy of the tested synthetic moving-subject replay is retained locally at
`screenshots/reframing-task003/synthetic-tracking-1080x1920.mp4`, with its EDL
and an inspected frame. The synthetic red test region stays in frame; this is
a geometry verification artifact, not footage of a real actor or a quality
benchmark for the supplied reference exports.

## Manual verification and remaining limits

1. Start the existing no-Docker app with `REFRAME_OUTPUT_SIZE=fullhd`. Generate
   licensed landscape clips with one moving speaker, two people, a group, a wide
   supermarket shot and treadmill/action footage. Enable existing auto/split
   options for the two-person case; try the editorial preset for context scenes.
2. Compare shot changes, headroom, body/objects, caption/headline safe areas and
   first/last frames. Confirm 1080×1920 output and no introduced black canvas;
   intentional source darkness must remain untouched.
3. Inspect shot-relative `.framing.json` paths or director `.edit.json` keys.
   Preview a directed clip and compare its subject location against the export.
4. Verify manual crop corrections win, short occlusions hold framing, and an
   unrelated camera cut resets immediately. Disable the new flags to compare
   the compatibility behavior and inference overhead.

Identity through complete occlusion cannot be guaranteed by geometry; appearance
recognition/diarization was not added. Object importance, semantic action coverage,
undetected faces and between-sample motion still need a rendered-video check.
Face-free action uses a full-context fallback instead of speculative tracking.
New object context does not run in the v1 fallback. VFR, rotated media and
abrupt resolution changes retain existing pipeline limitations/fallbacks.
No live Gemini request, newly trained detector, or interactive dashboard UX
verification was used. The supplied references are already portrait exports;
their contact sheets informed the body/context review but are not landscape
source benchmarks. No new source-media download or unrelated visual material
was introduced.

Suggested commit: `feat: stabilize shot-aware reframing with timestamped crop paths`
