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
