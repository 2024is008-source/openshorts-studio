# Automatic framing: duplicated wide panel

The screenshot shows the existing EDITORIAL composition: a large detail view
above a repeated wide source view. This differs from a two-subject SPLIT.
The supplied job `14fc256a-d1a8-4497-85b4-4c5b93f96c31` actually saved
`FRAMING_PRESET=editorial`, with EDITORIAL recorded for all eleven first-clip
shots. Metadata alone cannot establish whether an older dashboard, manual
settings or a previously running backend submitted that choice.

An independent backend defect also promoted GENERAL shots to EDITORIAL merely
because a video was classified as challenge/educational. Story genre does not
justify duplicating the image. That promotion now requires an explicit Editorial
request. Existing saved EDLs, native layouts and explicit choices remain valid.

## Changed files

- `editing_director.py`: require explicit Editorial policy for promotion.
- `reframe_v2.py`: skip unnecessary editorial-focus sampling otherwise.
- `dashboard/src/components/MediaInput.jsx`: optional framing also defaults to
  Automatic; Editorial label describes the repeated wide view.
- `tests/test_editing_director.py`: five-category regression, explicit Editorial
  compatibility, default GENERAL mapping and actual CLI generation. The CLI
  fixture now checks a grounded hook in the available top area rather than
  assuming an editorial panel must occupy it.
- Documentation: this report and `docs/AUTOMATIC-EDITING-FOCUS.md`.

## Verification

84 Python framing/director/automatic tests and 31 dashboard tests passed.
Changed JSX lint and production build passed. Existing scene-detection
deprecation, optional OpenPanel configuration, Browserslist age and bundle-size
warnings remain. The full application suite was not rerun.

A separate corrected copy was rendered from the retained first clip's source
range 336.4–366.07s using local detectors, with no Gemini requests. The original
job was not modified. Review hooks are disabled to isolate composition; bold
captions retain their source timing.

`output/automatic-layout-review/corrected.mp4` passed technical validation:
1080x1920 H.264, audio present, no reported problems. The review took 85.58s
after source extraction, including analysis, rendering and validation. Layout
totals: TRACK 8.3083s, SPLIT 1.9019s, BLUR 19.4598s, EDITORIAL 0s. The shared
EDL is `clean.mp4.edit.json`; `review.json` contains settings/validation,
`review.py` reproduces the review and `comparison.png` contains visually
inspected matching before/after frames from the actual supplied first clip.

## Limitations and manual verification

This fixes unwanted duplication, not every composition problem. Wide group and
action scenes still use blur where current subject geometry cannot safely crop.
Face size alone does not establish speaker importance. Existing outputs and
saved decisions keep their original composition until regenerated.

After active jobs finish, restart the backend and refresh the dashboard. Submit
a new job with Automatic editing enabled; metadata should contain
`FRAMING_PRESET=auto` and `EDIT_DIRECTOR=1`. Inspect opening, cuts, speakers and
ending. Explicit Editorial should still produce detail plus wide context.

Suggested commit: `fix(framing): stop implicit editorial duplication in automatic edits`
