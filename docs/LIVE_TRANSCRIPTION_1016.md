# Live transcription progress acceptance — 2026-10-18

Source: D:\1016.mp4 (1280 × 720, 12:16, approximately 537 MiB).

The UI was leaving transcription active at 100% because its stage adapter did not
recognize the actual hybrid engine message `Video analysis: chapter N/M`. The
current user's job had already written a transcript checkpoint and story analysis.

The adapter now recognizes hybrid chapter analysis and local-LLM analysis starts.
An emitted transcription 100% marks that stage completed, even during the interval
before the next stage starts. During that interval the primary status reads
Transcription complete · preparing next step. Overall job completion remains unknown
until the entire processing job finishes; no Gemini percentage or ETA is invented.

A fresh local run called the existing transcribe_media function on the complete
user video, using an owned child process. The native WPF diagnostic imported the
actual source through the existing bridge and displayed the resulting stage events.
No paid Gemini request or duplicate clipping job was submitted.

Observed transitions: active/unknown → 25% → 50% → 75% → completed/100%.
Elapsed: 44.91 seconds. Output: English, 272 segments, 2,218 aligned words.
Evidence: build/live-1016-transcription/result.json, progress-history.jsonl,
transcription-25.png through transcription-100.png, transcription-complete.png.
The transcript is retained locally in the same diagnostic directory.

Release build: zero warnings/errors. Python generation review tests: 13 passed,
including regression coverage for transcription completion and five hybrid chapters.
This checks local transcription and the native progress display; fresh Gemini
analysis and full clipping/export were not performed in this acceptance run.

The diagnostic is explicit opt-in: --transcription-check <directory> --video <path>.
It uses an isolated application profile and the real local ASR engine. The regular
launcher picks up build/preview-flow on the next application start. An already
running Python worker retains its loaded adapter until it is restarted.
