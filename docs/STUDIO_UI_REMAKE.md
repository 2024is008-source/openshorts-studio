# Studio interface redesign

The second supplied reference drives the home-page composition: compact navigation rail, photographic video-to-shorts hero, three quick actions, horizontal project cards, export table and separate system/storage/preset/account cards. The third supplied reference drives the charcoal surfaces, restrained blue selection states, compact rounded controls and neutral typography. The implementation remains native WPF with the existing Python engine.

## Assets

`native/OpenShorts.Desktop/StudioIcon.cs` contains original vector outline icons drawn in WPF. The navigation, storage buttons, presets and title bar no longer depend on mixing icon-font glyphs and text. No external icon package or new runtime dependency was added.

`native/OpenShorts.Desktop/Assets/Studio/creator-hero.png` is original artwork generated with the built-in imagegen tool. It is embedded in the desktop assembly, so it works offline. The hero composes this photograph with native card shapes and text; it is not a screenshot used as an application interface. Its example captions are marked “Style preview.” Recent projects and exports continue to display actual library data and actual thumbnails; no demonstration projects or paid account status are inserted.

Final generation prompt:

> Create one photorealistic landscape 16:9 photograph for a professional desktop video editing app's onboarding banner. A fictional bearded male podcast host in his early thirties, black t-shirt and backwards dark cap, speaking expressively with both hands near a black studio microphone. Waist-up medium shot, centered subject with generous space around shoulders so the same photograph crops well into vertical 9:16. Realistic cinematic studio, warm practical lamps and soft defocused green foliage, crisp natural facial texture, premium editorial photography. Warm face lighting against restrained charcoal surroundings. No text, no letters, no captions, no logos, no UI, no watermark. Output only the photograph.

## Working controls

- Import and New Project use the existing local import workflow.
- Quick Start opens AI Clipper or the template library.
- All nine workspaces remain reachable; Creative Studio and Publish are also visible on the navigation rail.
- Ctrl+K opens and focuses the existing project/template/workspace search.
- Quick tour and Help open a native walkthrough of the actual workflow.
- Project cards reopen saved projects; export rows open the corresponding clip.
- Hardware detection, processing preset, storage folder and output presets use the existing commands and data.
- GPU capability is reported from the local worker. No invented benchmark multiplier is displayed.
- Account remains an honest local workspace; no paid plan is claimed.

Window fit, native caption dragging, edge resizing and taskbar-safe maximize are retained. Dashboard content scrolls inside the window and the right cards have an independent scroll area.

Verification:

- Final Release build: zero warnings or errors.
- C# regression suite: 37 passed.
- `build/studio-home-verified/result.json`: real local library, one project and 12 exports; all nine workspaces, command search, preset selection, exactly one active navigation state, scrolling and compact layout passed.
- `build/studio-window-final/result.json`: 120 DPI, visible window bounds, native caption, interactive search/close buttons, resize edge and maximize/restore passed.
- `build/studio-editor-verified/visual-result.json`: actual local video playback, fullscreen return, foreground guides, responsive editor panels and imported image preview passed with the shared charcoal theme.
- Focused Python native contract/home checks: eight passed.
- Home screenshots: `build/studio-home-verified/home-desktop.png`, `home-compact.png` and `home-exports.png`.
- The previous Python engine is unchanged. The dashboard checks make no AI analysis requests.

Close any open copy with Alt+F4 and reopen `start_wpf.vbs`. It selects the newest successful local build. The source overlay archives from previous tasks predate this design.
