# Gemini chapter failure and efficiency fix

**Later correction:** the 12-MiB inline policy described below caused real transfer timeouts. The current implementation limits inline video to 2 MiB and uses uploaded file references for larger chapters. See [Gemini video transfer correction](GEMINI_VIDEO_TRANSFER_FIX.md) for the authorized live test and current behavior. The measurements below describe the earlier optimization snapshot.

Verified 2026-10-19. No paid Gemini requests were made.

## Diagnosis

The latest failed job, `6221bf8e-06d3-4939-8143-11e18f7e9985`, retained five successful chapters and recorded `ServerError` on chapter 6/10. Two earlier failure records showed `ReadTimeout` and `WriteTimeout`. The old diagnostics did not preserve the provider status code, so the exact latest HTTP status cannot be reconstructed safely.

The previous retry test primarily searched exception messages. HTTP transport timeouts can have empty messages, so those failures could escape retries. Chapters also ran serially, and the normal path always uploaded a proxy and polled its processing state. Failed jobs retained local checkpoints, but a new job directory did not automatically reuse them. The UI's previous highest-completed-chapter calculation would also overstate progress once chapters ran concurrently.

## Changes

- Recognize typed HTTP timeouts, connection errors, remote protocol errors and transient provider statuses. Empty-message errors now retry.
- Retry transient generation failures up to three attempts against the same media input. Keep authentication/quota key failover, strict schema validation, concise-response repair and policy-block behavior.
- Use a 90-second HTTP request timeout, a four-minute retry scheduling budget and a bounded file-processing wait. An in-flight request can finish after the scheduling budget; this is not a hard wall-clock cancellation guarantee. SDK automatic retries remain disabled so they cannot multiply application retries.
- Use two chapter workers by default, bounded to at most three. Each chapter starts at a different configured key slot without changing shared environment variables. Extra keys do not increase a provider account's quota.
- Stop scheduling new work after a known failure. Allow already in-flight work to finish and checkpoint its successes. No unvalidated partial result or transcript-only substitute is published as visual analysis.
- Preserve completed out-of-order chapters separately from the legacy contiguous checkpoint list. Resume skips both kinds of successful work and restores deterministic chapter ordering before selection.
- Use inline video for proxies at or below 12 MiB. Larger proxies retain the upload/poll/delete path, with transient upload/poll recovery. Inline media avoids those separate round trips; it does not eliminate the generation request or its network transfer.
- Use a more efficient `veryfast` proxy preset with two encoding threads, retaining the previous 640-pixel maximum width, 8 fps, CRF 28, source audio and exact chapter timing.
- Set explicit minimal thinking for Gemini 3 Flash-Lite and low thinking for other Gemini 3 analysis models. Local validation and grounded source-evidence requirements remain in force.
- Add a desktop-local cache for matching successful chapter checkpoints across attempts. Reuse requires the exact existing source size/mtime, duration, model, transcript and analysis-policy key. Changed input/settings cause a miss. Matching legacy job checkpoints can be adopted. Cache retention is 30 days and at most 64 source-analysis entries; deleting the normal application cache removes these reusable copies. Original project checkpoints remain separate.
- Preserve section-recovery checkpoints in the reusable desktop cache where available.
- Report completed chapter counts rather than the highest chapter number, and expose safe timeout/server/status diagnostics without provider bodies, source text or API keys.

Google documents [inline video for small requests](https://ai.google.dev/gemini-api/docs/video-understanding) and [thinking-level controls](https://ai.google.dev/gemini-api/docs/gemini-3). The 12 MiB file limit leaves room under the documented 20 MB request-size threshold for base64 encoding and the prompt.

## Measured results and limits

Real local encoding used `D:\1016.mp4`; no frames or audio were sent to an AI service:

| Check | Result |
| --- | --- |
| Optimized 180-second proxy preparation | 6.14 seconds |
| Proxy size | 10,141,880 bytes, fits the inline threshold |
| Probed duration/frame rate | 180.0 seconds, 8/1 fps |
| Ten mocked chapter requests, one worker | 0.8255 seconds |
| Ten mocked chapter requests, two workers | 0.4128 seconds |
| Mock orchestration speedup | 2.00× |
| Gemini requests during verification | 0 |

The 2× number measures mocked orchestration, not live Gemini latency or full-job speed. Live provider congestion, persistent service errors and quota restrictions can still fail requests after bounded recovery. Two workers can increase concurrent quota demand. No claim is made that client changes can repair a provider outage.

The five successful chapters from the latest failed job were copied into the exact-key reusable cache. The failed job and its failure state were not modified or restarted. Reuse on the next attempt requires matching source/model/transcript identity.

## Verification

- 217 targeted Python regression tests passed, with mocked Gemini responses.
- 31 focused UI/progress/native-contract checks passed after the completion-display changes; these overlap the regression suite.
- Additional final provider-configuration checks cover timeout handling, bounded retry, key selection and recovery.
- 56 native C# tests passed.
- Release solution build passed with zero warnings and zero errors.
- Real local proxy preparation and FFprobe checks passed.

New deterministic tests exercise blank-message read/write/connect failures, small inline and large uploaded proxies, failed upload recovery, bounded 503 retries, separate chapter key starts, actual worker overlap, out-of-order checkpoint preservation, restart skipping, exact-key cross-job cache reuse, safe diagnostics and truthful concurrent progress.

Evidence:

- `build/gemini-efficiency-python.xml`
- `build/gemini-efficiency-ui.xml`
- `build/gemini-efficiency-test-results/gemini-efficiency.trx`
- `build/gemini-efficiency-verification/benchmark.json`

## Files and running the update

Modified: `story_director.py`, `desktop/processes.py`, `desktop/generation_review.py`, `native/OpenShorts.Desktop/ClipperWorkspace.cs`.

Added: `tests/test_analysis_efficiency.py`, this report.

Pre-change source backups: `build/backups/gemini-efficiency-20261019`.

Updated executable: `build/gemini-efficiency/OpenShorts.Desktop.exe`. This is a source-backed build using this workspace's existing Python/media runtime. Close the previous application and open this build before starting the next attempt so the new desktop cache configuration and progress display are loaded. Existing running jobs were not interrupted. No live Gemini job was started automatically.
