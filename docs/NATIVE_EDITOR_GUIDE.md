# Native editor

Open a generated clip from Projects / AI Clipper. Source starts/ends are seconds in the original recording; the graphical timeline displays assembled time, including repeated source ranges.

Select a video block to inspect it. Drag its left/right edge to trim, or drag its body to reorder it. Each range must retain at least 0.5 seconds. Split at the playhead, remove a selected range, or use the numeric table for explicit timestamps. Snap can be disabled. Mouse wheel pans; Ctrl+wheel or Zoom changes scale.

Choose **Waveform / scenes** to save the draft and analyze the current ranges locally. Orange markers are sampled scene changes and edit joins. Audio peaks are drawn in the linked audio lane. Changing cuts invalidates the analysis; reload it when needed. Audio follows video cuts.

Select a caption in Caption Track. Correct phrase text or source timing. The adjacent word inspector is enabled only for existing aligned words and unchanged phrase text. Adjust word in/out times and emphasis; do not overlap words or move them outside the phrase. Rewriting a phrase uses phrase timing rather than pretending to realign it automatically.

Caption presets work immediately as saved decisions. Enable Custom appearance to set font, size, colors, outline, shadow and animation. Colors use #RRGGBB. A selected video template owns its caption design. **Render preview** shows the engine-composited result. Enable **Auto-render preview after autosave** for automatic rendered updates after changes settle. The native player shows the last rendered appearance until that job completes.

Drafts autosave two seconds after a committed edit. Undo/redo remains available across saves. A conflicting server revision pauses saving and keeps local edits in memory. Reload draft explicitly discards local changes after confirmation; no silent overwrite occurs. Closing normally flushes pending edits. Resolve errors before closing if that save fails.

With focus outside text/dropdown controls: Space plays/pauses; Ctrl+B splits; Delete removes the selected range; Ctrl+S saves; Ctrl+Z / Ctrl+Y undo/redo. Use Render final and Export MP4 for the quality-checked output.

Source playback traverses selected ranges using periodic timestamp checks. LibVLC seeking and traversal depend on decoder/keyframes and the 200 ms UI update interval. Use rendered preview/final to review exact assembled output; no frame-accurate interactive playback claim is made.
