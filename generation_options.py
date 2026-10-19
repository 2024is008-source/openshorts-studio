"""Validated nonsecret generation settings shared by API and recovery."""
import math

RESUME_OPTIONS = {
    'FFMPEG_ENCODER','FFMPEG_X264_PRESET','FFMPEG_NVENC_PRESET','FFMPEG_THREADS',
    'RENDER_MAX_ENCODERS','CLIP_WORKERS','RENDER_STRICT_OVERLAYS',
    'VIDEO_TEMPLATE','VIDEO_TEMPLATES_ENABLED',
    'AUDIO_MASTERING','AUDIO_NORMALIZE','AUDIO_PRESET','AUDIO_TARGET_LUFS','AUDIO_TRUE_PEAK',
    'AUDIO_FADE_SECONDS','AUDIO_NOISE_REDUCTION',
    'GENERATION_MODE','ANALYSIS_MODE','SUMMARY_SECONDS','CAPTION_PRESET',
    'AMCE_CATEGORY','AMCE_PROMPT','AMCE_MAX_VIDEO_SECONDS','AMCE_MAX_VISUAL_REQUESTS','AMCE_MAX_INPUT_TOKENS',
    'AMCE_MAX_JOB_SECONDS','AMCE_MAX_RETRIES','AMCE_MAX_CANDIDATES','AMCE_MAX_TEXT_REQUESTS',
    'AMCE_COST_CEILING','AMCE_INPUT_PRICE','AMCE_OUTPUT_PRICE',
    'QUALITY_PRESET','FRAMING_PRESET','AUTO_CAPTIONS','AUTO_HOOK','AUTO_HOOK_STYLE',
    'AUTO_LAYOUT','SPLIT_LAYOUT','SCREENCAST_LAYOUT','SPEAKER_SIGNAL','SPEAKER_CUT',
    'PUNCH_IN','CLIP_TARGET_MIN','CLIP_TARGET_MAX','CLIP_MIN_SECONDS','CLIP_MAX_SECONDS',
    'PYTHONIOENCODING',
    'CLIP_TARGET_SECONDS','CLIP_STORY_AWARE','CLIP_SCORE_WEIGHTS',
    'EDIT_DIRECTOR','EDIT_DIRECTOR_STRATEGY','STORY_MODE','STORY_AUDIO_ENERGY',
    'REFRAME_KEYFRAMES','REFRAME_SUBJECT_CONTEXT','REFRAME_OBJECT_CLASSES',
    'SMART_REFRAME','REFRAME_OUTPUT_SIZE',
    'PACING_ENABLED','PACING_MODE','PACING_TRIM_SILENCE','PACING_ALLOW_INCOMPLETE_END',
}


def clip_target_options(value, minimum=None, maximum=None):
    """Soft duration targets allow whole sentences instead of exact cuts."""
    if value in (None,''): return {}
    try: target=float(value)
    except (ValueError,TypeError): raise ValueError('clip_target_seconds must be a number')
    if not math.isfinite(target) or not 10<=target<=150:
        raise ValueError('clip_target_seconds must be between 10 and 150')
    lo=float(minimum) if minimum is not None else max(5,round(target*.75,3))
    hi=float(maximum) if maximum is not None else min(180,max(lo+5,round(target*1.2,3)))
    if not lo<=target<=hi or hi<lo+5:
        raise ValueError('clip duration band must contain its target and span at least 5 seconds')
    return {'CLIP_TARGET_SECONDS':str(target),'CLIP_MIN_SECONDS':str(lo),'CLIP_MAX_SECONDS':str(hi)}


def pacing_options(mode=None,trim=None):
    result={}
    if mode is not None:
        if mode not in ('fast','balanced','emotional','educational'):
            raise ValueError('pacing_mode must be fast, balanced, emotional or educational')
        result['PACING_MODE']=mode
    if trim is not None:
        if str(trim).lower() not in ('0','1','true','false'):
            raise ValueError('trim_silence must be a boolean')
        result['PACING_TRIM_SILENCE']='1' if str(trim).lower() in ('1','true') else '0'
    return result


def normalize_options(mode=None, analysis=None, seconds=None, captions=None,
                      quality=None, framing=None,pacing=None,trim_silence=None,
                      audio_preset=None,audio_target=None,audio_peak=None,audio_fade=None,audio_noise=None,video_template=None,
                      analysis_category=None,analysis_prompt=None):
    import video_templates
    chosen=video_templates.selected(video_template)
    from audio_mastering import options as audio_options
    def choice(value, default, allowed, label):
        value = default if value is None else str(value)
        if value not in allowed:
            raise ValueError(f'{label} must be one of: {", ".join(allowed)}')
        return value
    mode = choice(mode,'clips',('clips','highlights'),'generation_mode')
    analysis = choice(analysis,'transcript',('transcript','hybrid','adaptive-economy','adaptive-balanced','adaptive-quality'),'analysis_mode')
    from adaptive_analysis.runtime import CATEGORIES
    category=choice(analysis_category,'auto',CATEGORIES,'analysis_category')
    constraint='' if analysis_prompt is None else str(analysis_prompt)
    if len(constraint)>500:raise ValueError('analysis_prompt must be at most 500 characters')
    try: seconds = 60.0 if seconds is None else float(seconds)
    except (TypeError,ValueError): raise ValueError('summary_seconds must be a number')
    if not math.isfinite(seconds) or not 30 <= seconds <= 180:
        raise ValueError('summary_seconds must be between 30 and 180')
    return {
        'GENERATION_MODE': mode,
        'ANALYSIS_MODE': 'hybrid' if mode=='highlights' and not analysis.startswith('adaptive-') else analysis,
        'AMCE_CATEGORY':category,'AMCE_PROMPT':constraint,
        'SUMMARY_SECONDS': str(seconds),
        'CAPTION_PRESET':choice(captions,'classic',('auto','classic','clean','clean-minimal','bold-creator','dynamic-highlight','podcast','cinematic','openshorts-dynamic','creator-bold','clean-podcast','minimal','green-pop','teal-reveal','paper-focus'),'caption_preset'),
        'QUALITY_PRESET':choice(quality,'standard',('standard','studio'),'quality_preset'),
        'FRAMING_PRESET':choice(framing,'balanced',('auto','balanced','subject','editorial'),'framing_preset'),
        **({'EDIT_DIRECTOR':'1','SMART_REFRAME':'1','REFRAME_KEYFRAMES':'1',
            'SPLIT_LAYOUT':'1','AUTO_LAYOUT':'1','CLIP_STORY_AWARE':'1',
            'STORY_MODE':'auto','PACING_ENABLED':'1','AUDIO_MASTERING':'1',
            'AUDIO_NORMALIZE':'1'} if framing=='auto' else {}),
        **pacing_options(pacing,trim_silence),
        **audio_options(audio_preset,audio_target,audio_peak,audio_fade,audio_noise),
        **({'VIDEO_TEMPLATE':'auto' if video_template=='auto' else chosen['id']} if chosen else ({'VIDEO_TEMPLATE':'none'} if video_template is not None else {})),
    }
