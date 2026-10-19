# TASK-001 — Smart auto-reframing

Date: 2026-10-15 (Asia/Colombo).

The framing changes are implemented and exercised with deterministic tracking
tests and real FFmpeg renders. Full project acceptance remains limited by the
unrelated regression failures and MCP transport errors listed below. No paid
service, detector, or additional Gemini request was introduced.

## Inspection and diagnosis

`main.process_video_to_vertical` uses `reframe_v2.render` by default, with the
OpenCV frame loop as its fallback. `scene_detection.py` supplies shot boundaries;
`main.analyze_scenes_strategy` samples faces to select TRACK/GENERAL.
`layout_picker.py` enables existing layout modules once per source; the renderer
then considers split/speaker-cut and content/screencast/inset plans. Manual
overrides apply after automatic analysis. FFmpeg renders per-scene segments,
concatenates them with source audio, and writes a layout sidecar for captions.

| Finding | Correction |
| --- | --- |
| GENERAL enlarged the foreground to 42% of output height, losing about 24% of a 16:9 source's width | Default to contain scaling over a cover-scaled blurred source background |
| Split/panel graphs used black padding, including a two-pixel strip after half-height rounding | Scale the assembled raster to the final size; fill the three-person context cell from the source |
| Camera crops could be odd-sized; tightened crops could collapse on tiny inputs | Reuse validated, even, nonzero crop geometry and bounded offsets |
| Subject dominance could select one face while discarding another important face | Check the spatial extent of primary faces before preferring TRACK; retain existing strict split gates |
| Short no-face/wide inserts could inherit a tight layout from neighboring shots | Do not smooth an independently classified GENERAL insert into TRACK |
| A cut without a detection retained the previous shot's crop | Reset the camera to center, hold predictably within a shot, and snap to the first valid new subject |
| The old frame path returned full source height even when a portrait crop was shorter | Use the actual crop height and smooth vertical movement inside valid bounds |
| Downscaled analysis used horizontal scaling for vertical coordinates | Scale x/width and y/height independently |
| Taller-than-9:16 images were incorrectly treated as an exact fit | Analyze them for tracking or full-image preservation instead of blindly trimming top and bottom |
| A size change inside a stream invalidates fixed source-pixel coordinates | Observe decoder dimensions without checksums or another decode pass, then use the adaptive frame fallback; reinitialize geometry when decoded dimensions change |

No dark-pixel replacement is used. Source letterboxing, dark scenes, and genuine
black content remain part of the image.

## Resulting behavior

- Simple shots use the existing centered/tracked crop and face/person detectors.
  Crop motion remains damped, is scaled to source crop size, and resets at cuts.
- A scene with primary faces that cannot fit inside one crop preserves context.
  Existing enabled split layouts can still place two coexisting subjects into
  separate panels; important screen content continues to take priority.
- During trajectory analysis, at least three detection samples with 35% or more
  incomplete primary-face coverage select GENERAL for the entire scene. This
  avoids chasing a fast-moving person with a crop that cannot keep them visible.
  Manual framing and explicit whole-clip layout choices retain precedence.
- GENERAL/WIDE retain the full image over a blurred background that fills both
  output dimensions. The legacy GENERAL foreground zoom remains available.
- The existing editorial preset keeps its detail view and full-width context.
  Context cells use a fitted source bed when their aspect differs substantially.
- Split/panel subject crops use bounded headroom, placing size-bearing face
  detections higher in their tile while retaining the head where it fits.
- Captions reserve space by changing text margins, not by cropping a face. Clean
  captions retain their existing split/editorial placement; classic split captions
  retain seam placement. Explicit classic caption margins still take precedence.

`panel_layout.py` remains an optional helper as in the original checkout; this
task fixes its geometry/composition without adding a new automatic PANEL router.
Clip generation, highlight planning, metadata formats, and Gemini selection are
otherwise unchanged.

## Configuration

Set these in `.env` and restart the backend:

```env
SMART_REFRAME=1
REFRAME_OUTPUT_SIZE=fullhd
CAPTION_SAFE_BOTTOM_RATIO=0.20
```

- `SMART_REFRAME` defaults to `1`. Set `0` for legacy GENERAL foreground sizing
  and to disable new context/coverage routing. Crop validation, corrected raster
  dimensions, and removal of generated black padding remain active.
- `REFRAME_OUTPUT_SIZE=fullhd` produces exactly 1080x1920 for vertical reframing.
  The default `source` keeps the historical 1080-wide floor and retains larger
  source-derived outputs. Other existing output aspect ratios remain available.
- `CAPTION_SAFE_BOTTOM_RATIO` is clamped to 0.05–0.35. Malformed/nonfinite values
  fall back to 0.20. Clean captions default to 0.20. Classic captions keep their
  historical margin when this setting is absent. Split seam placement is retained.

No credentials were edited or included in source or logs. Tests installed pytest
and the already-declared optional cloud dependencies in `.venv` to collect the
existing suite. Billing remains disabled. `requirements-dev.txt` reproduces
these test dependencies separately from normal application setup.

## Verification

