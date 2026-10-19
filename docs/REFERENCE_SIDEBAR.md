# Reference sidebar replacement

The previous wide “Your workspace / Local account” card was removed. The dashboard now uses a separate native `DesktopStatusPanel` with the application's charcoal panel surfaces and blue accents, together with the reference's compact vertical stack, separators, chevrons and colored brand marks.

- System & Performance: detected GPU, enabled status, capability labels, title-cased processing selector, gauge and benchmark area.
- Storage: real library path and disk usage, green usage bar, Open Folder and Manage Files actions.
- Export Presets: TikTok, YouTube, Instagram and Custom rows with local vector brand assets.
- Account: compact photo-style placeholder and cyan plan badge, replacing the old workspace card.
- A small help/settings action sits below the cards.

GPU features and disk values come from the existing worker and filesystem. The badge reads “Local Plan” because no subscription service is connected. Speed reads “Not measured” and Run Benchmark is disabled because this build has no processing benchmark. The decorative portrait reuses the existing generated studio artwork and is not presented as an authenticated user's photograph.

Simple Icons paths were downloaded from the [upstream repository](https://github.com/simple-icons/simple-icons/tree/develop/icons). The upstream [CC0 license](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md) and source SVGs are preserved under `native/OpenShorts.Desktop/Assets/Brands`. Brand rights remain with their owners. No external icon runtime is required.

Verification: build succeeded with zero warnings/errors; 37 C# tests and eight focused Python native contract/home checks passed. The real local library review passed all-workspace navigation, search, presets, processing-mode binding, scrolling, compact layout and account visibility. It made no AI analysis requests.

The sidebar now fills the content height: fixed upper cards, a flexible presets section, and an account row aligned with the bottom edge. A minimum content height preserves readable controls on unusually short windows and enables scrolling there. The duplicate right-side help button was removed; Help remains in the main navigation.

Artifacts: `build/sidebar-fit-theme/home-desktop.png`, `home-compact.png`, `sidebar.png`, `sidebar-compact.png` and `result.json`. The visual review checks account alignment and equality with the shared Panel brush at both window sizes. Launch the newest build with `start_wpf.vbs` after closing the running copy.
