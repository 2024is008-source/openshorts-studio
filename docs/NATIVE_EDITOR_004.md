# OpenShorts Studio native editor — TASK-DESKTOP-004

Implemented in the existing five-project .NET 10 WPF solution and Python engine. The reference image guided the layout; the interface consists of native controls, not a screenshot or an embedded web editor. This is a substantial native editor implementation, **not full DaVinci-style feature parity**.

## Delivered interface

| Area | Implementation |
| --- | --- |
| Application shell | Cyan identity and export action, editable project title, undo/redo, autosave state, preview ratio, Windows window controls. Existing navigation and provider workflows remain accessible. |
| Assets | Media, Captions, Audio, Effects and Templates tabs. Project-local import, drag/drop, supported format filter, real thumbnails, names/duration, preview and Explorer action. Bounded catalogue and decoded thumbnail sizes. |
| Preview | Existing LibVLC player, fitted 9:16/1:1/16:9/source monitor, seek, clock, volume, approximate backward seek, decoded next-frame request, fullscreen, safe-zone and crop guides. |
| Inspector | Selected caption text/timing, aligned word emphasis, clip-wide font/size/colors/outline/shadow/background/position, caption animations, crop/focal point, templates and existing source-backed clip tools. |
| Timeline | Owner-drawn ruler, ordered source ranges, sampled filmstrip, selectable/draggable/trimmable caption bars, original waveform, music mix indication, real caption-animation indication, scene boundaries and template-headline marker. |
| Editing | Source-range trim/split/reorder/remove, source-time caption retiming, snapping, gesture undo/redo, timeline zoom/pan, numerical editing, autosave and revision conflicts. |
| Audio | Export mix gain/mute, fades, normalization target/peak settings and an imported music stem through the existing measured audio master. |
| Export | MP4/H.264/AAC dialog, filename/folder, supported resolutions, source or selected frame rate, auto/x264/NVENC policy, quality, real engine progress, cancellation, file/folder actions. |
| Persistence | Optional revision-checked workspace state stores title, playhead, selected range/caption, preview ratio, panel visibility and panel dimensions. Optional audio fields remain compatible with older project JSON. |
| Cache maintenance | Settings can remove generated thumbnail/feature caches older than 24 hours. Active jobs, source media, exported MP4s and unrelated files are preserved. |

At laptop sizes, assets and properties can be hidden from the timeline toolbar. Splitters resize the upper columns and timeline. Tab headers stay in a horizontally scrollable row. Inspector contents scroll instead of clipping essential editing controls.

## Components and contracts

- `native/OpenShorts.Desktop/EditorAssetsPanel.xaml`, `EditorInspector.xaml`, `EditorAudioPanel.xaml`, `EditorTimelinePanel.xaml`, `PreviewOverlayControl.xaml`, `ExportWindow.xaml` are reusable views.
- `EditorStyles.xaml` and the existing `Theme.xaml` provide the dark design system, tabs, sliders, panels and controls. `AspectRatioHost`, `PreviewGuides` and `MediaThumbnailConverter` handle monitor layout, guides and bounded image decoding.
- `EditorStudioWorkspace.cs` and `ExportWorkspace.cs` extend the existing partial MVVM model. Existing caption, template, creative and publishing workspaces are retained.
- `desktop/editor_assets.py` supplies a protected project-local catalogue. `desktop/home.py` supplies real home-page library/export information. `desktop/cache.py` only removes recognized generated cache names; `desktop/native_media.py` provides safe short playback aliases.
- `timeline_project.py` validates optional `audio`, workspace `ui` and render output settings. Existing project version 1 remains readable. New native clients require the `native-editor-workspace` capability, so an older unmatched worker is rejected clearly.
- `timeline_api.py` retains ownership, entitlement and revision checks. `timeline_render.py` reuses the established FFmpeg runner, caption renderer and measured audio master. There is no second AI or editing engine.

Rendering follows the existing bridge → saved timeline → FFmpeg/caption pipeline → audio master → quality validation → atomic export copy. User paths are not accepted by catalogue or cache endpoints. Imported music must resolve inside that project's media directory.

## Playback and overlays

LibVLC uses a native HWND. Guides and draft text use LibVLCSharp WPF's foreground-content mechanism, described in the [official WPF documentation](https://github.com/videolan/libvlcsharp/blob/3.x/src/LibVLCSharp.WPF/README.md).

Fullscreen has its own VideoView and overlay instance sharing the same MediaPlayer. The main view remains attached to its original window, avoiding foreground-window lifetime and visual reparenting failures. Playback position/state is restored when the video surface changes. Foreground binding, native video output and returning from fullscreen are covered by the UI review harness.

Draft caption/headline overlays are approximate editing guides, disabled by default. Render preview and final export use the actual caption/template renderer. No frame-accurate seeking or precise live overlay synchronization is claimed. Backward stepping is a timestamp seek; next-frame requests depend on the decoder.

