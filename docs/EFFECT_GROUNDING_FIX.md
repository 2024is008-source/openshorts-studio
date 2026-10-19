# Effect grounding correction

19 October 2026. Audited job: `d6e6fc22-e3ef-4a55-8d51-16b16bbf1f87`.

The source analysis completed, but valid text effects were rejected for three implementation reasons:

- Matching searched only the current picture shot's words even when the speaker's sentence continued across cuts.
- Matching treated punctuation as part of the spoken token, so `Oh!` did not match `oh,`.
- Number cues required digits, rejecting spoken quantities such as `million dollars`.

Matching now searches the retained clip's timed words and constrains each generated effect to its own picture shot. Punctuation and case are normalized. A provider quote containing an unsupported extra phrase may contribute a substantial contiguous exact retained fragment; no fuzzy replacement words or paraphrased text are added. Emphasis marks only retained words that overlap the effect's active time. Word matching can continue across transcript segment boundaries.

Spoken English number words are recognized. Number phrases are anchored to nearby retained speech before assigning them to a picture shot, with a bounded two-second alignment tolerance. Empty visual-only number quotes still do not invent spoken numbers.

Replaying saved analysis produces these active text effects:

| Clip | Before | After |
|---|---:|---:|
| Bionic Arm | 0 | 2 number-highlight intervals |
| Upside-Down Car | 0 | 1 number-highlight interval |
| Lab-Grown Chicken | 0 | 0 |
| Genetically Modified Animal | 0 | 5 keyword-highlight intervals |
| Rocket Tile | 1 | 5 keyword-highlight intervals |

Intervals are per shot; repeated intervals can represent one spoken phrase crossing a picture cut. This is not a count of distinct editorial events. Existing effect limits and manual overrides remain in force.

Camera behavior is a separate constraint. Full-view/blur shots cannot use the current crop-zoom adapter without potentially losing edge content. The correction does not force zoom, split or shake into those compositions. The chicken clip's retained candidate still does not justify an added eligible effect. More eligible effects do not establish that every editorial choice is compelling.

Two local corrected MP4 previews (car and animal) were rendered from the existing clean clips, saved scene analysis and original sentence-grouped transcript. Both passed export quality checks. No original job media was overwritten and no new provider calls were made.

Evidence: `build/output-effect-audit/effect-grounding-fix/comparison.json`, corrected edit plans, `render-verification.json` and `corrected-clip-2.mp4` / `corrected-clip-4.mp4`.

Validation: 43 automatic-effect/API tests and 177 director, caption, template and review tests passed. Native Release compilation succeeded with zero warnings and errors. The two decoded corrected previews were inspected for caption layout. Existing original outputs still need regeneration to use the corrected decisions.
