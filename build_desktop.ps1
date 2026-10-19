param([string]$Python="$PSScriptRoot\.venv\Scripts\python.exe",[string]$InnoCompiler="${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",[switch]$PrepareOnly)
$ErrorActionPreference="Stop"
if ($PrepareOnly) { throw "Legacy PrepareOnly is retired. Use dotnet build for development; build_wpf.ps1 for release packaging." }
& "$PSScriptRoot\build_wpf.ps1" -Python $Python -Installer -InnoCompiler $InnoCompiler
