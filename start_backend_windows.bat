@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set PYTHONUTF8=1
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
