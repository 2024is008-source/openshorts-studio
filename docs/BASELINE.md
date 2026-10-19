# OpenShorts local development baseline

Inspection date: 2026-10-15 (Asia/Colombo). This records the existing application;
it does not certify end-to-end video quality or introduce processing changes.

## Repository and current implementation

- Git is on `main` with no commits. Existing project files are untracked, so
  there is no committed baseline for comparison. No files were staged or committed.
- No `AGENTS.md` was found in the project inventory. `CLAUDE.md`, `README.md`,
  `LOCAL_WINDOWS_SETUP.md`, and `IMPROVEMENT_NOTES.md` describe the implementation,
  but some documentation describes the upstream Docker/cloud deployment.
- `app.py` is the FastAPI API and job coordinator: uploads, processing queue,
  subprocess execution, status, persisted recovery manifests, media delivery,
  editing, reframing, subtitles, hooks, downloads, and optional integrations.
- `main.py` handles ingest, transcription, AI selection, clip extraction, framing,
  captions, hooks, and metadata. It initializes YOLO and MediaPipe at import time.
- `gemini_worker.py` and `llm_backend.py` provide Gemini analysis and an optional
  OpenAI-compatible text backend. `story_director.py` adds chapter analysis,
  hybrid clip selection, summary planning, and analysis checkpoints.
- `scene_detection.py` defaults to TransNetV2 with a PySceneDetect fallback.
  `reframe_v2.py` renders through FFmpeg; `main.py` falls back to the legacy frame
  loop for automatic framing. Manual crop/forced-layout failures are surfaced.
- Layout modules cover active speakers, split views, screencasts, panels, camera
  insets, and punch-ins. These are existing implementations, not newly verified
  features. `ffmpeg_utils.py` centralizes encoder selection and quality settings.
- `dashboard/` is a React/Vite UI with upload controls, results, clip editing,
  manual reframing, caption/hook previews, browser Remotion rendering, and download.
- `remotion/` contains the standalone compositions; `render-service/` is a
  separate Express/Remotion server. The dashboard also contains composition copies.
- `cloud/`, `cli/`, MCP modules, and social/translation/storage integrations exist.
  `not update/` holds alternate Python implementations and is not the primary path.

## No-Docker configuration and dependencies

The Windows scripts create/use `.venv` and launch FastAPI at `127.0.0.1:8000`
plus Vite at `127.0.0.1:5175`. Vite proxies API/media requests to the backend
and `/render` to port 3100. The local launchers do not start the render service.
Browser rendering is implemented separately; compatibility was not tested here.

The local `.env` selects billing off, one concurrent job, automatic FFmpeg encoder
selection, and Whisper `small` on CUDA with `int8_float16`. Credential values
were not printed or copied. No external AI requests were made. Runtime process
environment and keys supplied through the dashboard may differ from `.env`.
Two numbered Gemini key slots are populated in `.env`; their validity was not tested.

Observed tools: virtualenv Python 3.11.9, Node 24.18.0, npm 11.16.0, and FFmpeg /
ffprobe 9.0. The default `python` on PATH points to Python 3.14; use the virtualenv
explicitly for project checks.

Core installed package versions satisfy `requirements.txt` (checked through
package metadata). Torch 2.11.0+cu128 and torchvision 0.26.0+cu128 are installed.
Package presence does not prove successful model loading or GPU inference.
Torch reports CUDA available on an NVIDIA GeForce RTX 2050; no model inference
or GPU encode was performed.
`requirements-local.txt` includes the core requirements; optional cloud packages
are listed separately in `requirements-billing.txt`.

The dashboard has `node_modules` and a lockfile. The standalone Remotion project
has neither installed dependencies nor a lockfile. The render service has a
lockfile but no installed dependencies. No dependencies were installed or upgraded.

## Checks executed

