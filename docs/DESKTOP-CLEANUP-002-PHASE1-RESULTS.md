# Desktop-only cleanup — approved Phase 1 results

Date: 2026-10-19. Scope: the user's explicit approval of **9,493 exact manifest entries** and the **five-file proposed patch**. **Phase 2 was not started. No files were permanently deleted.** No paid Gemini calls, package upgrades, large downloads, customer-data migration or Git initialization occurred.

## Result

All 9,493 approved entries were moved into the existing quarantine after archive/member/source hash validation. No changed entries were skipped. The five approved source changes were applied after exact hash and unified-patch context checks. Protected exceptions remained intact.

A retained render-service test exposed an additional frontend fixture dependency. Following the approved rollback instruction, **79 original files / 4,946,439 bytes** were copied back from quarantine and hash checked. The quarantine copies remain intact. Therefore **9,414 original files / 103,869,949 bytes (103.87 MB)** remain retired from the active tree. The standalone frontend and Vite runtime remain absent.

Final integrity check: **9,493 quarantine hashes verified, 232 original protected exceptions verified, all restored fixtures verified, all five applied source hashes verified, recovery ZIP unchanged, zero integrity errors.**

## Exact files and recovery records

| Record | Location |
|---|---|
| Approved immutable cleanup scope | `build/desktop-cleanup-audit-20261019-185359/cleanup-manifest.json` |
| Verified original backup | `.desktop-cleanup-recovery/20261019-185359/pre-cleanup.zip` |
| Original recovery manifest | `.desktop-cleanup-recovery/20261019-185359/manifest.json` |
| Quarantine, preserved relative paths | `.desktop-cleanup-recovery/20261019-185359/quarantine/` |
| Exact successful moves and applied source hashes | `build/desktop-cleanup-phase1-20261019-190913/execution.json` |
| Append-only move journal | `build/desktop-cleanup-phase1-20261019-190913/quarantine-journal.jsonl` |
| Exact copied-back exception list | `build/desktop-cleanup-phase1-20261019-190913/restored-test-dependencies.json` |
| Final integrity result | `build/desktop-cleanup-phase1-20261019-190913/final-integrity.json` |

The recovered frontend files are `dashboard/package.json`, `dashboard/src/components/ClipScoreReport.jsx`, and the approved manifest members of five complete declared React test dependencies: `react`, `react-dom`, `scheduler`, `loose-envify`, `js-tokens`. Their existing attribution files were already protected. These are fixtures for the retained `render-service/src/story-evidence.test.ts`; no frontend server/build was reintroduced. The approved manifest was not silently rewritten to hide this restoration.

No unrelated Node/Codex processes were stopped. No project-owned frontend process needed termination. Acceptance checks started and stopped only their own isolated workers; user projects were not used.

## Applied source changes

Exactly the five approved application/build files:

1. `desktop/backend.py`: browser-mode serving now stops with a native-launch instruction; the React HTML mount was removed. Native authenticated loopback IPC and worker handling remain.
2. `desktop_entry.py`: no-argument execution directs the user to WPF. Managed `--native-backend` and `--worker` dispatch remain functional.
3. `start_desktop.vbs`: redirects the compatibility entry to `start_wpf.vbs`.
4. `packaging/windows/build.py`: the shared inventory helper accepts `include_web`, retaining its existing legacy behavior by default.
5. `packaging/wpf/build.py`: native packaging calls `inventory(include_web=False)`.

No Gemini, transcription, ML, effect-selection, rendering, timeline or project-format implementation was modified. No Python/NuGet/Remotion dependencies were uninstalled. All local HTTP routes required by WPF remain.

Three test files were separately backed up before the user-authorized expectation corrections: `tests/test_native_auto_configuration.py`, `tests/test_gemini_transfer_recovery.py`, and `tests/test_adaptive_analysis.py`. Their verified original ZIP/manifest are under the same recovery directory with the `baseline-test-expectations-` prefix. New execution/reporting helpers and diagnostic artifacts were added; they do not change the product's AI logic.

## Investigation of the six existing Python failures

No tests were removed, skipped or weakened by discarding the behavior under test.

| Existing failure | Independent behavior confirmation | Correction |
|---|---|---|
| Saved UI key expected instead of explicit `.env` primary | Existing credential-selection implementation and the dedicated key-precedence suite confirm explicit `.env` keys take precedence; this also matches the user's configuration decision. | Expect the first explicit key and assert `GEMINI_KEY_SOURCE == 'env'`; retain secret-environment isolation checks. |
| Chapter dictionary omitted `completed` | Current progress adapter emits the count, and the native view uses it to display completed chapters rather than guessing. Existing percentage remained 40%. | Include `completed: 2` in the exact dictionary expectation. |
| Four Files API tests used a 3 MiB proxy | Current production source deliberately permits inline payloads up to 4 MiB. The tests were not reaching their stated uploaded-reference path. | Change those fixtures to 6 MiB, retaining upload-count, retry/reuse, expiry and key-safety assertions. No transport threshold was changed. |

