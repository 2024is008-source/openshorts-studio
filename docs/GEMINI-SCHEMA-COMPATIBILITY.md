# Gemini schema compatibility fix

For the separate server-side `400 INVALID_ARGUMENT` and audio failure, see
[job recovery and bounded JSON compatibility](JOB-AUDIO-AND-GEMINI-RECOVERY.md).
That later response does not establish another local SDK conversion defect.

A user generation failed at chapter 1/20 with `Schema ... evidence ... end.exclusiveMinimum: Extra inputs are not permitted`. The installed Google GenAI SDK rejects `exclusiveMinimum` while converting Pydantic models to its own `Schema`. Pydantic emits that property for `Field(gt=0)`. This happens during request preparation, before Gemini can analyze the chapter, so the existing transcript-only selection fallback is used.

## Diagnosis and change

The failure was reproduced locally through the actual installed SDK's `_transformers.t_schema` conversion, without credentials or a network request. Chapter analysis, detail selection and visual selection failed; score and summary schemas converted successfully. Constructing `GenerateContentConfig` or mocking `generate_content` does not exercise this conversion, which explains why the earlier verification missed it.

`story_director.py` evidence end times and `gemini_worker.py` detail end times now emit the supported inclusive `minimum: 0`. Local Pydantic field validators still require end times greater than zero. Finite-number checks, strict evidence types, source-range checks and grounded-evidence validation remain in place. No SDK upgrade, new provider, weakened local timestamp validation or renderer change is required.

## Verification

`tests/test_gemini_schema_compatibility.py` adds 16 regressions: actual SDK conversion of seven provider schemas, rejection of zero/negative/NaN/infinite end times, and preservation of small positive timestamp precision.

The compatibility, multimodal story detection, story director/selection, Gemini retry/block handling, clip selection and local-backend suites passed: **173 passed**, `logs/gemini-schema-fix.xml`. No live Gemini generation was rerun; this verifies the previously failing local request-conversion boundary.

## Apply to a running application

The current generation process has already loaded its old Python schemas and selected the transcript fallback. Let it finish, then restart the application and rerun the video to exercise visual analysis with the corrected schemas. Do not interrupt a useful running job solely to reload this fix. A new failure should be assessed from its own error message; this change does not certify provider availability, credentials or quota.

Changed files: `story_director.py`, `gemini_worker.py`, `tests/test_gemini_schema_compatibility.py`, this document, `LOCAL_README.md`, and the TASK-011 report follow-up.

Suggested commit: `fix(gemini): keep response schemas compatible with SDK timestamp bounds`
