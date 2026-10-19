# Full-video blurred-background preview — 2026-10-18

The user's generated portrait MP4 already contained the full landscape frame over
a blurred background. A decoded frame was inspected at 20 seconds. The review UI,
however, placed LibVLC directly in a wide ContentControl and kept showing the old
delivered MP4 after inline style saves.

The review player now uses the existing AspectRatioHost with actual decoded media
dimensions. This confines native video to the portrait/landscape frame instead of
leaving a wide native surface behind it. The source framing renderer is unchanged.

The contain framing choice is labeled Full video + blurred background. Apply &
preview saves the revision-protected timeline and calls its existing preview render
route. It waits for preview_ready, opens the validated local result and keeps that
preview when the Preview button is clicked again. A changed revision invalidates
this selection. Preview rendering does not replace delivered files; final export
continues through the existing renderer with the saved framing/caption/audio edits.
Caption disabling also updates the export caption checkbox. Choice labels now show
human-readable text in the custom ComboBox template.

Verification uses an isolated three-second excerpt at 00:20 from D:\1016.mp4,
with existing Python FFmpeg rendering and LibVLC playback. No Gemini request was
made and original user project files were not modified. Native checks verify the
saved framing/caption/audio settings, preview-ready output, video aspect ratio,
Preview preserving the new artifact, playback, exports and recovery. Preview media
is 360 × 640 with audio; final portrait exports are 1080 × 1920. Evidence is in
build/blur-preview-acceptance. The preceding acceptance run in build/blur-preview-verified
also passed all checks. Release compilation has zero errors or warnings; 55 C#
regression tests passed during this change.

To use the fix, restart with start_wpf.vbs, open a clip, choose Full video + blurred
background and press Apply & preview. Export selected produces the final MP4 using
those saved settings. This mode preserves the full source, so a landscape picture
remains centered within a portrait delivery frame with blurred space above/below.

One intervening native run (build/blur-preview-final) failed during its first
FFmpeg export. Repeating in a fresh isolated library passed the full acceptance
check, including fresh preview rendering and final exports. The final result also
records updatedRenderedPreview and previewAspectVerified as true.
