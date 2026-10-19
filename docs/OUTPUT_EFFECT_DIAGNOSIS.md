# Output effects diagnosis and live verification

Verified 18 October 2026. See [the engine capability inventory](VIDEO_ENGINE_CAPABILITIES.md) for the complete feature matrix.

## What failed in the supplied output

The supplied job `78495efc-bdfa-453d-9fa6-10bbd3e73e75` requested hybrid analysis and automatic editing. Its ten retained clip plans contained no semantic editing cues or effects. The job recorded selection fallback and had no retained visual story analysis. A finished video therefore did not establish that AI scene understanding had succeeded.

The installed Google SDK rejected the editing-cue schema's `exclusiveMinimum` property before it could submit the structured analysis request. The timestamp field now uses SDK-compatible bounds, with strict ordering validated locally. A separate bounded JSON compatibility retry also handles structured-request `400 INVALID_ARGUMENT` responses without dropping local result validation.

Generation now records whether visual analysis completed or fell back. The review page displays a clear warning when visual analysis failed, including older hybrid jobs with no retained analysis. Raw provider errors and API keys are not displayed.

## Scene and effect decisions

Broad narrative moments previously could impose the same framing across several different camera shots. Analysis now supplies per-shot observations: visible action, shared context, shot type, layout evidence and timed editing cues. Shot observations take precedence over broad narrative framing. Neighboring observations must overlap sufficiently before affecting a shot.

Speech emphasis is matched to retained words near the proposed cue and uses their actual audio timing, including words spanning a picture cut. Invalid number cues and unmatched quotes are rejected with a saved reason.

Split layouts remain conditional. Separate useful views can justify a split; two crops repeating shared action do not. Keeping both people and an object visible in one wide view is appropriate when their interaction depends on that shared space. These rules improve the available evidence and constraints; they do not guarantee human editorial judgement.

## Authorized live sample

The user authorized a short Gemini sample. Only seconds **20–50 of `D:\1016.mp4`** were used for live provider analysis. Two successful analyses used this same 30-second sample while verifying the corrections. The full 12-minute source was not submitted for analysis.

The final saved result contains 11 semantic shot observations. Local scene detection produced 17 render shots: 14 preserve the full view over a blurred background, and three use tighter subject framing. One grounded spoken-number cue (`105`) was applied. A proposed number cue without a number and an unmatched emphasis quote were skipped. The shared supermarket action did not justify a duplicate split.

Final export: `build/output-effect-audit/shot-analysis/1016-live-scene-aware.mp4` (1080 × 1920). The export passed the engine's quality checks, and a decoded output frame visibly confirms the number emphasis. Evidence and skip reasons are in the adjacent `render-result.json` and `.edit.json` files. Local replay/rendering made no additional provider calls.

A separate controlled two-region fixture exercised the actual split renderer and produced a `SPLIT` output. This verifies the render path with controlled geometry; it is not proof that arbitrary real-world subjects will always be detected correctly.

## Validation

- 116 focused Python tests passed across SDK schema conversion, retries, shot policy, automatic effects, review status and split rendering.
- Native Release build succeeded with zero warnings and zero errors.
- Isolated native acceptance passed review, playback, cancellation, recovery, duplicate independence, preview updates and real 1080 × 1920 batch exports. Provider job status was mocked in this UI test; it made no paid requests.
- The native test confirmed that the visual-analysis fallback warning is visible. Captures and machine-readable results are under `build/output-effect-audit/native-check`.

The user's existing output videos were preserved. They need fresh successful analysis and rendering to gain these decisions. This verification does not certify every effect in the capability inventory or a complete long-video generation run.

## Follow-up: malformed chapter response

The later `f127b737-1a00-4040-8f3d-6a91081c2f69` job was configured for hybrid analysis, but recorded `JSONDecodeError`, no visual analysis and zero editing cues. Its clip selection succeeded separately. The raw failed provider response was not retained, so its exact formatting or truncation cause cannot be established retrospectively.

Chapter analysis now explicitly allows up to 32,768 output tokens and requests concise, nonduplicated observations. Complete fenced JSON is accepted and still schema-validated. Empty, malformed and token-truncated responses trigger at most one concise response retry on the same uploaded chapter, within the existing three-attempt ceiling. SDK-level JSON decoding errors use the same recovery. Truncated parsed objects and trailing garbage are rejected rather than repaired into invented scene evidence. Retry response usage is included in the returned cost estimate when available.

Invalid semantic values still fail strict validation; exhausted retries still expose the existing fallback warning. Successful chapter checkpoints survive a later failure. No cache version bump forces previously successful analysis to be purchased again.

Verification: 170 relevant regressions plus one checkpoint-resumption regression passed (171 total). The native Release build succeeded with zero warnings and errors. Tests used local mocked provider responses, including the schema-compatibility retry followed by malformed JSON; no additional paid provider requests or full-video rerender were performed. Existing rendered clips retain their original decisions until regenerated.

