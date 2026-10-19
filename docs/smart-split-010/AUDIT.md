# TASK-010 audit

- `clip_selection.speech_units`, `pacing.boundaries`: complete utterance boundary closure, retained speaker/word timing, visual story protection already exist.
- `recut.normalize_segments`, `run_cut_concat`, `virtual_transcript`: real noncontiguous assembly and caption remapping already exist. Reuse the source recipe rather than another Director.
- `continuous_cut_command`: single audio encoding and 8ms join fades already exist; these are de-click fades, not a true overlapping crossfade or J/L cut.
- `editing_director.compile_plan`: source/output segment map, per-shot context and skills run after assembly. Keep this order.
- `timeline_render.render`: shared preview/export compositor and canonical source mapping; existing correction path remains authoritative.
- `learning`: unreviewed collection and explicit human review gates already exist; use operational records, no training activation.
- Missing: automatically invoked safe split/removal planner with saved reasons, final source-map receipt, category-aware removal vetoes and explicit track-edit rendering.
- Partial: semantic relevance decisions require existing visual/Story evidence; transcript repetitions alone do not establish that a repeated action is redundant.
- Default: chronological hard cuts. Reordering can change causality, so no category recipe forces it. Unavailable beats remain unavailable.
