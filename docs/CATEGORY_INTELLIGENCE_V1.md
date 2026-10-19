# Category Intelligence v1

The native Video Ready window detects a suggested category after importing a local file or supported URL. Initial classification uses representative, timestamped speech and local measurements. If the local Whisper model is already installed, preflight samples at most three 12-second audio intervals; it never downloads a model. Missing speech or uncertain classification can use three representative JPEG frames. This can use the configured Gemini account's quota. No full source video is uploaded for category classification.

The AI Options tab shows the suggestion, source intervals, method, uncalibrated model estimate and review status. Category/subcategory controls override the suggestion. Detect again preserves the current selection; Use suggested category is an explicit confirmation. New sessions default to Adaptive Balanced and automatic captions. Saved analysis modes and caption styles remain valid. Legacy Transcript and full-video Hybrid remain explicit comparison choices.

| Category | Subcategories | Existing editorial behavior |
|---|---|---|
| Podcast | Auto, motivation, education, comedy | Complete ideas; explanation/takeaway or setup/punchline; stable framing and pauses |
| Challenge | Auto, competition, survival, experiment, general | Stakes, attempts, obstacles and supported outcomes; independent local visual discovery |
| Sports Highlights | Auto, cricket, football | Local activity/audio windows plus commentary; video verification; field/action context preserved |
| General | Auto | Mixed evidence, conservative effects and framing |

Movie, gaming, tutorials, vlogs and standalone comedy are not supported categories in this registry. Existing legacy IDs, including podcast-education, cricket, football and default_clipping, remain readable. Combined engine IDs retain the selected subtype in existing generation settings without a project-schema rewrite.

## Shared engine and safety

`category_intelligence.py` supplies the versioned taxonomy, structured classifier, grounded observation references, selection precedence and declarative policies. Adaptive analysis reuses its existing local media index, Gemini gateway, budget ledger, candidate discovery, source-time verifier and shared ranker. Manual category selection skips automatic generation-time reclassification. Discussion about football is insufficient evidence of match footage. Uncertain or mixed suggestions use General until the user selects a category. Still frames establish context, never a goal, wicket or match result.

The existing Editing Director and `auto_edit` remain responsible for planning and rendering. Policies can only narrow existing proposals; they never create effects from genre alone. Allowed AI effects are keyword/number emphasis, bounded smooth push/pull, punch-in and snap zoom as appropriate. Sports suppresses camera effects and number highlights because reliable ball/scoreboard detectors are unavailable. Existing scene-context guards, protected geometry, word grounding, spacing and Balanced zoom limits remain authoritative. Manual effects remain editable and survive compatible regeneration. Unsupported and delegated timed effects are not introduced.

Automatic captions resolve to existing clean-minimal or dynamic-highlight presets after category selection. Explicit styles remain authoritative. Changing category or caption style does not regenerate source transcription. Old timelines and projects still reopen through the existing schemas.

## Caches and learning

Source-derived media indexing is independent of the selected category. Derived story/ranking decisions have category-sensitive keys; classification keys include source fingerprint, supplied observations, configured model, taxonomy and classifier prompt versions. With OPENSHORTS_LIBRARY configured, verified full transcription is shared across jobs under cache/source-analysis/full-asr using the source SHA-256, size, duration and transcription configuration. Legacy job checkpoints and externally supplied transcripts cannot populate that shared cache. Preflight reuses a verified full transcript when available and retains bounded sampled ASR separately. Sampled speech does not produce a full-source speech-density claim. Source indexing is shared under cache/source-analysis/index unless an explicit analysis-cache override is configured.

The existing SQLite store, grouped datasets, logistic trainer, model registry and privacy controls are reused. Highlight snapshots contain versioned category evidence and retain the compatible 72-value rank vector. Unavailable scoreboard, ball tracking, speaker continuity and aftermath measurements stay missing. Category/subtype already enter the shared model through categorical features. Grounded category-specific payoff evidence can populate the existing payoff feature. No category-specific model is enabled automatically.

Explicit category corrections are operational metadata in `user_feedback`; no dialogue or media paths are stored there. They are not positive highlight/effect labels. Collection opt-out, explicit history deletion and retention apply. Classification source caches remain ordinary source-analysis caches, separate from learning history. Effect acceptance/rejection and clip relevance reviews continue through the existing native AI Learning panel. Undo is not automatically a negative label.

## Limits

Model-estimated confidence is not calibrated accuracy. Mock contract tests and synthetic rendering tests do not establish classification accuracy or ranking improvement on real videos. There is no automatic classifier training, no production ranker promotion, and no verified scoreboard/ball detector. Sports framing therefore remains wide and conservative. URL network downloading was not repeated against a third-party platform for this task; the existing validated URL-import handoff is reused. Installer licensing gates and clean-machine release blockers are unchanged.
