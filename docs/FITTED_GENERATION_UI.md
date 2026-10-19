# Fitted native generation workspace — 2026-10-18

AI Clipper opens directly into an idle preview of the processing workspace, with
all steps pending and no AI request. After import and the existing Video Ready
configuration, it displays the actual source on that same page. The permission
checkbox and Start AI clipping action explicitly begin processing. The separate
landing card and additional GenerationSettingsWindow have been removed. Video Ready
remains the single settings dialog. The duplicate image within the processing card
has been removed; the source thumbnail remains in the source card.

The generation page retains the cyan/navy theme and the reference layout: workflow
header, source card, processing card and settings/performance sidebar. A WPF Viewbox
fits the complete 1480 × 750 design surface to the available viewport; no processing
or sidebar ScrollViewer is present. The global bottom status bar has been removed.
Diagnostics open in a separate read-only window. Background jobs are still reached
from the header activity button and AI Clipper navigation.

Stage telemetry reuses the existing Python job logs. Transcription exposes its
reported segment progress; rendering counts distinct completed clips against saved
metadata. Observed transitions mark earlier observed stages complete. Unobserved
stages stay pending. Unknown stage progress displays Working…; no Gemini percentage
or ETA is invented. The ring and bar explicitly represent completed workflow steps,
not an estimate of processing time. The API overall remains unknown until completion.

Verification: the separate Release build in build/preview-flow has zero warnings
or errors; 55 C# tests passed. The native clipping smoke check verifies the idle
preview, direct import destination, no automatic AI processing, fitted layouts,
playback, cancellation, recovery, duplication and real portrait exports. The real
import smoke check verifies Video Ready persistence, single navigation, decoding,
source preservation and owned cancellation. Both passed with local synthetic media
and no paid AI calls. Visual evidence: build/preview-direct-verified and
build/import-direct-verified. The earlier 12 Python generation telemetry tests remain
applicable; no Python engine changes were made for this navigation update.

The normal Release output could not be replaced while the user's app was open.
start_wpf.vbs selects the newer build/preview-flow build by assembly timestamp on
next launch, preserving the running application's work.
