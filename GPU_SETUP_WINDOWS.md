# OpenShorts — Windows NVIDIA GPU Setup (No Docker)

This package is the **Gemini BYOK + no-Docker build**. It now auto-detects NVIDIA CUDA for faster-whisper and records the GPU/VRAM in the job log.

## Recommended for RTX 2050-class laptops

```env
WHISPER_MODEL=small
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16
TRANSCRIBE_BACKEND=whisper
ASR_GPU_CONCURRENCY=1
FFMPEG_ENCODER=auto
```

If your card has substantially more VRAM, test `WHISPER_MODEL=large-v3-turbo` later.

## Install GPU dependencies

1. Make sure `nvidia-smi` works.
2. Create/activate the project's `.venv`.
3. Install the normal requirements.
4. Install the CUDA-enabled PyTorch 2.11 wheel:

```bat
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements-local.txt
pip install --force-reinstall torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
pip install -U faster-whisper==1.2.1 ctranslate2
```

Current CTranslate2/faster-whisper GPU builds require compatible CUDA 12 NVIDIA runtime libraries, including cuBLAS and cuDNN. On Windows, make sure the required CUDA/cuDNN DLLs are installed and visible on `PATH`.

Then run:

```bat
python check_gpu.py
```

## Diagnostics

A successful setup should show:

```text
PyTorch CUDA available: True
GPU: NVIDIA GeForce RTX ...
CTranslate2 CUDA compute types: ...
NVENC available: True
```

During a real job:

```text
🖥️ [GPU] CUDA available=True device=NVIDIA GeForce RTX ...
🖥️ [GPU] VRAM=4.0 GB compute=8.6
🧠 [ASR] selected model=small device=cuda compute=float16
🎙️  Transcribing video...
```

If CUDA/Whisper fails, the worker now prints the **actual exception and full traceback**, then attempts CPU fallback for GPU-related failures.

## Start without Docker

```bat
start_backend_windows.bat
```

and in another terminal:

```bat
start_frontend_windows.bat
```

Open `http://localhost:5175`.
