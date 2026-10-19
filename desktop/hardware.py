"""Report tested encoder capability separately from AI CUDA availability."""
def capabilities():
    import render_runtime
    result = render_runtime.capabilities()
    result['ai_cuda'] = {'torch': False, 'devices': [], 'ctranslate2_device_count': 0}
    try:
        import torch
        if torch.cuda.is_available():
            result['ai_cuda']['torch'] = True
            result['ai_cuda']['devices'] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except Exception:
        pass
    try:
        import ctranslate2
        result['ai_cuda']['ctranslate2_device_count'] = ctranslate2.get_cuda_device_count()
    except Exception:
        pass
    result['desktop_pipeline_jobs'] = 1
    return result
