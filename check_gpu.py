"""Windows/NVIDIA diagnostic for OpenShorts local GPU setup."""
import shutil
import subprocess
import sys

print("=== OpenShorts GPU Diagnostic ===")
print("Python:", sys.version.replace("\n", " "))

try:
    import torch
    print("PyTorch:", torch.__version__)
    print("PyTorch CUDA build:", torch.version.cuda)
    ok = torch.cuda.is_available()
    print("PyTorch CUDA available:", ok)
    if ok:
        print("GPU:", torch.cuda.get_device_name(0))
        props = torch.cuda.get_device_properties(0)
        print(f"VRAM: {props.total_memory / (1024**3):.2f} GB")
        print(f"Compute capability: {props.major}.{props.minor}")
except Exception as e:
    print(f"PyTorch check FAILED: {type(e).__name__}: {e}")

try:
    import ctranslate2
    print("CTranslate2:", ctranslate2.__version__)
    print("CTranslate2 CUDA compute types:", ctranslate2.get_supported_compute_types("cuda"))
except Exception as e:
    print(f"CTranslate2 check FAILED: {type(e).__name__}: {e}")

ffmpeg = shutil.which("ffmpeg")
print("FFmpeg:", ffmpeg or "NOT FOUND")
if ffmpeg:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
        print("NVENC available:", "h264_nvenc" in out.stdout)
    except Exception as e:
        print(f"FFmpeg NVENC check FAILED: {type(e).__name__}: {e}")

nvidia = shutil.which("nvidia-smi")
print("nvidia-smi:", nvidia or "NOT FOUND")
if nvidia:
    try:
        out = subprocess.run([nvidia, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
        print("nvidia-smi result:", out.stdout.strip() or out.stderr.strip())
    except Exception as e:
        print(f"nvidia-smi FAILED: {type(e).__name__}: {e}")
