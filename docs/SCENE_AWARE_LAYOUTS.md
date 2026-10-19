# Scene-aware automatic layouts

Automatic split-screen previously promoted a stable two-face detection without
requiring a scene-level reason. That can repeat an interaction in overlapping
panels and lose the relationship between the people and their surroundings.

The existing Gemini visual analysis now requests a bounded layout intent and
concrete visible evidence for each inspected moment. It distinguishes a shared
scene, a single subject, independent speaker views, a demonstration, and an
uncertain observation. The instructions preserve shared actions, objects, body
positioning, and readable surroundings; two detected people alone do not justify
a split. Appearance is not evidence of feelings or intent.

The renderer maps observations through source montage segments. An automatic
split requires explicit supporting evidence covering at least 80% of the shot,
two distinct crop regions with no more than 0.15 crop IoU, at least 90% coverage
of each own face, and no more than 10% of the other primary face. Shared-scene,
demonstration, and single-subject evidence veto a split. Conflicting, missing,
or insufficient evidence preserves the complete scene over blurred padding.
Existing speaker-activity checks still apply after this gate. Explicit editor
crop overrides remain available.

Word-boundary expansion does not extend the original visual observation range.
The selected reason is retained in the existing `.edit.json` shot record and is
reused for preview/export. Old analysis caches remain readable; their missing
layout intent cannot silently authorize a split. No extra AI call is added to
the rendering path and caches are not invalidated to force paid analysis.

## Verification

140 targeted Python tests passed, covering timeline mapping, evidence conflicts,
duplicate observations, invalid timestamps, overlapping panel crops, grounded
demonstrations, and actual FFmpeg rendering. The native Release build passed
with zero warnings or errors.

The supplied clip 6 from job `464701ce-76fe-4b54-936d-14988f87b789` had no retained
visual analysis. Its three automatic split intervals were replayed as full-scene
blur layouts using the original source and saved captions. The separate copy is
`build/scene-layout-check/scene-aware-clip-6.mp4`; `result.json` records the changed
intervals and accepted output-quality report. The original project is untouched.
Frames were visually inspected against the original wide source. This check
made zero provider calls; fresh Gemini response quality was not live-tested.