| Check | Result |
| --- | --- |
| Parse Python sources with `ast.parse` | Passed: 145 files, zero syntax errors; excludes virtualenv, node_modules, Git, and caches |
| `.venv\\Scripts\\python.exe -m pip check` | Passed: no broken installed requirements |
| Compare installed core versions against `requirements.txt` | Passed: no missing packages or pin mismatches |
| `.venv\\Scripts\\python.exe -m pytest --version` | Blocked: `No module named pytest`; no pytest tests executed |
| `npm.cmd run lint` in dashboard | Failed: 11 errors, zero warnings |
| `npm.cmd run build` in dashboard | Passed after retry outside sandbox; initial attempt failed with filesystem `EPERM` |
| `ffmpeg -version`, `ffprobe -version` | Passed: both executables available |
| Temporary synthetic FFmpeg encode and ffprobe inspection | Passed: 1080x1920 H.264, yuv420p, AAC at 48 kHz; temporary output removed automatically |
| Torch CUDA availability | Passed: RTX 2050 detected; inference not tested |
| Standalone Remotion build and render-service build/test | Not run: dependencies absent |

Lint failures: five in `dashboard/public/op1.js`, one in `dashboard/seo/render.js`,
one each in `dashboard/src/Legal.jsx` and `dashboard/src/components/PricingPage.jsx`,
and three in `dashboard/src/lib/consent.js`. They involve unused variables/arguments,
empty blocks, and unreachable code. No fixes were applied.

Build warnings concern unset optional OpenPanel placeholders, outdated Browserslist
data, and bundles larger than 500 kB. A successful bundle does not verify browser
WebCodecs support or video export.

There are 70 `tests/test_*.py` modules. Coverage includes framing geometry,
speaker tracking, layouts, clip selection, summary planning, Gemini retries,
checkpoints, job recovery, editing endpoints, media access, and optional cloud
features. `tests/conftest.py` forces self-host mode, but some test modules still
import cloud dependencies directly. SQLAlchemy is absent, so full collection may
require optional test dependencies even after pytest is installed. Ruff is absent;
no root Python lint/test configuration or CI directory was found in this checkout.

## Findings to address in a separately requested task

1. Make local regression checks reproducible: declare suitable test dependencies,
   establish test collection, then resolve the current lint errors. Existing notes
   report historical passes; they are not evidence for this machine's current suite.
2. Clarify local renderer setup and supported browser export behavior. Keep the
   FFmpeg core workflow and optional render service distinct in setup instructions.
3. Review job limits: `app.run_job` polls until the child exits and has no overall
   processing deadline in that loop. Individual FFmpeg/network operations do have
   timeouts; those do not establish a whole-job deadline.
4. Validate real footage before changing framing or highlight selection. Existing
   `IMPROVEMENT_NOTES.md` records continuity concerns in a prior highlight, but that
   sample was not reviewed again during this inspection.
5. Review duplicated compositions and `not update/` carefully before edits, and
   reconcile upstream Docker/cloud documentation with local Windows instructions.

These are source findings and verification gaps, not all confirmed runtime defects.
No development task was started automatically.

## Manual verification for a later development task

1. Use the existing local setup instructions, configure a Gemini key privately,
   and launch `start_windows.bat`. This may download models and use Gemini quota.
2. Check `/health` and `/api/config`, then upload an owned video longer than the
   default 45-second source minimum with clear speech and at least one scene cut.
3. Generate standard clips and inspect face framing, scene transitions, word and
   sentence boundaries, caption placement, audio sync, and downloaded MP4 playback.
4. Exercise manual reframe, trim/rerender, captions, and hooks; confirm that the
   downloaded clip includes the requested edits. Compare standard and studio output.
5. Test highlights separately for setup/development/payoff continuity, and test
   silent footage, corrupt input, interrupted jobs, and unavailable dependencies.
6. Once test dependencies are available, run `.venv\\Scripts\\python.exe -m pytest -q`
   from the root, plus dashboard lint/build and render-service tests/build when set up.

## Changes in this inspection

Only this report and the link in `LOCAL_README.md` were added to documentation.
Dashboard build artifacts were regenerated under ignored `dashboard/dist/`.
Application code, test files, requirements, and credentials were not changed.
The README report link and report contents were checked after writing.

Suggested documentation commit message: `docs: record local OpenShorts development baseline`.
Because the repository has no initial commit, review staging explicitly before
creating any commit; this inspection did not create one.
