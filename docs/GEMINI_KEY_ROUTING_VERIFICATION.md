# Gemini key routing verification

Checked on 2026-10-19 using the configured `gemini-3.5-flash-lite` model. User-authorized live tests sent only a tiny text prompt, `Reply OK only.` No source media or transcript was uploaded.

## Live results

| Key label | Metadata HTTP status | Tiny generation HTTP status | Result |
| --- | ---: | ---: | --- |
| `.env` GEMINI_API_KEY_1 | 200 | 200 | Working |
| `.env` GEMINI_API_KEY_2 | 401 | Not attempted | Authentication rejected |
| Saved slot 1 | 200 | 200 | Working |
| Saved slot 2 | 200 | 200 | Working |
| Saved slot 3 | 200 | 200 | Working |
| Saved slot 4 | 200 | 403 | Generation forbidden |
| Saved slot 5 | 200 | 200 | Working |
| Saved slot 6 | 200 | 200 | Working |
| Saved slot 7 | 200 | 403 | Generation forbidden |
| Saved slot 8 | 200 | 200 | Working |

The seven successful responses reported a combined 35 tokens. There was no 429 quota response during these probes. HTTP 401/403 does not establish a remaining-credit balance or a daily spending limit. This API-key check cannot read the account's billing balance or remaining daily video allowance. Successful tiny text generation also does not prove that a three-minute video request will meet the timeout or its separate throughput limits.

## Confirmed configuration fault and fix

The desktop loaded the two `.env` keys, but then unconditionally replaced them with the older encrypted eight-key pool. A saved UI credential could also have taken precedence before that override. This made `.env` edits ineffective.

Explicit `.env` keys now form the authoritative pool. The older protected pool is used only when no explicit file keys are configured. If neither exists, the existing saved UI credential behavior remains available. All configured numbered keys are supported in numeric order; reading only slots 1 and 2 was removed.

A local fingerprint-only health record temporarily excludes keys returning HTTP 401/403 for this model. The exclusions expire after one hour or are superseded by another explicit health check. Changed key strings have different fingerprints and are eligible immediately. Transient network errors do not disable a key. If all explicit keys are rejected, the application does not silently fall back to an older account.

Current verified desktop/job assignment:

- Key source: **env**.
- Usable pool size: **1**.
- Primary: matches `.env` **GEMINI_API_KEY_1**.
- `.env` key 2: excluded following HTTP 401.
- Older saved keys: absent from this pool.
- Three simulated job assignments selected only the working first key.

Safe job diagnostics now include `Gemini chapter: key slot 1/1 from env`. No key text or provider error body is logged. This identifies a configured slot/source, not a billing account identity. Keys are not copied into this report or the public probe output.

## Verification and use

85 targeted Python tests passed, covering precedence, health expiry/model scope, worker assignment, key failover, analysis recovery and local security. Release native build passed with zero warnings and zero errors.

Sanitized live probe results: `build/gemini-key-health.json`.

Fingerprint-only routing health: `.local-gemini/key-health.json` (ignored local data).

Future explicit probe command:

```powershell
.venv/Scripts/python.exe tools/check_gemini_keys.py --output build/gemini-key-health.json --save-health
```

That command performs tiny **live** generation calls and can incur token usage. `--include-saved` additionally checks the old protected slots. No automatic paid preflight was added to every job.

Updated executable: `build/gemini-key-routing/OpenShorts.Desktop.exe`. Close the previous application and reopen this build before creating a new job. Already-running worker processes keep their original credential environment; they were not interrupted or restarted automatically.

The credential-precedence bug and observed rejected-key assignment are fixed. Persistent server timeouts and large-video latency are separate from key authentication; no full video generation was performed during this check.

Modified source: `desktop/gemini_keys.py`, `desktop/processes.py`, `story_director.py`, `desktop/generation_review.py`.

Added source/tests: `tools/check_gemini_keys.py`, `tests/test_gemini_key_precedence.py`, this report.

Backups: `build/backups/gemini-key-precedence-20261019`.
