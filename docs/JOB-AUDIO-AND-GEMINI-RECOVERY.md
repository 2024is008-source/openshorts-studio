# Failed job: audio tail and Gemini request rejection

Inspected the supplied log, job metadata, stream probes and quality/analysis
sidecars for `7a2d24e5-8418-441d-87ae-9b9a6cfcab39`. No credentials were read
or logged. The job was configured as a 60-second highlights summary, so one
summary output is consistent with its generation mode.

## Confirmed fatal failure

The visual composition rendered successfully, including NVENC and split scenes.
Audio mastering then raised `Audio mastering changed stream timing`; the quality
gate exposed only the generic `AUDIO_MASTERING_FAILED` code.

This was reproduced on a separate copy of the real exported clip. Before
mastering, video duration was 59.025633s and audio duration 59.020s. After the
normalization/AAC processing pass, video duration was unchanged but audio became
59.100s. That 80ms extension exceeds the existing 60ms preservation tolerance.
Loudness/peak processing itself succeeded: -16.03 LUFS and -2.71 dBTP.

The normalization chain now limits its output to the original **audio** stream
duration when available. It does not trim to video length or reset timestamps.
The same post-encode loudness, peak, stream-preservation and synchronization
checks remain mandatory. Missing duration retains the existing checked path;
it does not guess a shorter source audio duration. Processing remains bounded
to two AAC attempts and 120 seconds. Audio cache version 2 prevents old receipts
from bypassing the updated behavior.

Timing errors now retain stream, field, before/after values, difference and
tolerance in the quality report and emit a safe measured reason in job logs.
Raw FFmpeg commands, output and secrets are not copied into those errors.

## Separate Gemini failure

The first visual chapter received a server-side `400 INVALID_ARGUMENT`, unlike
the earlier local SDK `exclusiveMinimum` conversion failure. This log gives no
specific rejected argument. The currently installed SDK successfully converts
the chapter schema locally. Google documents that only a schema subset is
supported and deeply nested/complex schemas may be rejected; that is a possible
cause, not a proven diagnosis for this request.

Reference: [Google's structured-output limitations](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en).

Chapter analysis now makes one compatibility transition after a typed 400
INVALID_ARGUMENT: reuse the uploaded active video and model, request JSON with
the schema in its prompt, and validate the result with the same full local
Pydantic model. Invalid evidence timestamps remain rejected. Repeated 400s stop;
authentication and blocked-content handling remain unchanged. The existing
three-attempt request cap also covers this compatibility path. This is a safe
recovery attempt, not proof that video analysis will succeed for every 400.

No live Gemini generation was performed during this fix. Provider availability,
model/video compatibility and successful multimodal analysis remain unverified.
The user's log had already fallen back to transcript selection; this recovery
does not improve or reselect that particular story.

## Verification and recovered output

50 existing audio-mastering/schema tests passed. Another 168 story-selection,
provider retry/block, quality/API and new regression tests passed: **218 unique
Python tests**. Python compilation passed. The tests include quiet/loud audio,
sample rates, silence, delayed clocks, explicit music/noise/fades, bounded
retries, interrupted writes, deterministic processing-tail padding, short audio
tracks, structured failure diagnostics and mocked Gemini upload/retry/cleanup.
The entire application/frontend suite was not rerun.

`output/job-audio-review/recovered.mp4` was mastered and validated locally:

- Mastering PASS after one encode attempt; -16.03 LUFS, -2.71 dBTP.
- Technical export validation PASS, 1080x1920 H.264 with AAC audio.
- Encoded video payload hash exactly matches the user's failed export: no video
  rerender, layout changes or repeated AI/transcription work.
- `recovery-report.json` records mastering, validation and unchanged payload.

The failed job's original files/status were preserved. The recovered copy is a
separate review/download artifact; it was not silently published into the old
job or marked as newly generated through Gemini.

## Changed files and manual checks

- `audio_mastering.py`: source audio duration limit, versioned receipts and
  measured `TimingError`.
- `export_quality.py`: structured timing diagnostics and safe error logging.
- `story_director.py`: bounded typed-400 JSON compatibility request.
- `tests/test_job_audio_failure.py`: two local audio/report regressions.
- `tests/test_gemini_chapter_compatibility.py`: four no-network provider tests.
- This document, `docs/GEMINI-SCHEMA-COMPATIBILITY.md` and `LOCAL_README.md`.

After current jobs finish, restart the application to load these changes. Review
the recovered clip now, or retry the source to exercise live visual analysis.
The new job should retain its strict audio quality gate. If Gemini again rejects
both request forms, transcript fallback remains explicit rather than being
presented as successful visual analysis.

Suggested commit: `fix(export): preserve mastered audio duration and recover rejected chapter requests`
