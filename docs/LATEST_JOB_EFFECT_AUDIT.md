# Latest job effect audit

Job: `d6e6fc22-e3ef-4a55-8d51-16b16bbf1f87`.
Checked 19 October 2026 against its metadata, all five saved edit plans, skip decisions and final MP4 render receipts. No AI calls or regeneration were performed.

Visual analysis completed successfully and retained 65 editing cues over the source. These are proposed editorial events, not 65 rendered effects. The five selected clips retained 32 cue entries across their render shots, including repeated cue intersections with shot boundaries.

| Clip | Enabled added AI effects | Layout shots |
|---|---|---|
| Surprising A Kid With A $25,000 Bionic Arm! | None | 28 full-view/blur |
| Holding a Genetically Modified Animal! | None | 21 full-view/blur |
| I Installed a Real Rocket Tile! | One `keyword_highlight`, local 29.84–34.12s | 17 full-view/blur; 5 subject-track |
| Driving a $1M Car Upside Down! | None | 23 full-view/blur |
| Can You Tell Lab-Grown Chicken From Real? | None | 19 full-view/blur; 4 subject-track |

Across the five outputs, no added zoom, shake, split-screen, AI sound-effect or special transition effects were selected. Cuts and source-video graphics may still be visible. Opening hooks were explicitly disabled (`AUTO_HOOK=0`) and all five edit plans retain disabled hooks.

The first four clips in metadata use the Story Focus template with cinematic captions. Rocket Tile uses the Challenge template with creator-bold captions. The user-level caption option is green-pop, but the template render path uses each selected template's caption preset. The review dropdown label alone is not evidence of the already-rendered caption style. All five final receipts confirm a rendered overlay passed its pixel-change check and an actual 1080 × 1920 NVENC output was produced.

The auto-edit decisions contain 48 skip entries:

- 25 camera-effect entries: extra magnification would discard a retained subject, object or shared scene.
- 19 text-emphasis entries: the proposed quote did not match retained speech near the cue inside the shot.
- Four number-highlight entries: the proposed quote contained no retained numeric token.

These are per-shot decision counts, not necessarily distinct original proposed events. A cue crossing multiple cuts can produce multiple skip entries.

The Rocket Tile effect targets the engineer's warning quote. A decoded final frame at 31.5 seconds shows the Challenge caption styling and yellow emphasis. The frame alone cannot distinguish every contribution of the template's regular word highlighting from the additional semantic keyword effect; the saved plan and template render inputs establish that the effect was enabled.

Evidence snapshot: `build/output-effect-audit/latest-job/audit.json`.
Decoded output frame: `build/output-effect-audit/latest-job/rocket-highlight.png`.

Conclusion: four clips have zero added AI effects, and one has a text-only effect. Scene analysis worked; most proposed effects were filtered before rendering. This audit does not establish that every rejection was editorially appropriate, especially the repeated quote-matching rejections.
