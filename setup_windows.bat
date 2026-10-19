@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
if errorlevel 1 exit /b 1
dotnet restore native\OpenShorts.sln --locked-mode
if errorlevel 1 exit /b 1
dotnet build native\OpenShorts.Desktop\OpenShorts.Desktop.csproj -c Release --no-restore
if errorlevel 1 exit /b 1
echo Native development setup complete. Launch start_wpf.vbs.
echo Optional Remotion fallback: install locked remotion and render-service dependencies as documented.
