# OpenShorts Local Edition

See `LOCAL_WINDOWS_SETUP.md` for the no-Docker + Gemini API setup.

For `AUDIO_MASTERING_FAILED` after normalization or chapter-analysis
`400 INVALID_ARGUMENT`, see [the reproduced job failure and recovery](docs/JOB-AUDIO-AND-GEMINI-RECOVERY.md).

See [the development baseline](docs/BASELINE.md) for the repository inspection,
current verification results, and remaining local test/setup limitations.

Opening headlines: see [animated hook editing](docs/TASK-002-ANIMATED-HOOKS.md)
for source-backed suggestions, independent headline timing, the five animation
presets, rendered previews, and placement limitations. The existing **Automatic
hooks** option disables generation; captions remain independent.

Portrait composition: see [professional reframing](docs/TASK-003-REFRAMING.md)
for shot-local timestamped paths, body/object preservation, layout selection,
configuration switches, tests and remaining detector limits.

Captions: see [animated captions and word synchronization](docs/TASK-004-ANIMATED-CAPTIONS.md)
for the five current presets, measured word highlighting, editable saved text,
phrase controls, exact FFmpeg previews, and alignment limitations.

Additional local looks: see [Green Pop, Teal Reveal and Paper Focus](docs/LOCAL-CAPTION-LOOKS.md)
for the Cutback ZIP compatibility findings, offline caption presets, rendered
samples, validation and changed-file report.

Wide blurred layouts now keep captions below the clear image and use a more
diffuse backdrop. See [blur caption composition](docs/BLUR-CAPTION-COMPOSITION.md)
for geometry, configuration, sample renders, tests and legacy-media limits.

Story selection: see [emotion, story and highlight detection](docs/TASK-005-STORY-DETECTION.md)
for five story modes, timestamped source evidence, grounded explanations, cached
multimodal analysis and offline fallback behavior.

Clip timing: see [intelligent boundaries and pacing](docs/TASK-006-PACING.md)
for four pacing modes, protected setup/payoff/reaction timing, optional measured
pause shortening, and continuous audio joins in previews and exports.

Quick start on Windows:

1. Edit `.env` and set `GEMINI_API_KEY`.
2. Run `setup_windows.bat` once.
3. Run `start_windows.bat`.
4. Open `http://127.0.0.1:5175`.


### Measured audio mastering (TASK-007)

The existing generation options now offer Natural, Dialogue and Original audio
presets, target LUFS, true-peak ceiling, optional edge fades and light local noise
reduction. Natural defaults to -16 LUFS / -2 dBTP. Pauses, reactions and existing
sound effects are not removed. No music is automatically added.

Final Python, timeline, browser and Remotion-service deliveries use the shared
FFmpeg mastering/quality gate. It measures the assembled mix, encodes AAC with
headroom, checks decoded true peak and stream timing, and keeps the previous file
if checks fail. Reports/cache live beside exports as `.audio.json`,
`.audio-analysis.json` and `.quality.json`. Quality rechecks do not modify audio.
Saved job settings survive reopening. `AUDIO_MASTERING=0` restores the legacy
fixed filter; `AUDIO_NORMALIZE=0` disables both normalization paths.

Optional separate local music stems can be ducked through
`audio_mastering.master(path, music=stem)`; there is no music upload/mixing UI or
separation of music already mixed into dialogue. See
[the implementation and verification report](docs/TASK-007-AUDIO-MASTERING.md)
for controls, limitations and listening checks.


### OpenShorts professional templates (TASK-008)

Generation options include five optional styles: Creator Energy, Minimal Studio,
Story Focus, Podcast and Challenge. Choose None to retain the current styles.
The existing saved timeline editor can preview and customize colors, fonts,
caption styles and source-backed headlines; save/duplicate custom styles; and
apply a style to selected drafts or export those clips sequentially. Batch
exports use the existing jobs, cancellation and technical quality gate.

Style JSON is separate from clip content. Starter configurations live in
`assets/video_templates.json`; custom styles are stored per authorized job in
`custom_video_templates.json`. Drafts/final clip metadata retain the exact
validated style snapshot, so later library edits cannot silently change exports.
Graphics use existing offline FFmpeg/libass caption and headline rendering.
Optional brand text, source-evidenced speaker/progress labels and restrained
identity accents avoid detected faces. No prizes, people or claims are baked in.

`VIDEO_TEMPLATE=none` is the default. Set `VIDEO_TEMPLATES_ENABLED=0` to reject
new template rendering; existing files and ordinary editing remain available.
See [TASK-008 implementation/verification](docs/TASK-008-VIDEO-TEMPLATES.md)
for API shapes, supported layout behavior, screenshots, limitations and tests.


### Rendering performance and hardware (TASK-010)

The existing FFmpeg, libass, OpenCV and optional Remotion paths are retained.
`GET /api/render/capabilities` reports initialized CPU/NVENC support, filters,
installed backends and process resource limits. NVIDIA presence alone is not
reported as working encoding: a 1080x1920 HQ/AQ encode must initialize first.