Focused recheck: **65 passed**. Full unchanged baseline selection, after the expectation corrections: **448 passed, zero failed/skipped/errors**. Twelve existing PySceneDetect deprecation warnings remain.

## Baseline versus final validation

| Check | Before cleanup | After cleanup |
|---|---|---|
| WPF Release build | Passed, 0 warnings/errors | Passed, 0 warnings/errors |
| Native tests | 60 passed | **60 passed**, 0 failed/skipped |
| Python baseline selection | 442 passed, 6 outdated-expectation failures | **448 passed**, 0 failed/skipped/errors |
| Native Video Editor / ML | Passed | Passed |
| Native AI Clipper | Passed | Fresh final run passed; an earlier failed run is preserved below |
| Authenticated native startup | Passed in native acceptance | Explicit startup probe passed without React/Vite runtime |
| CPU export | `libx264`, valid 3.000 s output | `libx264`, 3.000 s, shared quality gate **PASS** |
| NVIDIA export | `h264_nvenc`, no fallback | `h264_nvenc`, 3.000 s, no fallback, shared quality gate **PASS** |
| Retained renderer suite | Not included in the original Python/.NET baseline | **20 passed**, including real Remotion export, after restoring the discovered fixture dependencies |

Python final run: 73.36 seconds wall output (XML suite time 73.299 seconds), versus approximately 95.54 seconds for the baseline. Test-machine load/concurrency differed; **this is not an application-performance improvement claim**.

Build output: `build/desktop-cleanup-phase1-native/OpenShorts.Desktop.exe`. The build uses the current Python source engine setup. WPF unit evidence: `build/desktop-cleanup-phase1-20261019-190913/native-tests/desktop-cleanup-phase1.trx`. Python evidence: `python-regressions.xml` and `baseline-failure-rechecks.xml` in that same report directory.

### Native acceptance evidence

`build/desktop-cleanup-phase1-editor/` contains:

- `visual-result.json`: playback, fullscreen reparenting, foreground guides, responsive panels and image-asset preview passed.
- `auto-edit-result.json`: effect undo/redo, regeneration retaining a manual override, save/reopen and rendered preview passed.
- `learning-result.json`: native panel, explicit feedback, duplicate guard, privacy settings and insufficient-data training guard passed. All data was in the synthetic acceptance library; no production model was activated.

`build/desktop-cleanup-phase1-clipper-recheck/clipper-result.json` confirms import-to-ready behavior, mocked provider job states, background navigation, cancellation, partial results, native playback, timeline editing, real 1080 × 1920 batch export, per-item retry, preferences, inline styles, updated preview, aspect ratio and independent duplication.

All acceptance libraries used locally generated media and separate profiles. Paid provider requests: **zero**. The clipper harness deliberately simulates and recovers from a worker disconnect; its expected transition-error diagnostic is retained.

### Explicit startup without the standalone frontend

`build/desktop-cleanup-phase1-20261019-190913/startup-check/result.json` records an isolated, owned native backend:

- Unauthenticated contract access: **403**.
- Authenticated native contract: **200**, exposing 117 active route records.
- Authenticated project-library access: **200**.
- Root HTML request: **404**; no React page is mounted.
- `dashboard/dist/index.html`: absent.
- `dashboard/node_modules/vite/bin/vite.js` and Vite package manifest: absent.

The retained license directories mean a directory named `vite` can still exist; this is not a working Vite runtime. No React/Vite server was required to start the app or complete native acceptance. Node was used only to test the explicitly retained optional renderer, not as a WPF startup process.

### CPU/NVENC details

Fresh generated three-second 640 × 360, 30 fps source. Existing render runtime and shared export-quality checks were used. Output evidence is under `build/desktop-cleanup-phase1-20261019-190913/exports/`.

Render receipts report CPU execution at 0.266 seconds and NVENC execution at 0.297 seconds for both baseline and final samples. The final measured command-plus-quality-check wall times were 1.031 and 1.047 seconds; the baseline's 0.406 and 0.407 second outer timings did not include that additional quality validation, so they are not directly comparable. Neither final run fell back to CPU. Both outputs passed. These are small functionality fixtures, not production video benchmarks.

## Errors discovered and recovery performed