## Verification and artifacts

- Release build: `dotnet build native/OpenShorts.sln -c Release --no-restore -v minimal`, zero warnings/errors.
- C# tests: 31 passed, including actual worker contract, authenticated transport, process ownership and DPAPI checks. Set `OPENSHORTS_TEST_ROOT` to this checkout.
- Affected Python desktop/timeline suite: 86 passed before the final cache test. Additional focused portability/cache tests: 25 passed.
- Full Python rerun: **1,618 passed, 76 warnings** in 401.22 seconds (`build/editor-004-pytest-verified.log`). After the long-path adapter addition, **27 focused tests passed**, including the new alias-preservation case and the matched-source inventory tests.
- Subsequent native image-preview acceptance also passed in `build/editor-004-complete-ui/visual-result.json`, using a copy of the earlier real-video project and no provider calls.
- Native acceptance: `build/editor-004-verified/result.json` reports successful playback/seek, media import, caption drag/undo, aligned words, revision conflict, autosave/automatic preview, templates, filmstrip, audio gain/fades/music and CPU/NVENC portrait export workflows.
- UI/fullscreen review: `build/editor-004-complete-ui/visual-result.json` reports successful foreground guides, fullscreen return, laptop/focus layouts and imported image preview. This review uses an isolated copy of the previously authorized real-video project.
- Independent FFprobe checks confirmed real 1080×1920 H.264/AAC output at 30 fps for the CPU and NVENC-request paths. The latter retains the existing CPU fallback behavior when hardware initialization fails.
- Editing/render acceptance fixtures are synthetic. A separate UI review reopens a copy of the earlier authorized real-video project; it does not generate new clips or run AI. No new paid Gemini or other provider requests were made. Original real-video projects are preserved.

Useful actual UI captures:

- `build/editor-004-complete-ui/editor-desktop.png`
- `build/editor-004-complete-ui/editor-laptop.png`
- `build/editor-004-complete-ui/editor-focus.png`
- `build/editor-004-complete-ui/editor-image-asset.png`
- `build/editor-004-verified/wpf-export.png`

The editor captures combine the actual WPF window, its paused LibVLC decoded frame and its real foreground guide layer. WPF RenderTargetBitmap alone omits native HWND video/overlay windows. This composition is documented in the visual-result JSON; the application does not use these images as its UI.

The real-video review exposed a LibVLC 3 Windows long-filename playback failure. Protected source/media routes now provide short project-local aliases for long paths, using hard links when possible. Original references and files are unchanged. This was verified by replaying the same real project successfully, with no provider calls.

The full Python suite initially had five Windows cp1252 failures in tests that read UTF-8 source without specifying an encoding. Those test reads now specify UTF-8; their assertions are unchanged.

## Remaining parity limits

- The video timeline still assembles ranges from one retained source. Imported B-roll and images are stored/previewable but cannot be composited as independent video layers. Add-source-range is enabled only for the actual retained source.
- Original audio remains linked to video cuts. Music uses the existing ducked mix, begins at zero and is trimmed/padded to the cut; independent music positioning, music waveform editing and multiple audio buses are not implemented.
- There is no general rotation, speed-ramp, arbitrary zoom/pan/effect-layer or motion-tracking renderer. Unsupported controls are explained rather than simulated. The effects row represents actual caption animation, not a freeform effects compositor.
- Captions use the existing aligned phrases. New arbitrary text layers, per-caption font-weight overrides, custom animation durations and interactive free-position text handles are not implemented. Existing hooks/template headlines remain available through their real tools.
- Font/style appearance is clip-wide; caption text/timing/emphasis are selected-row edits. Templates retain their own styling rules.
- Aspect selection in the monitor changes the monitor; the Export dialog determines the raster. Crop keyframes remain the existing scene override workflow, not a new transform compositor.
- The filmstrip contains eight real samples, not a frame-accurate thumbnail at every pixel. Scene detection remains sampled at 2 fps. The timeline draws only visible ranges instead of creating a WPF element for every frame.
- Fullscreen binding and playback are tested; DPI changes across monitors, all GPU/driver combinations, reverse frame decoding and exact live overlay synchronization are not certified.
- Saved view state is written on save/autosave and clean close. Title/view changes are revision checked; edit undo/redo covers rendering decisions, not every window-layout action.
- General cache eviction of retained render stages is not implemented; the cleanup action deliberately targets aged generated thumbnail/feature files only.
- Frozen-worker packaging, installer prerequisites, third-party/model license review and paid subscription infrastructure remain separate release blockers. This work does not create or verify an installer or establish readiness for sale.

Launch the newest locally built configuration through `start_wpf.vbs`. A source overlay is a matched source transfer, not an executable distribution or installer.
