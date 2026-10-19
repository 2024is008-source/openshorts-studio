# Wide-shot captions and diffuse backgrounds

## Diagnosis and behavior

The supplied screenshots show a large caption phrase crossing the sharp image
and the blurred lower background. The caption layer knew split/editorial
timelines, but had no clear-image boundary for BLUR/GENERAL/WIDE layouts. Face
avoidance could also move an otherwise bottom-aligned phrase over the image.
The old background used a weak full-size sigma-12 blur.

Wide blurred shots now reserve the lower background for captions. A short
phrase prefers one line, retains its word clocks and highlight colors, and is
fitted to the available width/height below the sharp foreground. Layout-cut
boundaries split drawing intervals without changing word timing. Foreground
faces cannot push these captions back onto the video. Other layouts retain
their existing positioning rules. Browser preview uses the same lower-band
rule; exact FFmpeg preview remains authoritative for font measurements.

The blurred branch is downscaled to about one-eighth resolution, blurred more
strongly, upscaled, slightly desaturated and dimmed. The sharp foreground stays
on a separate unchanged branch. No dark-pixel replacement or source-content
removal is performed. `REFRAME_BLUR_STRENGTH` optionally configures reference
sigma at 1080px width, default 64, bounded 12–96. Invalid settings use 64.
The OpenCV fallback applies the corresponding stronger background treatment.

Sidecars can now retain optional normalized `content_bottom` geometry through
read/write and trim/remap. Existing landscape sidecars without that field use
0.67. New sidecars derive geometry from source/output dimensions. Directed
rendering derives it from the same EDL used for preview and final output. Caption
renderer version 4 invalidates cached caption derivatives.

## Verification

- 165 caption, director, API, template, timeline and bold-style tests passed.
- 91 sidecar, caption-geometry, reframing and automatic-mode tests passed.
- Those groups share 10 new composition tests: 246 unique Python tests passed.
- Dashboard: 31 tests passed. Native Remotion caption helpers: 6 tests passed.
- Dashboard production build, Remotion TypeScript build and changed JSX lint
  passed. Existing optional OpenPanel, Browserslist age, bundle-size and scene
  deprecation warnings remain. The full application suite was not run.

The new tests cover landscape/4:3/square/portrait geometry, legacy sidecars,
trim/remap persistence, large-caption safe bounds at full/preview resolutions,
word clocks across layout cuts, API preview, malformed blur strength and real
decoded image comparisons. A detailed grid fixture verifies that background
detail decreases while the sharp foreground is pixel-identical. Actual caption
pixel changes are confined below the foreground in the representative fixture.

The retained source and saved EDL from the preceding framing review were reused
to render `output/blur-caption-review/corrected.mp4`, with no AI requests or
tracking changes. The 1080x1920 H.264 export has audio and quality PASS, with no
reported problems. Render/layer/validation time was 82.39s using CPU libx264.
`comparison.png` and `sample.png` were decoded and visually inspected. Original
exports were not overwritten. `review.py` and `report.json` retain reproduction
details and validation results.

## Changed files

- Shared composition and timing: `framing_geometry.py`, `reframe_v2.py`,
  `main.py`, `layout_ranges.py`, `caption_timing.py`, `caption_renderer.py`.
- Existing integrations: `editing_director.py`, `app.py`, `timeline_render.py`,
  `video_templates.py`.
- Browser/native mirrored files: `dashboard/src/remotion/lib/types.ts`,
  `dashboard/src/remotion/lib/captions.ts`,
  `dashboard/src/remotion/compositions/Subtitles.tsx`,
  `remotion/src/lib/types.ts`, `remotion/src/lib/captions.ts`,
  `remotion/src/compositions/Subtitles.tsx`.
- Editor: `dashboard/src/components/SubtitleModal.jsx`.
- Tests: `tests/test_blur_caption_composition.py`,
  `render-service/src/captions.test.ts`.
- Documentation: this file and `LOCAL_README.md`.

## Manual review and limits

After active jobs finish, restart the application and refresh the dashboard.
Generate a new clip or rerender its framing from retained source to get the new
background. Editing captions alone preserves an already-rendered background.
Use Render preview before applying caption changes; inspect a BLUR interval,
the adjacent crop/split shots and transitions. Existing burned captions require
the retained clean clip for replacement.

This lower-band rule applies when a wide composition leaves usable space below
the clear image. Nearly square/portrait content or unusually restrictive safe
zones may have no usable lower band; existing safe positioning then applies.
Missing legacy geometry uses the documented landscape approximation. Missing
layout metadata cannot establish where an unknown video's foreground ends.
Speaker tracking and clip-selection quality are unchanged by this caption fix.

Suggested commit: `fix(captions): reserve lower blur band and soften portrait backgrounds`