Use the project Python 3.11 environment and UTF-8 mode on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONUTF8 = '1'
$env:AWS_EC2_METADATA_DISABLED = 'true'
.\.venv\Scripts\python.exe -m pytest -q tests/test_smart_reframe.py tests/test_reframe_v2.py tests/test_split_layout.py tests/test_panel_layout.py tests/test_scene_cut_reset.py tests/test_speaker_tracker.py tests/test_layout_picker.py tests/test_layout_ranges.py tests/test_subtitles.py
.\.venv\Scripts\python.exe -m pytest -q tests
```

Final focused suite: **206 passed, zero failures or skips**, with 14 existing
PySceneDetect `get_frames()` deprecation warnings. This includes the actual
variable-resolution transport-stream guard and the adaptive frame-path tests.

The new tests exercise landscape, 4:3, square, portrait, taller portrait, tiny
sources, two important subjects, fast motion, scene cuts, no-face inserts,
malformed/out-of-bounds crop centers, configurable caption margins, and source
resolution changes. Real FFmpeg tests encode and inspect H.264 rasters, test
nonblack edges for colored inputs, preserve deliberate black source content,
verify a colored subject across a scene cut through the actual v2 renderer,
and construct a transport stream with changing frame dimensions. Deterministic
face detections isolate framing from detector accuracy.

Earlier broad checks:

| Check | Result |
| --- | --- |
| Complete suite including MCP stdio | 941 passed, 3 failed, 3 setup errors in an earlier iteration |
| Broad suite excluding only `tests/test_mcp_stdio.py` | 943 passed, 3 failed; includes 205 passing framing/caption cases, before the final stream-dimension guard test |
| Repeat the three unrelated failures with `SMART_REFRAME=0` | All three reproduced |
| Dashboard production build | Passed; existing optional analytics, Browserslist, and large-chunk warnings |
| Dashboard ESLint | Same 11 baseline errors in unchanged files |
| Installed-package consistency | `pip check` passed |
| Changed Python syntax | All 11 changed Python files parsed successfully |

The three unrelated failures are:

1. `test_deploy_drain.py::TestStatusFromDisk::test_unknown_job_with_metadata_is_completed`:
   expects completion from metadata without a rendered clip; the current status
   path rejects the missing artifact.
2. `test_restoring_static.py::test_missing_file_is_restored_then_served_with_ranges`:
   its missing-file request does not call the restorer in this Windows environment.
3. `test_story_director.py::test_summary_plan_repairs_provider_plan_that_exceeds_budget`:
   summary copy does not match the repaired provider plan.

`test_mcp_stdio.py` has three setup errors from its subprocess exceeding its
300-second timeout. These failures involve unchanged modules and remain outside
TASK-001. They prevent a claim that the whole application test suite is green.
The initial sandboxed attempts were stopped after filesystem-related stalls;
verification was rerun outside the sandbox. JUnit results are in ignored `logs/`:
`task001-focused.xml`, `task001-regression.xml`, `task001-pytest.xml`, and
`task001-unrelated.xml`.

## Remaining limitations and manual verification

These tests verify crop/composition behavior, not real-person detection accuracy
or artistic quality on every video. Severe occlusion, incorrect detections,
unusual display aspect metadata, rotation, and essential non-face objects still
need representative footage checks. Existing screen/layout analysis is retained;
no new OCR or semantic object detector was added. The variable-resolution
fallback's geometry is tested with changing decoded frames; the real transport
stream test verifies the v2 guard. An end-to-end variable-resolution video with
audio still needs manual review. Very low-resolution footage is upscaled and
cannot gain detail. Full Gemini-to-dashboard processing, browser Remotion export,
and NVENC encoding were not exercised by these synthetic media tests.

1. Configure `REFRAME_OUTPUT_SIZE=fullhd`, launch the existing Windows scripts,
   and submit an owned video longer than the source-duration minimum.
2. Check a single speaker moving left/right, two people near opposite edges,
   wide/group footage, screen content, a no-face insert, and a tall portrait.
3. Compare balanced and editorial presets, and enable the existing split layout
   for a stable two-person conversation. Confirm that context remains visible.
4. Inspect scene cuts and temporary face loss. Verify that motion is smooth,
   headroom is reasonable, and source content is preserved when a crop cannot fit.
5. Compare clean and classic captions with a changed safe-bottom ratio. Verify
   faces are not moved/cropped to make room, and split captions stay at the seam.
6. Exercise manual reframe and clip rerender, then download the MP4. Inspect
   1080x1920 geometry with ffprobe, edge pixels, audio sync, and caption placement.
7. Test a variable-resolution source and verify that the fallback produces a
   stable canvas with correct audio duration. Compare with `SMART_REFRAME=0`
   where legacy GENERAL sizing is needed.

## Changed files

| File | Purpose |
| --- | --- |
| `framing_geometry.py` | Shared validated crop, containment background, context, and caption helpers |
| `main.py` | Scene context protection, camera bounds/reset/vertical movement, adaptive frame fallback |
| `reframe_v2.py` | Full-HD option, complete backgrounds, bounded trajectories, coverage fallback, decoder size guard |
| `split_layout.py` | Bounded face-aware crops and no final black padding |
| `panel_layout.py` | Bounded tile crops and source-derived context cell |
| `clean_captions.py` | Configurable caption reserve |
| `subtitles.py` | Configurable classic ASS reserve with explicit-margin precedence |
| `tests/test_smart_reframe.py` | New TASK-001 regression and media tests |
| `tests/test_reframe_v2.py` | Compatibility-path coverage and corrected tall-source expectation |
| `tests/test_split_layout.py` | Updated padding-free composition assertion |
| `tests/test_panel_layout.py` | Updated source-background composition assertions |
| `requirements-dev.txt` | Reproducible test dependency set |
| `.env.example` | Documented optional settings, no credentials |
| `LOCAL_WINDOWS_SETUP.md` | Local configuration and test instructions |
| `IMPROVEMENT_NOTES.md` | Link to this report; historical results identified |
| `docs/TASK-001.md` | Diagnosis, changes, verification, limitations, and manual checks |

Suggested commit message: `fix: stabilize smart reframing and remove generated black padding`.

No commit was created. This checkout has no initial commit and all project
sources remain untracked; review the explicit file list before staging.
