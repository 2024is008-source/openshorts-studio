"""Pre-generation classification of a validated local import; no alternate API provider."""
import os
from pathlib import Path
import threading
from adaptive_analysis.runtime import Cache,Ledger,DEFAULTS

_lock=threading.Lock()


def analyze(source,duration,folder):
    import category_intelligence as ci
    from adaptive_analysis.media_index import identity
    from adaptive_analysis.gemini import Gateway
    from clip_selection import speech_units
    from story_director import atomic_json
    from transcribe_backends import get_whisper_config
    # Serialize optional preflight to avoid competing for the resident Whisper model.
    if not _lock.acquire(blocking=False):return ci.fallback('Another classification is running. Retry when it finishes.')
    try:
        cfg=dict(DEFAULTS['economy'],mode='economy',category='auto',cost_ceiling=None,input_price=None,output_price=None)
        cfg.update(job_seconds=180,text_requests=2,visual_requests=1,input_tokens=16000,retries=0,video_seconds=0)
        folder=Path(folder);source_id=identity(source)
        model=os.getenv('GEMINI_MODEL','gemini-3.1-flash-lite')
        root=folder/'category-cache';cache=Cache(root,source_id,model,dict(category='auto',prompt_constraint='category-v1'))
        ledger=Ledger(cfg,folder/'category-metrics.json')
        # A small source profile is independent of the chosen category. Never
        # transcribe a long upload synchronously in the settings dialog.
        signature=dict(category='auto',prompt_constraint='category-source-v1')
        source_cache=Cache(root,source_id,model,signature)
        from adaptive_analysis.runtime import digest
        speech_key=digest(['sampled-whisper-v1',get_whisper_config(),duration])
        asr=source_cache.read('media-index',speech_key)
        full_source=False
        if asr is None:
            shared=ci.source_transcript_cache(source,duration)
            if shared:
                retained=shared[0].read('media-index',shared[1])
                if isinstance(retained,dict) and isinstance(retained.get('segments'),list) and retained['segments']:
                    asr=retained;full_source=True
        if asr is None and Path(str(get_whisper_config()['model_size'])).is_dir():
            try:
                import subprocess,tempfile
                from transcribe_backends import _transcribe_with_whisper
                asr=dict(segments=[])
                with tempfile.TemporaryDirectory(prefix='category-asr-',dir=folder) as temp:
                    seen=set()
                    for i,fraction in enumerate((.1,.5,.9)):
                        ledger.check();start=max(0,min(duration-12,duration*fraction));length=min(12,duration-start)
                        if start in seen:continue
                        seen.add(start)
                        audio=Path(temp)/f'sample-{i}.wav'
                        subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str(start),'-t',str(length),'-i',str(source),'-vn','-ac','1','-ar','16000',str(audio)],capture_output=True,check=True,timeout=20)
                        sample=_transcribe_with_whisper(str(audio))
                        for segment in sample.get('segments',[]):
                            # Word timings from a partial sample are not presented
                            # as a complete transcription for generation.
                            if 0<=segment['start']<segment['end']<=length:
                                asr['segments'].append(dict(start=start+segment['start'],end=start+segment['end'],text=segment['text']))
                source_cache.write('media-index',speech_key,asr)
            except Exception:asr=None  # Missing/offline ASR leaves a bounded visual option.
        index=dict(duration=duration,units=speech_units(asr,duration),scenes=[],motion=[],audio=[],
            transcript_scope='full_source' if full_source else 'representative_samples')
        result=ci.detect(source,index,Gateway(model,ledger),cache,ledger,model)
        atomic_json(folder/'category-result.json',dict(source_identity=source_id,model=model,result=result))
        return result
    finally:_lock.release()
