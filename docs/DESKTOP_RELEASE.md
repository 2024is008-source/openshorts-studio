# Windows native desktop development and packaging

The maintained application is native WPF with authenticated FastAPI loopback IPC.
Install Python 3.11 x64, the .NET 10 Windows SDK, and FFmpeg/FFprobe on PATH.
Run `setup_windows.bat` for the existing Python engine and WPF development build.
Launch `start_wpf.vbs` or the existing native shortcut. Credentials stay local.

Optional Remotion fallback and renderer tests still require Node/npm and local
Chromium. Run `npm ci --ignore-scripts --no-audit` in `remotion` and
`render-service`, then `npm run build` / `npm test` in `render-service`.
No dashboard install, Vite process or WebView2 shell is required.
Keep renderer dependencies, fonts, models, notices and version lockfiles.
Keep Deno and yt-dlp for supported desktop URL downloads.

For a development build: `dotnet build native/OpenShorts.Desktop/OpenShorts.Desktop.csproj -c Release`.
For tests: `dotnet test native/OpenShorts.Tests/OpenShorts.Tests.csproj -c Release`
and the targeted Python regression commands in the Phase 2 audit report.
Save/reopen, manual effect overrides and preview/export use the existing engine.

For release packaging use `build_wpf.ps1`; add `-Installer` and a valid
`-InnoCompiler` path for Inno Setup 6. PyInstaller freezes the Python engine;
dotnet publishes WPF. Development builds do not certify a distributable installer.
The native release packager currently does not stage the optional Node/Chromium
fallback: retain its working source setup and resolve release parity before
claiming a fully self-contained fallback distribution.

Release remains blocked until the distributor supplies the actual selected
FFmpeg corresponding-source/provenance record at
`packaging/windows/FFMPEG-SOURCE-OFFER.txt` and reviewed vendor/model/.NET/LibVLC
notices at `packaging/wpf/THIRD-PARTY-NOTICES.txt`. Existing preflights remain.
Do not invent notices or treat an upstream URL as a complete source offer.
Preserve all original licensing and recovery evidence. Historical web reports
describe previous builds and are not current setup instructions.

## License review map

| Component | Distribution consideration |
| --- | --- |
| OpenShorts root source | MIT; preserve repository LICENSE |
| `cloud/` | Separate OpenShorts Commercial License; excluded from desktop freeze |
| pywebview | BSD; include package license |
| pythonnet / clr-loader | Preserve their package licenses and runtime notices |
| WebView2 | Microsoft runtime redistribution terms and third-party notices |
| Node / Chromium / npm packages | Include exact distribution notices; inspect generated inventory |
| FFmpeg / libx264 / linked codecs | Current full build is GPL v3; distribute appropriate notices and corresponding source material |
| Ultralytics / YOLO assets | Review AGPL/commercial terms for the intended distribution and subscription product |
| Remotion | Review the installed version's business/commercial license terms before release |
| PyTorch, Whisper, TransNetV2, MediaPipe | Preserve package and separately supplied model notices; verify model redistribution rights |
| fonts and branding | Include font licenses and confirm rights for the distributed assets |

An inventory does not itself settle redistribution rights. Record the selected
versions, licenses and model origins for the actual release. The current package
source offer and vendor checks are release inputs, not fake legal declarations.

## Historical shell security and subscription record

The following preserved sections describe the retired WebView shell and historical
release design, not the current native startup workflow. Current native IPC and
packaging status are documented above and in WPF_BUILD.md.

The local API binds exclusively to 127.0.0.1. A random launch token protects all
routes including static files, and Host/Origin are checked. Native WebView2
attaches the token only to that exact origin; external navigation opens the
system browser. No custom Python API is exposed to page JavaScript. Local
processes running as the same Windows user are outside this boundary: they
already control the user's files and process environment.

The Node renderer also binds loopback and requires a separate launch token. Its
owned Chromium reads source media through a private capability URL; that token
is distinct from the dashboard token. Local frontend traffic uses the protected
FastAPI proxy. The original engine's argument-list subprocesses and media path
validation remain in use; the local project state endpoint additionally rejects
traversal and missing media references. There are no embedded Gemini secrets.

Gemini credentials use Windows current-user DPAPI, with no plaintext fallback.
The browser runs in private mode. Crash logs contain only time, component and
exception class, never exception text/keys/media paths. The engine retains its
existing in-memory processing logs for progress/error display.

`desktop/licensing.py` defines login/logout, license status, entitlements, device
activation/deactivation, trial, offline-grace expiry and authenticated API
interfaces. It does not grant paid rights, validate payments, or invent an
offline license. Wire these to a trusted service and verify signed expiring
responses before enabling subscription features. Existing cloud code is kept
in the source repository but is not activated or relicensed by this task.

## Signing and update distribution

Before publishing, sign application executables and the final installer with a
publisher-controlled Authenticode certificate using SHA-256 and an RFC 3161
timestamp. Keep private signing keys outside the repository/build artifacts.
Verify signatures after staging and after installation. Signing must happen
before generating final artifact checksums; regenerate the checksum if the
installer is signed after the script completes. Include hashes for disk slices.

There is no automatic updater in this task. Distribute upgrades via HTTPS with
verified publisher signatures and versioned hashes. A future updater should
verify a signed manifest, enforce version/rollback policy and close owned
processes before replacing binaries. Do not execute an unsigned download as an
update. Keep AppData/library storage outside the installation directory.
