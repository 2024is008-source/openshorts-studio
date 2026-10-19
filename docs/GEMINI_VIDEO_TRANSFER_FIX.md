# Gemini video transfer correction

Verified 2026-10-19. This supersedes the previous 12-MiB inline-video policy in `GEMINI_ANALYSIS_EFFICIENCY.md`.

## Observed failure

The new screenshots and the latest failure record, job `7690e711-3d1f-4714-8e32-3f47ed9dd1d6`, show a **WriteTimeout** while sending video, with no chapters completed. Diagnostics confirm `key slot 1/1 from env`. The credential selection fix was active; text-key authentication was not the failing operation.

The previous implementation could attach about 10 MiB of video as base64 in a generation request and resend that body during retries. Meeting the provider's legal inline-size limit did not establish that a particular connection could send it reliably. The earlier tiny text pings and mocked transport tests did not verify this real video path.

## Live test explicitly authorized by the user

One 10-second sample from `D:\1016.mp4` was encoded and sent through the working `.env` key to the configured `gemini-3.5-flash-lite` model. The test uploaded the sample through the Files API, waited for ACTIVE processing, then made exactly **one generation request** using its file reference.

| Operation | Measured time |
| --- | ---: |
| Binary file upload | 6.12 seconds |
| File processing | 3.47 seconds |
| Video generation | 2.75 seconds |

The model returned a visible-action observation matching the grocery-store sample. The sample was 842,940 bytes. Provider usage was 948 input tokens and 41 output tokens, 989 total. Temporary local sample media was removed and remote file deletion was attempted in the cleanup block. This was a video-transport check with a small JSON response, not a live run of the full chapter schema or the full source job.

Sanitized evidence: `build/gemini-video-transfer/result.json`. No API key or raw provider error body is stored in this report.

## Changes

- Proxies larger than **2 MiB** now use the Files API from the first attempt. The generation request carries a file reference, not the entire base64 video.
- Uploads use a public seekable-stream interface with reads limited to **1 MiB**, rather than the SDK's usual eight-MiB chunks. No global SDK constants or installed package code are modified. File bytes and offsets are preserved.
- Small inline requests that encounter WriteTimeout/WriteError switch to file upload on the next attempt instead of resending the same inline body.
- A successful upload is reused for generation retries and removed during normal cleanup.
- A ReadTimeout during analysis of media longer than 60 seconds now requests existing short-section recovery after the first whole-chapter failure. Successful sections remain checkpointed and all observation/cue/story timestamps are mapped back to the chapter. No transcript-only substitute or partial JSON is accepted as visual analysis.
- Authentication, quota and generic provider failures do not trigger this long-media timeout recovery merely because they failed. Media transfer still has bounded recovery and a total retry scheduling budget.
- The details panel includes safe messages for transfer fallback and shorter-section recovery.

The working new key remains selected; rejected and older saved keys were not reintroduced.

## Verification

- **160 targeted Python tests passed**, including editor compatibility and credential selection.
- Deterministic tests reproduce an inline WriteTimeout, verify that the second request carries the uploaded-file reference, verify a single upload across retries, check exact byte preservation with bounded chunks, and exercise long-timeout section recovery and timestamp mapping.
- Python compilation passed.
- Release native solution build passed with **0 warnings and 0 errors**.
- Live 10-second Files API test passed with exactly one generation call. No additional live generation was used for the regression run.

Test results: `build/gemini-transfer-tests.xml`.

## Scope and running the correction

The complete 26:58 source job was not rerun. Live full-chapter schema quality, total job duration, and reliability during a provider outage are not established by the short test. The correction addresses the observed large inline-transfer failure and adds smaller-media recovery; it cannot guarantee provider availability.

Open `build/gemini-transfer/OpenShorts.Desktop.exe` after closing the previous application. An already-running Python worker retains the old transfer implementation; saving source files does not patch that process. Existing jobs were not stopped or restarted automatically.

Modified: `story_director.py`, `desktop/generation_review.py`.

Added: `tools/check_gemini_video_transfer.py`, `tests/test_gemini_transfer_recovery.py`, this report.

The live test tool performs a real generation call; it must not be rerun under a no-credit verification request without authorization.
