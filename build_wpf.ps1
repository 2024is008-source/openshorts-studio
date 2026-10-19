param([string]$Python="$PSScriptRoot\.venv\Scripts\python.exe",[switch]$Installer,[string]$InnoCompiler="${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe")
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$nativeArgs=@('packaging/wpf/build.py','--python',$Python)
if($Installer){$nativeArgs+=@('--installer','--iscc',$InnoCompiler)}
& $Python @nativeArgs
if($LASTEXITCODE -ne 0){throw "WPF release build failed ($LASTEXITCODE)"}
