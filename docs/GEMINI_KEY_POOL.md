# Direct Gemini key pool

The temporary local router integration, override configuration and encrypted router credential were removed. The existing optional text-only compatible backend remains in source for prior installations, but the desktop worker explicitly selects `gemini` and has no router URL or credential.

Eight supplied keys are stored as a Windows current-user DPAPI encrypted pool in `.local-gemini/credentials.dpapi`, excluded from Git. The native primary credential is set to the first pool key; the previous encrypted primary is backed up in the same private directory.

Each newly submitted desktop job rotates its starting key in round-robin order. All eight keys remain available in its environment, without duplicates, as bounded failover slots. Direct Gemini selection and chapter analysis use the same ordered pool. A different explicit request key remains isolated from the shared pool. The desktop retains one concurrent processing job; adding keys does not increase rendering or GPU concurrency.

Existing chapter logic moves to another slot for authentication/key or quota responses. Retries are bounded and successful chapter/section checkpoints are retained. Schema or invalid-response errors use response recovery instead of assuming another key fixes the output. These keys may share project quotas; multiple credentials do not guarantee higher quota, successful generation or provider availability.

Read-only authenticated Google model-list requests succeeded for all eight keys. This validates accepted credentials, not the quota available for every model or a completed generation job. No paid generation calls were made during pool validation.

Restart the updated desktop app to load the direct Gemini pool. Local Whisper transcription remains unchanged. Logs and presentation adapters redact both common Gemini key formats and configured pool values.