## Follow-up: later chapter validation failure (19 October 2026)

Job `2d6c61c6-3163-4ff8-8987-6ca4f40d044f` retained two successfully validated chapter checkpoints (0–180 and 177–357 seconds), then recorded `ValidationError` and produced five fallback clips. This is a different error class from the prior JSON parsing failure. Its rejected payload and exact failing fields were not retained, so the specific invalid field cannot be reconstructed.

Validation failures now receive the same bounded response-recovery attempt, with rejected field paths and validator types included in the correction request. The schema itself remains strict. Failed chapter diagnostics are saved to `analysis_failure.json`, including chapter/range and completed checkpoint count. These diagnostics omit provider inputs, custom validation messages and credentials.

Hybrid mode now requires successful visual analysis. If recovery is exhausted, it stops before clip selection/rendering with an actionable error and keeps successful checkpoints, rather than substituting transcript-only generation. Transcript-only mode remains available when explicitly selected. Historical fallback clips retain their warning; their labels cannot establish successful analysis retroactively.

Local tests verify validation recovery, exhaustion, safe diagnostics and the CLI's refusal to render transcript-only clips in failed Hybrid mode. No paid provider calls were used to test this follow-up, and the full affected video has not been rerun.

### Exact chapter-eight failure

Job `e7963619-6b3f-402c-9710-4249a1c7db62` saved the missing field `scene_observations.7.layout_evidence` in chapter 8/8. Seven preceding chapter checkpoints validate successfully offline. The layout explanation is now optional, matching the existing moment contract: a shot with no explanation carries an empty evidence string and cannot supply an AI layout override. Other valid chapter observations remain usable; timestamps, cue evidence and enumerations remain validated.

The failure UI now uses the saved chapter diagnostic ahead of generic log matching. It shows the actual chapter and rejected field in View Details, and marks the analysis row Failed. The transcription error matcher no longer mistakes “No transcript-only clips were generated” for a transcription failure. Offline replay of this actual job confirms the corrected message. A local provider fixture reproduces the missing-field response and confirms it succeeds without a retry or invented layout evidence. No new provider requests were made.

### Unsupported descriptive labels

Job `3cf31b96-51dd-4e0b-86ff-eb67260237fc` failed on `scene_observations.7.shot_type` with `literal_error` in chapter 6/8, after five validated checkpoints. The exact rejected label was not saved. Previously, any unsupported descriptive label rejected the whole chapter even after the correction attempt.

Text labels outside the shot-type vocabulary now normalize to `unknown`; unsupported layout intents normalize to `uncertain`, and unsupported moment editing categories to `general`. Missing shot/layout classifications use the same conservative defaults. Recognized labels tolerate surrounding whitespace and letter case. This does not guess a synonym's meaning or authorize an unsupported split. Nontext classifications, invalid times, missing cue evidence and out-of-range confidence still fail validation. Local provider fixtures exercise multiple unsupported labels without additional requests and verify no split is authorized. The full source has not been submitted for another paid verification run.

### Malformed final chapter: verified shorter-section recovery

Job `744978ce-5fce-4efe-9ef0-55c69ee675de` retained seven successful chapters but exhausted response recovery on invalid JSON in chapter eight. Repeating a similarly large response was insufficient. Content failures in chapters longer than 60 seconds now trigger a bounded recovery using sections of at most 60 seconds. Each section uses the existing bounded request policy; authentication/service failures do not trigger this extra content path. Short-section failure still stops Hybrid generation rather than fabricating observations.

Section results are independently validated and checkpointed. Local section times are mapped back for moments, scene observations, editing cues, scene cuts and story evidence. Out-of-section evidence is rejected, not clamped. Restarting section recovery skips successful sections and the already-failed whole-chapter attempt. Per-chapter checkpoints for successful earlier chapters remain unchanged.

The user explicitly authorized a paid test of only final source seconds **1239–1383.0817**. The real recovery path succeeded using 60s, 60s and 24.0817s sections, with no preceding chapter resubmitted. It completed in 67.25 seconds and produced five usable moments, 21 shot observations and four editing cues. The engine estimated the successful section responses at $0.106239; this is an estimate, not a verified invoice. Results are in `build/output-effect-audit/final-chapter-recovery/live-result.json` and `live-analysis.json`.

The validated chapter was saved into the original job's analysis cache after checking timestamp bounds, bringing its cache to eight chapters. `story_analysis.before-final-recovery.json` preserves the original seven-chapter cache. `analysis_recovery.json` records the recovery. The failed historical job was not requeued: clip selection and full rendering were not run, and no further paid generation was performed. This verifies the previously failing analysis stage, not a completed end-to-end render.
