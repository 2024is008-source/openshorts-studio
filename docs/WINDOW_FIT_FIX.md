# Window sizing and movement fix

The previous 1600 × 1000 WPF device-independent window exceeded a 1920 × 1080 display at 125% scaling. Its title bar could open outside the desktop. The custom drag handler also depended on the exact child element clicked.

Startup now fits and centers the window inside the current monitor's usable work area, using physical pixels and the window DPI. Minimum sizes shrink when the display requires it. Maximize respects that monitor's taskbar. Restore and display/DPI changes recheck visible bounds without constraining ordinary dragging between monitors.

The 60-DIP header uses Windows caption hit testing for dragging, double-click maximize, and snapping. Search, project controls, and window buttons remain client controls. Resizing uses native window edges. Short editor windows reduce panel minimums and allow scrolling the timeline controls.

Verification: Release build completed with zero warnings/errors; 37 C# tests passed, including six window geometry cases for scaling, negative monitor coordinates, and preserving valid positions. `--window-check` exercises the actual native window at 120 DPI (125%), checks physical bounds before and after maximize/restore, and verifies caption, search, close-button, and resize-edge hit tests. Results are in `build/window-fit-final/result.json`. This check uses an isolated library and does not start AI analysis.

Close any already running copy with Alt+F4, then reopen `start_wpf.vbs` to load the rebuilt application. Existing source archives predate this correction; the local builds contain it. The final Debug build was verified with zero warnings/errors because an open user session held the Release executable; the launcher selects the newer Debug build automatically.
