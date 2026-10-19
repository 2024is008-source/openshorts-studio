# OpenShorts Studio initial source import plan

The existing private remote has commit `c3ab981` (README, LICENSE and .gitignore).
The nine section commits will be based on that commit. They describe one initial
source import, not the historical development dates of the files.

No remote push, develop branch or tag is part of the local review stage.
The requested GitHub account and private repository were verified through the
connected GitHub account; `gh` is unavailable in the local shell.

The exact per-file section assignment is in `repository-file-manifest.json`.
The manifest includes the prior remote README, LICENSE and .gitignore, which
will be updated in section 1 without rewriting their existing commit.

During the section 2 staged review, generated `cli/*.egg-info` was found and
excluded. The final manifest and .gitignore correction are included with the
section 2 commit; no application source was modified for this correction.

| Section | Commit message | Files | Bytes |
| --- | --- | ---: | ---: |
| 1 | `chore(repo): initialize OpenShorts Studio source repository` | 80 | 703,635 |
| 2 | `feat(engine): add authenticated desktop backend and workers` | 73 | 895,310 |
| 3 | `feat(ai): add multimodal analysis and clip discovery` | 17 | 397,694 |
| 4 | `feat(ml): add local learning and knowledge foundation` | 15 | 96,708 |
| 5 | `feat(editor): add autonomous editing and Smart Split` | 17 | 297,737 |
| 6 | `feat(render): add local video rendering and effects` | 59 | 2,317,392 |
| 7 | `feat(desktop): add native Windows AI editor` | 179 | 2,568,060 |
| 8 | `test: add desktop and AI engine verification` | 178 | 1,085,980 |
| 9 | `build(windows): add desktop packaging configuration` | 23 | 33,708 |

## Section inventory and scan status

### Section 1

- Important paths: `docs` (65), `.env.example` (1), `.gitignore` (1), `GPU_SETUP_WINDOWS.md` (1), `IMPROVEMENT_NOTES.md` (1), `LICENSE` (1).
- Largest files: `repository-file-manifest.json` (122,245 B), `docs/TASK-011-SYSTEM-VERIFICATION.md` (26,084 B), `docs/TASK-010-RENDERING-PERFORMANCE.md` (22,447 B).
- Secret scan: 1 reviewed placeholder/test-fixture findings.

### Section 2

- Important paths: `desktop` (30), `cloud` (25), `cli` (3), `app.py` (1), `desktop_entry.py` (1), `file_hosts.py` (1).
- Largest files: `app.py` (342,125 B), `saasshorts.py` (60,237 B), `cloud/billing.py` (32,978 B).
- Secret scan: no findings.

### Section 3

- Important paths: `adaptive_analysis` (8), `active_speaker.py` (1), `category_intelligence.py` (1), `clip_selection.py` (1), `gemini_worker.py` (1), `llm_backend.py` (1).
- Largest files: `main.py` (143,355 B), `story_director.py` (73,073 B), `gemini_worker.py` (27,530 B).
- Secret scan: no findings.

### Section 4

- Important paths: `learning` (11), `alembic` (2), `alembic.ini` (1), `clip_ranking.py` (1).
- Largest files: `learning/highlight_ranking.py` (18,173 B), `clip_ranking.py` (14,002 B), `learning/models.py` (12,374 B).
- Secret scan: no findings.

### Section 5

- Important paths: `assets` (3), `auto_edit.py` (1), `edit_builder.py` (1), `editing_director.py` (1), `editing_skills.py` (1), `editor.py` (1).
- Largest files: `timeline_api.py` (37,225 B), `auto_edit.py` (33,057 B), `editing_director.py` (32,946 B).
- Secret scan: no findings.

### Section 6

- Important paths: `remotion` (15), `render-service` (15), `assets` (4), `fonts` (3), `audio_mastering.py` (1), `camera_inset.py` (1).
- Largest files: `fonts/NotoSerif-Bold.ttf` (638,164 B), `remotion/public/fonts/NotoSerif-Bold.ttf` (638,164 B), `fonts/Anton-Regular.ttf` (170,812 B).
- Secret scan: no findings.

### Section 7

- Important paths: `native` (178), `dashboard` (1).
- Largest files: `native/OpenShorts.Desktop/Assets/Studio/creator-hero.png` (1,880,962 B), `native/OpenShorts.Desktop/MainViewModel.cs` (27,466 B), `native/OpenShorts.Desktop/ClipperWorkspace.cs` (25,626 B).
- Secret scan: no findings.

### Section 8

- Important paths: `tests` (137), `tools` (14), `native` (12), `examples` (5), `skills` (4), `benchmarks` (2).
- Largest files: `examples/n8n/openshorts-content-machine.json` (33,321 B), `tests/test_adaptive_analysis.py` (18,893 B), `tests/test_professional_pacing.py` (18,043 B).
- Secret scan: 2 reviewed placeholder/test-fixture findings.

### Section 9

- Important paths: `packaging` (11), `build_desktop.ps1` (1), `build_wpf.ps1` (1), `requirements-billing.txt` (1), `requirements-desktop.txt` (1), `requirements-dev.txt` (1).
- Largest files: `packaging/windows/build.py` (9,331 B), `packaging/wpf/build.py` (4,582 B), `packaging/windows/smoke_webview.py` (2,751 B).
- Secret scan: no findings.


## Reviewed boundaries

- Section 1: repository configuration and current architecture/development documentation.
- Section 2: Python/FastAPI IPC, desktop backend, CLI and separately licensed `cloud/` source.
- Section 3: Gemini, adaptive multimodal analysis, transcript, story and candidate selection.
- Section 4: local learning, migrations and ranking.
- Section 5: autonomous editing, skills, Smart Split and timeline project/API.
- Section 6: FFmpeg, audio, captions, framing, Node/Remotion fallback and required visual assets/fonts.
- Section 7: WPF project and resources; one retained legacy dashboard source component.
- Section 8: Python/.NET tests, safe fixtures and development tools.
- Section 9: build scripts, dependency lists and release packaging configuration.

## Security and exclusions

The candidate-byte scan checked common provider tokens, private-key headers,
URL credentials, sensitive filenames and files above 3 MB. Findings are
recorded by path/type/line only in the JSON manifest. Placeholder credentials
in `.env.example` and synthetic URL test fixtures were reviewed as safe.
No detected live credentials or oversized candidate files remain.
Git ignores real `.env`, local media, model weights, databases, libraries,
node_modules, virtual environments, build output, logs, recovery/quarantine,
local user research, and reports containing personal machine paths.
The six reference videos and all customer videos stay local.

A clean checkout requires documented third-party dependencies and model
provisioning. Release distribution remains subject to the existing FFmpeg
source-offer and vendor notice gates; this import does not fill them in.

## Verification before each commit

Stage only paths assigned to that section, inspect staged name/size/diff,
re-run candidate secret checks, reject suspicious files, run lightweight
checks, commit, and record the SHA. The local history then awaits explicit
user approval before its first remote push.

After approved sequential pushes, verify remote SHA after each update,
run baseline tests, create/push `develop`, and annotate/push `v0.1.0-dev`
on the verified final main commit. Future work follows
`feature/* → develop → main` by pull request with test evidence.
`feature/ai-visual-assembly-011` is reserved as a proposed name only.
