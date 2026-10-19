# Local animated caption looks

## Extension inspection

Inspected the supplied `com.cutback.cep.zip` without executing it. Its manifest
identifies Cutback 2.45.0, an Adobe Premiere Pro (`PPRO`) CSXS/CEP panel. Its
`main/index.html` redirects to `https://static.cutback.video/app/main/index.html`
and displays an offline error. The archive contains Premiere JSX, a Premiere
project, an export preset, translations and third-party Node dependencies. It
does not contain a standalone local caption renderer. Dependency licenses do not
establish permission to redistribute the application. No Cutback code, fonts,
templates or remote assets were imported or executed. Pricing and account access
were not verified. A screenshot cannot establish animation quality or timing.

## Implementation

Three independent configurations reuse the existing FFmpeg/libass caption
renderer and word clock. No additional renderer, Adobe installation, service,
Docker dependency or AI requests are required.

| Preset | Appearance | Timing behavior |
| --- | --- | --- |
| Green Pop | Large uppercase Anton, white words, green active word, thick outline | Subtle phrase entrance, active color only during measured speech |
| Teal Reveal | Condensed Anton, cyan-green active word | Future aligned words reveal when spoken; fixed phrase geometry |
| Paper Focus | Gray Anton on a white panel, dark active word | Word focus without text movement |

All use short four-word phrases and the existing safe placement, face avoidance,
split-layout placement, trim offsets and alignment fallbacks. Missing word
alignment keeps the whole phrase readable and does not invent precise highlights.
Automatic generation keeps the previously restored bold default. Choose another
look in the existing caption editor or optional generation settings. The same
preset IDs are accepted by saved timelines, EDLs and custom templates. Template
font/color overrides intentionally take precedence over caption preset colors.

The editor now retains each preset's case, phrase limits and panel colors. The
old Creator Bold/Bold Creator client entries incorrectly specified small Arial
instead of the server's large Anton; they now agree. Font and outline controls
cover the supported 240px and 20px ranges. Browser preview includes the existing
bundled Anton font and supports the same nominal font-size range. Its approximate
text metrics can differ from libass. Use **Render preview** to inspect the exact
FFmpeg output before applying captions. Existing automatic and manual workflows
remain available; the main automatic interface gains no extra required choices.

The existing Anton font is copied unchanged into the two renderer public-font
directories. Its embedded metadata credits Copyright 2020 The Anton Project
Authors, designer Vernon Adams, and declares SIL Open Font License 1.1. No fonts
from the supplied extension were used.

## Verification and manual review

Python regression groups cover preset settings, timeline save/reopen, EDL choice,
template validation, unaligned text, special characters, subtitle preview/apply,
actual decoded frames during speech and silence, and portrait safe bounds.
The existing caption/director/timeline/template groups passed 183 tests. The new
caption suite passed 15 tests, including its three director choices. Initial new
test fixtures incorrectly omitted Whisper's leading word spaces and expected
literal braces rather than the existing safe ASS substitutions; these fixtures
were corrected and rerun. No production timing/sanitization changes were needed.

Dashboard tests: 31 passed. Lint of changed JavaScript/JSX files passed. Production
dashboard build passed with existing optional OpenPanel variable, Browserslist
age and bundle-size warnings. This task did not rerun the entire project suite.

Run from the repository root:

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/test_local_caption_looks.py tests/test_bold_caption_restore.py tests/test_professional_captions.py tests/test_advanced_animated_captions.py tests/test_caption_api.py tests/test_editing_director.py tests/test_timeline_project.py tests/test_video_templates.py -q
.venv\Scripts\python.exe -X utf8 examples/local_caption_looks.py
```

The sample generator creates three 1080x1920 H.264/yuv420p, 30fps MP4s plus
decoded PNGs, a contact sheet and a JSON metadata report under
`output/local-caption-looks/`. These use synthetic background media and explicit
word fixtures, with no audio expected. The rendered contact sheet was visually
inspected. Timing tests also decode speech and silence frames at 270x480.

Restart the app after any active jobs finish, refresh the dashboard, open a clip's
caption editor, select a new look, render a preview, edit words and apply. Reopen
to confirm retained style/timing. Existing burned captions require the retained
clean clip for replacement. Missing clean media continues to fail safely.

## Changed files

- Backend preset and validation integration: `caption_renderer.py`,
  `generation_options.py`, `editing_director.py`, `timeline_project.py`,
  `video_templates.py`.
- Dashboard preset controls: `dashboard/src/lib/captionEditing.js`,
  `dashboard/src/lib/captionEditing.test.js`,
  `dashboard/src/components/SubtitleModal.jsx`,
  `dashboard/src/components/MediaInput.jsx`,
  `dashboard/src/components/SavedTimeline.jsx`,
  `dashboard/src/components/VideoTemplateControls.jsx`.
- Mirrored browser/server preview font and size support:
  `dashboard/src/remotion/lib/fonts.ts`,
  `dashboard/src/remotion/compositions/Subtitles.tsx`,
  `remotion/src/lib/fonts.ts`, `remotion/src/compositions/Subtitles.tsx`,
  `dashboard/public/fonts/Anton-Regular.ttf`,
  `remotion/public/fonts/Anton-Regular.ttf`.
- Tests and reproducible samples: `tests/test_local_caption_looks.py`,
  `examples/local_caption_looks.py`.
- Documentation: this file and `LOCAL_README.md`.

Suggested commit: `feat(captions): add local animated looks and align bold preview settings`
