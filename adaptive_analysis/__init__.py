"""Opt-in analysis stages feeding the existing Story/Editing Directors."""
VERSION=1


def enabled(mode=None):
    import os
    return (mode or os.getenv('ANALYSIS_MODE','transcript')) in ('adaptive-economy','adaptive-balanced','adaptive-quality')


def analyze(*args,**kwargs):
    from .pipeline import analyze as run
    try:return run(*args,**kwargs)
    except Exception as exc:
        from pathlib import Path
        from story_director import analysis_failure,atomic_json
        output=kwargs.get('output_dir') or (args[3] if len(args)>3 else None)
        if output:atomic_json(Path(output)/'analysis_failure.json',dict(adaptive=True,**analysis_failure(exc)))
        from .runtime import BudgetExceeded,Cancelled
        if isinstance(exc,(BudgetExceeded,Cancelled)):raise
        raise RuntimeError('Adaptive analysis stopped. See generation details for the failure type; validated checkpoints were retained.') from None
