# Native editing parity audit — TASK-DESKTOP-003

Reference interaction: DaVinci Resolve. This is an OpenShorts editor, with source-time decisions and decoder-dependent playback seeking.

| Feature | Existing native state | Existing reusable engine / web implementation | Work for this task |
| --- | --- | --- | --- |
| Ordered cuts, split, reorder, delete | Numeric range table and buttons | `timeline_project.normalize`, `recut`, saved editor PUT | Interactive trim handles, selection, snapping |
| Caption track and correction | Phrase table | Stable source phrase IDs, real words retained unless phrase corrected | Word inspector for aligned words; explicit timing decisions |
| Caption appearance | Enabled, preset, position | Shared ASS `caption_renderer.options/generate` | Validated saved appearance options and native inspector |
| Waveform / scenes | Track placeholder | `/editor/features`, 600 peak bins; scene sampling at 2 fps | Native drawing, explicit refresh, invalidate on cut changes |
| Zoom / pan | Fit-only overview | Web SVG overview | Viewport-cull drawing and wheel navigation |
| Undo / redo | Missing | Web reducer history | Bounded native snapshots covering cuts, captions, crop and style |
| Autosave | Manual save only | Revision/origin conflict rejection already enforced | Debounced save; halt on conflict; explicit reload |
| Playback | Native LibVLC, seek and playhead | Existing clean assembly and rendered derivatives | Source-cut playback traversal; honest stale preview indication |
| Templates | Select and apply | Existing template compositor and validated content | Preserve existing template renderer; custom caption styling only outside templates |
| Audio | Linked source audio | Existing continuity/mastering/quality pipeline | Waveform navigation; independent audio mixing remains a gap |
| Saved format | Version 1 JSON, atomic writes, revision and origin | `timeline_api`, `timeline_project` | Backward compatible optional style and aligned-word decisions |
| Export | Preview, final, MP4 export and quality gate | Existing cached FFmpeg pipeline | Reuse unchanged pipeline |
| Shortcuts | Missing | Previous web editor key handlers | Editor-scoped transport, split, save, undo/redo, delete |

No second rendering or editing engine is required. Live caption appearance currently requires an engine-rendered preview; the native player does not composite ASS overlays itself. Full Resolve features such as independent audio tracks, transitions, keyframes, grading and multicam are outside the received requirements. The supplied task text ended at “Live pre”; subsequent phases have not been supplied.

## Implemented native increment

- Video selection, edge dragging with source timestamps, drag reorder, split, delete and existing range buttons. Minimum range remains 0.5 seconds. Snap uses cut/caption boundaries and available sampled scene markers, with a 0.12-second tolerance.
- Caption and linked audio lanes, a real 600-bin peak waveform and sampled scene markers loaded through the existing features API. Cut edits invalidate those features. Scene detection samples at 2 fps and may miss fast cuts.
- Timeline zoom up to 32×, wheel pan, Ctrl+wheel zoom; only visible segment/caption intersections are drawn. Numeric tables use WPF row/column recycling. The existing render contract still limits output to 12 ranges / 180 seconds; virtualization does not expand engine limits.
- Bounded 100-state undo/redo covering source cuts, phrase/word edits, crop, template selection and appearance. Split and mouse trim gestures are single history operations. Saves preserve history.
- Two-second debounced autosave with server revision/origin checks; a 409 stops saving and retains local edits. Explicit Reload latest draft asks before discarding local changes. Opening another clip and normal close flush pending edits. No automatic conflict merge or overwrite.
- Editor shortcuts when focus is outside text/dropdown inputs: Space transport, Ctrl+B split, Delete selected segment, Ctrl+S save, Ctrl+Z undo, Ctrl+Y redo. Native text controls retain their own editing shortcuts.
- Caption font, size, #RRGGBB text/highlight/outline colors, border width, shadow, position and existing animation effects. Optional appearance fields flow through the existing ASS renderer and its cache key. Templates retain their own caption design.
- Aligned-word inspector supports timing and emphasis. Word text is read-only; phrase rewrites disable word edits. Validation rejects overlap, out-of-phrase timings, changed word identities and attempts to invent alignment.
- Optional **Auto-render preview after autosave** uses the same Python preview job and native player. This is asynchronous rendered feedback, not instant WPF compositing or frame-accurate seeking. Manual Render preview remains available.

## Remaining native gaps

The audit identified template content/headline authoring, director/per-scene controls, independent music/audio authoring and browser-specific effects as gaps beyond the received phases. Existing functions remain available in the engine; no duplicate engine or replacement dashboard was introduced. Installer, signing, subscription authority and clean-machine release qualification remain separate unfinished work from TASK-DESKTOP-002.
