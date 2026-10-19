# Automatic visuals and Gemini configuration — 2026-10-18

Native Video Ready now defaults new imports to automatic subject/scene framing
and an Automatic template entry. The template dropdown also includes None and all
real starter templates. Automatic template selection uses existing grounded story
mode (challenge, podcast, educational, emotional, comedy); unknown story modes use
Minimal Studio. No extra provider call is added. Manual template choice bypasses
selection. Manual framing now takes precedence over template layout hints.
Use automatic framing & template resets both choices. Existing explicit drafts
remain unchanged. Saving and reopening retains automatic or manual choices.

The disabled Key Moments / Manual Range controls were removed. The actual Separate
Short Clips / One Highlight Summary modes remain available, and source ranges are
editable in the existing Video Editor. No unsupported strategy is presented as a
working feature.

The source desktop worker reads only GEMINI_API_KEY[_1/_2], GEMINI_MODEL and
GEMINI_MODEL_VISION from the project .env; unrelated settings and cloud credentials
remain excluded. An existing DPAPI primary key keeps precedence. Frozen distribution
still uses protected settings rather than an embedded development .env. Verification
on this machine found both numbered keys available, two distinct runtime keys, and
the protected primary preserved. No key values are logged or written by this task.

The installed Google SDK defaults to five HTTP attempts. Those could multiply the
pipeline's three attempts. SDK attempts are now one, with a 120-second request
budget, leaving bounded pipeline retries and quota/auth key failover in control.
Hybrid chapter analysis rotates immediately to the next key on a key-specific
quota/auth error. Provider video-processing polling still has its existing deadline.
Video analysis still processes each chapter of the source, followed by scoring and
detail selection, so long videos can legitimately take minutes. No paid provider
latency benchmark was run.

Progress scans retained job history rather than only its last 600 lines, preserving
completed transcription/source steps on long logs. Completed chapters provide
measured analysis progress; it remains below 100% until the stage transitions.
The native heading shows the current chapter/total. Uploaded-proxy / provider
processing / request messages are available in the sanitized details popup.

Verification: Release build 0 warnings/errors; 155 focused Python tests passed
(10 existing PySceneDetect deprecation warnings), 55 C# tests passed. Native import
acceptance passed with actual FFprobe/LibVLC and the Python engine: automatic defaults,
manual framing override, automatic template persistence, reopening, cancellation and
single navigation. Evidence: build/automatic-options-ui/result.json. Gemini provider
tests were mocked; no paid AI calls were made. Restart the running app/worker using
start_wpf.vbs or build/preview-flow/OpenShorts.Desktop.exe to load these changes.