Use `FFMPEG_ENCODER=x264` (default), `auto`, or `nvenc`. File-based FFmpeg
renders retry once on CPU after a diagnosed NVENC error, preserving the selected
quality tier and recording requested/effective encoders. GPU failures enter a
60-second reprobe cooldown. The legacy OpenCV raw-frame fallback uses CPU
because consumed stdin cannot safely be replayed after an encoder failure.

`FFMPEG_X264_PRESET` and `FFMPEG_NVENC_PRESET` optionally override speed; they do
not replace CRF/CQ quality policy. Default encode threads are bounded to four,
encoder slots to two, and clip workers to two per Python process. See
`.env.example` for bounds. Existing higher-level job limits still apply.
Whole compatible clean clips can bypass video re-encoding; caption-only output
copies audio. Cache keys include encoder/quality/thread settings. MP4 output is
staged and checked before replacement; final export retains the existing
technical/audio quality gate. Known ASS overlays receive bounded raster checks;
requested timed captions that fail to render block completion by default.

Generation and saved-editor progress now use FFmpeg frame/output clocks.
Completion remains reserved for validated exports. Saved timeline cancellation
kills/reaps the active FFmpeg process, removes owned partial files and keeps
completed cache parts. The optional Remotion service has bounded FIFO jobs,
separate browser frame concurrency, staging and cancellation:
`POST /api/render/{render_id}/cancel` authorizes against its actual source job.
The installed Remotion 4.0.447 H.264 backend is CPU-only on Windows; NVENC is
used by supported FFmpeg paths, not claimed for browser/WebCodecs or Remotion.

Reproduce the local 1080x1920 CPU/NVENC benchmarks with:

```powershell
.venv\Scripts\python.exe -X utf8 benchmarks/render_exports.py
```

The three cases are a 30-second simple clip, 60-second animated captions and a
30-second blur/split/editorial composition. Results, actual exports and resource
measurements are under `output/task010-benchmark/`. Preparation is excluded;
render and end-to-end validation timings are reported separately. See
[the full TASK-010 change/benchmark report](docs/TASK-010-RENDERING-PERFORMANCE.md)
for measured numbers, verification, limitations and Windows manual checks.

### Complete verification (TASK-011)

The final implementation matrix, confirmed Windows fixes, visual/audio review,
regression artifacts and release conditions are documented in
[the TASK-011 system verification report](docs/TASK-011-SYSTEM-VERIFICATION.md).

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests -q --junitxml=logs/task011-final.xml
.venv\Scripts\python.exe -X utf8 benchmarks/verify_system.py
.venv\Scripts\python.exe -X utf8 benchmarks/render_exports.py --output output/task011-benchmark
```

The read-only media audit creates timestamped review sheets/JSON under
`output/task011-review/`; when the retained example project exists it also renders
preview/final copies in that review directory using cached source timing. It does
not request Gemini analysis or retranscription. Missing reference files are
reported as unavailable. New CPU/NVENC timings and resource measurements go to
`output/task011-benchmark/`. Keep reports local if their media paths/transcript
content are private.

Windows restored playback supports native path separators, in-flight recovery
keeps reporting manifest progress, and MCP stdio supports synchronous Windows
pipes and Unicode tool descriptions. Caption placement uses packaged MediaPipe
when the optional OpenCV Haar XML files are absent; if neither backend works,
existing safe-zone positioning remains available. The face-policy cache version
refreshes overlays without rerendering unchanged clean video.

The automated review does not certify live Gemini narrative quality, fresh ASR
accuracy or an interactive browser session. See the report for remaining global
lint errors and the installed Torch/setuptools constraint mismatch before release.

If generation reports `end.exclusiveMinimum: Extra inputs are not permitted`,
see [Gemini schema compatibility](docs/GEMINI-SCHEMA-COMPATIBILITY.md). The provider
schema now uses supported bounds while local validation retains strictly positive
end times. Let an active fallback job finish before restarting and rerunning it.

For the restored large white/yellow Anton caption style, choose Classic during
generation or Bold Creator / Creator Bold in the caption editor. Challenge uses
the restored bold defaults. Existing saved template snapshots need the starter
reselected before exporting. See [caption appearance restoration](docs/CAPTION-ANTON-RESTORE.md)
for the verified sample, sizing controls and changed files.

### Automatic editing with fewer controls

Generation now opens with Automatic professional edit. Upload/paste the original
source, acknowledge rights and generate; existing captions can be declared with
one checkbox. Optional manual settings remain under Customize settings. The
profile coordinates existing video/speech analysis, subject-first scene framing,
short-shot split views, bold captions, grounded headlines and audio/quality gates.
Wide or uncertain shots may still preserve context with blur. See
[automatic editing diagnosis and verified clip](docs/AUTOMATIC-EDITING-FOCUS.md).
Existing all-blur exports need source-based reframing; a caption edit alone cannot
recover their original framing. Restart after active jobs finish and refresh the
dashboard to load the updated interface and generation code.
