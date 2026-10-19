# Local highlight learning

The native Editor's **AI Learning → Highlight ranking** section uses the existing SQLite knowledge store and logistic trainer. It is separate from effect learning. No dataset is uploaded and no AI provider is called by collection, training, evaluation or inference.

## Review a candidate

Open a newly generated clip in the Editor and choose **Snapshot current clip**. This identifies the immutable candidate recorded before rendering. Accept or reject the clip explicitly; rejection requires a reason. Ratings, preferred trims, alternative source ranges, category corrections and caption-style preferences have separate actions. Existing effect correction controls continue recording operational effect changes.

Only explicit acceptance/rejection supplies a binary relevance label. Selecting an alternative records a pairwise preference; it does not declare the original clip irrelevant. Autosave, unchanged settings, exports, view counts and weak selection events are not positive labels. Repeated identical actions do not amplify training weight. A changed explicit verdict supersedes the previous verdict for that candidate.

Boundary fields use source seconds, stay inside the original candidate, and record feedback without editing the timeline. Category corrections and preferences do not rewrite prediction-time features. Existing manual edits and approved ranges are protected from optional learned reranking.

Older clips without an immutable ranking snapshot remain editable/exportable. Their ranking-review endpoint explains that no snapshot is available; the system does not reconstruct a supposedly original feature vector from post-export/manual outcomes. Existing labels are not invented or copied from Gemini predictions.

## Storage and privacy

The database is `<selected library>/learning/editing-knowledge.sqlite3`. Precedence is `OPENSHORTS_LEARNING_DIR`, then `OPENSHORTS_LIBRARY/learning`, then `%LOCALAPPDATA%/OpenShorts/learning`. The native app supplies its chosen library. Schema 1 and existing tables are reused; clip rows carry `task="highlight-ranking"`, and old effect rows/artifacts without a task remain `effects`.

Clip records contain a source-content SHA-256 group, candidate ranges, bounded numeric features/missingness, categories, saved comparator scores, provenance and explicit feedback. They exclude media paths, dialogue, raw captions, titles and export popularity. Collection/retrieval/inference settings remain local. Inference is OFF by default and requires a separately activated model. Upload remains disabled. Turning collection off prevents new candidate/feedback collection; status does not persist dataset snapshots. Retention excludes expired examples from training without rewriting customer projects.

The existing explicit Delete local learning action clears owned knowledge/model records and artifacts. It now preserves opt-out preferences and unrelated files placed in the learning directory. It is never invoked automatically by export or training. Backups/corrupt database recovery remain available through the existing store.

## Train, evaluate and activate

1. Collect real explicit verdicts across independent source videos and supported categories. Synthetic fixtures are excluded from real readiness.
2. Request **Train highlight candidate**. This uses the same bounded CPU logistic optimizer and safe JSON registry as effect learning; it never starts automatically on export.
3. Use **Training status** and **Refresh** to inspect readiness, candidate ID and held-out results. There is no fabricated percentage progress.
4. A candidate remains inactive. Explicit approval/activation checks dataset/feature/artifact identity, real provenance, sufficient data, source-grouped holdouts and improvement over both saved baselines. Synthetic models cannot be promoted.
5. Enable local inference only if desired. Missing/corrupt/incompatible/unsupported models fall back to existing selection. Rollback deactivates the selected task's model and preserves the other task's active model. Reapproving a rolled-back highlight model rechecks its evaluation.

Default readiness requires 100 explicit examples, 10 independent source videos, two categories and both labels in each train/validation/test partition. Promotion additionally requires paired held-out candidate queries and sufficient category/subcategory coverage. No separate category-specific trainer is introduced. Shared category-aware features cover podcast motivation/education/comedy, challenge, cricket and football; unverified crowd noise is not an event label.

Precision@K, Recall@K, NDCG@K, Brier error, available boundary correction error, negative-review reasons and category results are recorded. Source video groups never cross partitions. Unreviewed candidates are excluded rather than treated as negatives, so metrics describe the reviewed subset and may be selection-biased. Saved deterministic weighted scores and actual Gemini-assisted scores/hybrid adaptive priorities are compared when available; missing comparators block promotion. Raw logistic scores are not advertised as calibrated probabilities.

No improvement is claimed before real held-out evaluation. With insufficient real data, complete feedback collection/evaluation infrastructure remains usable and the learned ranker stays inactive.

Content hashes identify exact source copies. Curate re-encoded/derived footage into source families before production evaluation; semantic duplicate detection is not claimed.
