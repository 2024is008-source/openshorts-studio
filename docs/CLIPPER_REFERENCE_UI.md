# AI Clipper reference UI refinement — 2026-10-18

The two native WPF workspaces were refined against the supplied generation/review screenshots. Existing Python processing, authenticated communication, DPAPI credentials, process ownership and FFmpeg rendering are retained.

## Visual changes

- Dark navy panels, cyan accents, outlined cards, consistent compact controls, rounded score badges and tag chips.
- Progress header with a horizontal workflow stepper, real source card, glowing activity ring, elapsed time, observed pipeline stages and source preview.
- Icon-led settings sidebar with GPU capability and measured system-memory information.
- Three-column review: native preview and playback controls, compact horizontal clip cards, and properties/export inspector.
- Cyan preview/export actions, previous/next navigation, playback speed, volume, sorting, tag filtering, batch selection, more actions and fullscreen playback.
- Responsive Details/Export tab at narrower sizes. Hidden header columns are collapsed correctly rather than measuring text at zero width.

## External icons

Lucide vectors are bundled under `native/OpenShorts.Desktop/Assets/Lucide`. Upstream revision and downloaded file names are recorded in `provenance.json`; the full ISC license and applicable Feather MIT notice are retained in `LICENSE.txt`, copied with the build. `LucideIcon.cs` renders these as native WPF vector geometry, without a network dependency at runtime. Both the new workspaces and the window navigation use them.

## Functional additions

- Caption preset, framing mode and audio mastering controls save to the selected existing timeline through its revision-protected API. Rendering/export applies these changes to the delivered MP4.
- Duplicate creates a separate editable timeline while sharing source/delivered video files. Busy/stale revisions are rejected. Copies can be recovered after restarting the worker.
- Focused preview selection and batch checkboxes persist independently (`active` versus `selected`) so reopening a project restores the clip that was being viewed.
- Export filename/versioning and sequential per-item failure/retry behavior are preserved.

## Validation

- **69 Python tests passed**, including duplication, revision conflicts, source sharing, no-source clean-artifact reuse, selection recovery and existing pipeline/rendering operations.
- **54 C# tests passed**.
- Isolated Debug and normal Release builds passed with **0 warnings and 0 errors**.
- Native acceptance passed: real local import, preview/fullscreen, sorting/selection, editor loading, inline style save, duplication, worker restart recovery, background navigation, cancellation and sequential 1080×1920 MP4 export with partial failure/retry.
- Native capture checks cover desktop, laptop and 910×510 effective layout. Captures compose the WPF window with an actual decoded LibVLC frame, since the player uses a native HWND.
- Paid AI job responses are mocked only in explicit diagnostic mode. The visual fixture animates existing project artwork and adds generated audio. **No paid Gemini calls were made.**
- Overall generation percentage, ETA and success probability are not invented when the engine cannot measure them. Scores remain editorial scores rather than claims of viral success.

Evidence: `build/clipper-reference-final/clipper-result.json`, `generating.png`, `review-desktop.png`, `review-laptop.png`, `review-compact-export.png`.

Launch the rebuilt software using `start_wpf.vbs` after closing an earlier running version. No installer or clean-machine certification is claimed.
