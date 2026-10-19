@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install -U pip
python -m pip install --force-reinstall torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -U faster-whisper==1.2.1 ctranslate2
python check_gpu.py
pause
