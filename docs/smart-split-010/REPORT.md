# TASK-010 implementation and verification

## Delivery status

The automatic Smart Split/removal path is implemented in the existing generation pipeline and produces real source recipes rendered by FFmpeg. This is a partial implementation of the full TASK-010 brief. Independent-track native editing, automatic B-roll insertion, visual comparison composition, advanced transitions, and learned assembly selection are not complete. They are not advertised as enabled features.

No paid provider calls, model downloads, Git initialization, customer-file deletion, licensing changes, or installer release were performed.

## Existing capabilities reused

- `clip_selection.speech_units` and `pacing`: word/sentence closure, existing highlight selection, protected visual context, silence measurements and boundary correction.
- `recut`: persisted noncontiguous source recipes, continuous decoded audio assembly, and virtual transcript mapping.
- `editing_director` and `auto_edit`: final assembled timeline, source-grounded captions, existing category policies and editing skills.
- `timeline_render` and native WPF: existing preview/export, corrections, draft persistence and regeneration.
- `learning`: local SQLite storage, collection opt-out, retention and existing explicit review requirements.

## Smart Split and content removal

`smart_split.apply` runs after the existing pacing pass in `main.py`. It changes actual `recipe.segments` before rendering, saves an `assembly_report`, updates canonical duration and story source ranges, and marks pre-assembly rankings stale. Nothing depends on a user placing split points.

Every report retains original ranges, final ranges, source/output maps, removal reasons, protected beats, and concrete hard-cut joins. Native review explains the removed duration and kinds of material.

Rules:

- Reject nonfinite/out-of-bounds source times and invalid confidence values.
- Keep word interiors intact. Semantic dialogue removal requires complete contained utterances.
- Preserve explicit story/action/reaction/result, comparison milestones, contextual shots and emotional/stakes dialogue.
- Disable this additional removal pass for Minimal, sports, comedy, locked or manually authored recipes.
- Remove long measured quiet intervals only with inspected low-value footage, or complete same-speaker turns in a non-comedy podcast. Keep breathing room on each side. A quiet challenge scene alone is insufficient evidence.
- Accept explicitly identified empty/redundant footage only with high-confidence visual evidence and no intersecting protected content or speech.
- Restrict semantic digression/redundant-attempt removal to challenges with explicit source observations. Exact duplicate explanations additionally require the same known speaker and an earlier identical statement still retained in the recipe.
- When evidence or bounds are insufficient, retain the footage.

Existing Gemini scene schema accepts editorial roles and an optional earlier duplicate timestamp. Chapter/recovery assembly shifts that timestamp with its source chapter. No extra provider request was added; cached older observations safely default to unknown.

## Story assembly and editing skills

Existing highlight and story selection remain responsible for finding meaningful candidates. Smart Split compresses their retained source sections chronologically. It does not invent missing beats or reorder chronology to satisfy a genre template. Verified before/milestone/after, action, result and reaction ranges are protected.

The existing Editing Director compiles the final recipe before generating effects. A new integration regression verifies that a number at source 6.0 seconds maps to output 2.8 seconds in both captions and skill opportunities after removal. Manual recipes remain authoritative after JSON save/reopen.

This does not yet add autonomous reaction relocation, B-roll search/insertion, cross-time split-screen comparisons, or milestone selection outside the already chosen candidate. Existing reaction emphasis and progression recognition remain available; they are not equivalent to those missing compositing operations.

## Audio and transitions

Production assembly uses chronological hard cuts with the existing single audio encoding and 8 ms de-click ramps. Those ramps are not represented as overlapping audio crossfades.

`recut.track_edit`, `track_command` and `render_tracks` now provide a real separate-track J/L adapter. Audio retains its source speech clock while a verified visual handle moves the picture join. Bounds, duplicate joins, durations and caller-supplied visual eligibility are checked. Plans serialize to JSON and render with FFmpeg.

J/L adapters passed isolated preview-size/export-size render checks, but are deliberately not activated in automatic WPF projects: their current EDL assumes a shared audio/video segment map. Native track-aware persistence and lip-sync eligibility need implementation before activation. Cross dissolve, fade-through-black, directional push and true overlapping audio crossfade remain unsupported; no metadata-only transition claims are made.

## Local learning

Assembly decisions are recorded as unreviewed operational records with a hashed source identifier, category, original/final boundaries, mapping, reasons and order. They carry `training_label=false`. Collection opt-out and retention apply; raw source paths and transcript text are not copied into these records.

Existing scene/effect review remains unchanged. Assembly-specific user correction/review capture and an assembly-trained model are not yet connected. Unreviewed records cannot be claimed as training examples.

## Validation

- Relevant Python regressions: **335 passed**, including director, pacing, recut, schema/recovery, learning and timeline/API tests.
- After final confidence/category/review changes: **42 passed** across Smart Split and generation review.
- Final Smart Split tests after story-range/ranking adjustment: **25 passed**.
- .NET: **71 passed**.
- Native desktop builds with **0 warnings, 0 errors**.
- `tools/validate_smart_split_010.py` creates actual test-pattern/tone videos: 4.8-second noncontiguous CPU and NVENC outputs; 6-second J-cut and L-cut preview/export controls. All six renders pass the existing media validator.
- Decoded source-frame comparisons before, at and after both CPU/NVENC hard cuts and at J/L visual boundaries pass. Preview/export J/L decoded audio is byte-identical.
- The assembled frame was visually inspected: expected test pattern and source timestamp, no unintended blank crop.
- Native preview/fullscreen/overlay/layout acceptance passed. The rebuilt current-source desktop also passed AI-effect undo/redo, manual override preservation through regeneration, save/reopen, and rendered preview (`auto-edit-result.json`, zero provider calls).

These are engineering fixtures, not proof of editorial quality on every source or category. No paid end-to-end Gemini generation was run. Tone controls do not demonstrate subjective spoken-dialogue quality. Human aesthetic evaluation, actual independent-track native parity, and full automation for the remaining operations are still required for complete TASK-010 acceptance.

## Artifacts

- Audit: `docs/smart-split-010/AUDIT.md`
- Saved assembly plan: `build/smart-split-010/assembly-plan.json`
- Sample: `build/smart-split-010/assembled-cpu.mp4`
- GPU sample: `build/smart-split-010/assembled-nvenc.mp4`
- J/L plans and videos: `build/smart-split-010/j_cut-*`, `l_cut-*`
- Render receipt: `build/smart-split-010/receipt.json`
- Python and .NET logs: `build/smart-split-010/regressions.txt`, `final-tests.txt`, `smart-split-final.txt`, `dotnet-tests.txt`
- Native acceptance: `build/smart-split-010/native/`