1. **Cleanup-induced render-service test failure:** `Cannot find module 'react'` from its dashboard-scoped test import. The audit had missed this test dependency. Restored 79 exact original files, preserved all quarantine copies, then ran all 20 retained renderer tests successfully. No renderer source was edited to hide the dependency.
2. **One initial native import worker exit 1:** the first post-cleanup clipper smoke attempt stopped during local validation. Its diagnostic remains in `build/desktop-cleanup-phase1-clipper/`. A captured reproduction using the real managed worker completed successfully, and a fresh full native clipping run passed. The initial root cause is **unconfirmed**; no import/runtime code was changed or claimed fixed. This remains a diagnostic follow-up if it recurs. Captured reproduction: `build/desktop-cleanup-phase1-20261019-190913/import-diagnostic/result.json`.
3. Existing test expectation discrepancies were reconciled as described above. No final regression suite is failing. Existing deprecation warnings and Remotion's `objectFit` guidance remain informational.

## Files retained

- All 232 original protected fixture/notice exceptions, unchanged, plus the 79 restored test dependencies.
- Complete `native/`, shared Python engine, `adaptive_analysis/`, `learning/`, Gemini modules/configuration/credential stores, FFmpeg/FFprobe, CPU/NVENC paths, fonts/templates/assets, native DLLs, tests, user settings and profiles.
- Customer library, source/exported media, databases, approved models, recovery checkpoints, caches and download history.
- Entire `remotion/`, `render-service/`, `cloud/`, `.remotion/`, `.venv/`, `.nuget/`, legacy shell source, archived ZIPs and historical builds. No Phase 2 scope was inferred from the approval.

## Project size and recovered active-tree payload

All measurements below are logical file sizes, exclude `.desktop-cleanup-recovery/`, and do not describe NTFS allocated disk usage.

| Snapshot | Bytes | Decimal GB |
|---|---:|---:|
| Earlier first-run audit | 23,629,303,191 | 23.629 |
| Fresh execution snapshot, immediately before moves | 23,870,810,544 | 23.871 |
| Immediately after quarantine, before fixture restoration/new validation builds | 23,765,510,386 | 23.766 |
| After validation, including new build/results/media artifacts | 23,993,761,618 | 23.994 |

The raw tree grew after validation because approximately **226.66 MB of new Phase 1 build and diagnostic outputs** were created and deliberately retained. Excluding those new verification directories gives an approximate comparable final tree of **23,767,097,607 bytes**; snapshots/cache/report writes are not atomic, so this comparison is approximate. The precise retirement calculation uses original manifest hashes:

```
108,816,388 approved bytes moved
  4,946,439 required test-fixture bytes restored
-----------
103,869,949 bytes removed from the active original payload
```

Similarly, 9,493 approved entries moved minus 79 copied back = **9,414 retired active-tree files**. The quarantine still contains all **9,493 original entries**. Whole-drive space recovered by the move is **0 bytes**, because quarantine is on the same drive. Backups/quarantine and diagnostic builds were not purged. Do not equate active-tree shrinkage with free drive space.

Measured snapshots and reconciliation are in `execution.json`, `project-size-after-validation.json` and `size-reconciliation.json`. No before/after installer-size claim is made; an installer was not built, and the existing source-offer/third-party notice release requirements remain in force.

## Remaining web dependencies and next proposed phase

Phase 1 retires the standalone frontend startup and payload; it is **not a claim that all legacy web source has been removed**. Remaining items:

- FastAPI/Uvicorn/httpx/multipart and media HTTP endpoints are required native IPC/provider dependencies and should remain.
- The old WebView shell and its packages still support an existing locking regression; its source is inactive under the approved entry paths.
- Remotion/Node rendering fallback, renderer tests and their React fixtures remain intentionally supported. Twenty tests including real output now pass.
- Shared `cloud/`, S3/provider helpers and mixed application routes remain unchanged.
- `setup_windows.bat`, the old `build_desktop.ps1`/browser packager and older documentation still describe retired frontend setup. They were outside the five-file approval and have **not** been edited. The maintained native build/start paths were verified; the old web setup/build commands need retirement in a separately approved migration.

**Proposed Phase 2, not executed:** move cross-product renderer test fixtures to an explicit maintained fixture location; migrate the old shell lock regression; inventory and retire legacy web setup/build/documentation paths; classify genuinely unused routes and dependencies with another exact manifest. Audit historical builds separately, preserving recovery artifacts/customer data. Any renderer/cloud removal, dependency uninstall, further move or permanent purge requires separate approval.

## Recovery

The original ZIP, original manifest and complete quarantine remain at the recorded locations. The approved patch's original files are in the verified ZIP; applied-file hashes are in `execution.json`. Test expectation snapshots were separately preserved. To restore an individual retired dependency, verify its quarantine hash against the original manifest and copy it to its original relative path without overwriting a later edit; this is how the 79 test files were recovered.

The existing `tools/desktop_cleanup_restore.py` verifies the original backup by default. A blanket `--restore` intentionally refuses changed existing files, including the five approved edits: review those conflicts and back up the current versions before any full rollback. Never purge the archive or quarantine as part of restoration.

**Phase 1 is complete with all final required checks passing, the one intermittent import diagnostic disclosed, and Phase 2 awaiting separate approval.**
