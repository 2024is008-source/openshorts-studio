"""Central video-encoder selection for every ffmpeg encode call site.

FFMPEG_ENCODER env values:
  x264  (default) — CPU libx264, exact pre-GPU behavior
  nvenc           — force h264_nvenc; probed once and falls back to x264
                    (with a warning) if the GPU/driver is unavailable
  auto            — h264_nvenc when the probe succeeds, else x264

Only the codec/quality args live here; surrounding args (-movflags, -pix_fmt,
audio codecs, filters) stay at each call site.
"""
import os
import subprocess
import threading
import time
from contextlib import contextmanager

_encoder_context = threading.local()
X264_PRESETS = ('ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow')


def bounded_int(name, default, low, high):
    try: value=int(os.getenv(name,default))
    except (ValueError,TypeError): value=default
    return max(low,min(high,value))


@contextmanager
def cpu_encoding():
    """Per-thread CPU override; never changes another clip's environment."""
    previous=getattr(_encoder_context,'cpu',False)
    _encoder_context.cpu=True
    try: yield
    finally: _encoder_context.cpu=previous

# Quality tiers pinning the historical libx264 settings.
QUALITY = "quality"            # was: -preset medium -crf 18
QUALITY_FAST = "quality_fast"  # was: -preset fast -crf 18
DELIVERY = "delivery"          # was: -preset fast -crf 22

_X264_ARGS = {
    QUALITY: ["-c:v", "libx264", "-preset", "medium", "-crf", "18"],
    QUALITY_FAST: ["-c:v", "libx264", "-preset", "fast", "-crf", "18"],
    DELIVERY: ["-c:v", "libx264", "-preset", "fast", "-crf", "22"],
}

# NVENC -cq is not 1:1 with x264 CRF: benchmarked on the prod GPU (RTX 4000
# Ada), cq ≈ crf + 7 lands in the same file-size ballpark, with vbr + AQ for
# quality. Presets p1-p7: p5 ≈ "medium", p4 ≈ "fast".
# -pix_fmt yuv420p is REQUIRED: with RGB input (the bgr24 rawvideo pipe from
# OpenCV) nvenc otherwise emits H.264 in gbrp/GBR colorspace, which ffmpeg
# reads fine but web players render as a magenta/green mess.
_NVENC_ARGS = {
    QUALITY: ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
              "-rc", "vbr", "-cq", "25", "-b:v", "0",
              "-spatial-aq", "1", "-temporal-aq", "1", "-pix_fmt", "yuv420p"],
    QUALITY_FAST: ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
                   "-rc", "vbr", "-cq", "25", "-b:v", "0", "-spatial-aq", "1",
                   "-pix_fmt", "yuv420p"],
    DELIVERY: ["-c:v", "h264_nvenc", "-preset", "p4",
               "-rc", "vbr", "-cq", "29", "-b:v", "0", "-spatial-aq", "1",
               "-pix_fmt", "yuv420p"],
}

# Output args that drop container/stream metadata carried over from the source
# — most notably YouTube's "produced by Google Inc." stream handler, which
# otherwise survives every re-encode (ffmpeg copies input metadata by default)
# and rides into the published clip. The per-stream specifiers are required:
# global -map_metadata -1 alone leaves the audio handler_name intact on a
# stream copy. Empty audio/video specifiers are harmless when a clip lacks that
# stream (ffmpeg ignores them, verified). Spliced in before the output filename
# at each final-artifact producer; kept out of video_encode_args() so that
# stays purely codec/quality args.
METADATA_SCRUB = ["-map_metadata", "-1", "-map_chapters", "-1",
                  "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1"]

# Legacy fallback only (AUDIO_MASTERING=0). Default mastering now measures
# the finished mix in audio_mastering.py and verifies decoded AAC true peak.
# Historical AAC encodes overshot pre-encode limits; adding a sample limiter
# worsened intersample peaks. Keep encoder headroom and post-encode validation.
LOUDNORM_FILTER = "loudnorm=I=-14:TP=-2.0:LRA=11"


# AI Act art. 50(2): a provider whose system generates synthetic audio or video
# has to mark the output in a machine-readable way. The regulation asks for the
# marking, not for a particular standard, and the cheap one that survives every
# player and every upload is a container tag: `ffprobe -show_format` reads it
# back, and TikTok/Reels/YouTube ignore it. Stamped by a stream copy, so it is
# a remux (no quality loss, ~0.2 s) and never a re-encode.
#
# Deliberately narrow: it goes on outputs where a machine actually synthesised
# voice or a person (dubbing, AI actors), not on an ordinary clip, whose audio
# and pixels are the user's own footage. Marking everything would make the tag
# mean nothing.
AI_DISCLOSURE = "AI-generated content produced with OpenShorts (openshorts.app)"


def mark_ai_generated(path, detail=""):
    """Stamp AI Act art. 50(2) machine-readable tags on a finished file.

    Returns True when the file now carries the tags. Never raises: a missing
    tag must not lose the user the video they just paid minutes for.
    """
    note = f"{AI_DISCLOSURE}: {detail}" if detail else AI_DISCLOSURE
    tmp = f"{path}.aitag.mp4"
    # `comment` and not a custom `ai_generated` key: mp4 only carries the
    # standard iTunes-style tags, and ffmpeg drops anything else without
    # warning (verified with ffprobe -show_entries format_tags).
    # -map 0 because ffmpeg's default picks one stream per type: a dubbed file
    # that ever ships two audio tracks would come back with one.
    cmd = ["ffmpeg", "-y", "-i", path, "-map", "0", "-c", "copy",
           "-metadata", f"comment={note}",
           "-movflags", "+faststart", tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            print(f"[ai-tag] skipped for {os.path.basename(path)}: {r.stderr[-300:]}")
            if os.path.exists(tmp):
                os.remove(tmp)
            return False
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[ai-tag] skipped for {os.path.basename(path)}: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def audio_encode_args():
    """AAC encode args for a delivered clip, with loudness normalisation."""
    args = ["-c:a", "aac", "-ar", "48000", "-b:a", "192k"]
    if (os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0"
            and os.environ.get("AUDIO_MASTERING", "1").strip() == "0"):
        # Legacy fallback. Measured mastering otherwise runs once after rendering.
        args = ["-af", LOUDNORM_FILTER] + args
    return args

_probe_lock = threading.Lock()
_nvenc_ok = None  # None = not probed yet
_nvenc_retry_at = 0.
_announced = False


def _probe_nvenc():
    """One tiny lavfi encode to prove h264_nvenc works end-to-end.

    The probe uses the portrait delivery raster and production HQ/AQ flags.
    Any failure (no ffmpeg binary, no GPU, no driver libs) means False.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=black:s=1080x1920:r=30:d=0.1",
        "-frames:v", "2", "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq",
        "-rc", "vbr", "-cq", "20", "-b:v", "0", "-spatial-aq", "1",
        "-temporal-aq", "1", "-pix_fmt", "yuv420p", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def nvenc_available():
    """Probe h264_nvenc once and cache the verdict (thread-safe)."""
    global _nvenc_ok, _nvenc_retry_at
    if _nvenc_ok is False and _nvenc_retry_at and time.monotonic()>=_nvenc_retry_at:
        with _probe_lock:
            if _nvenc_retry_at and time.monotonic()>=_nvenc_retry_at:
                _nvenc_ok=None;_nvenc_retry_at=0.
    if _nvenc_ok is None:
        with _probe_lock:
            if _nvenc_ok is None:
                _nvenc_ok = _probe_nvenc()
    return _nvenc_ok


def reset_encoder_cache():
    """Test hook: forget the cached probe result."""
    global _nvenc_ok, _announced, _nvenc_retry_at
    with _probe_lock:
        _nvenc_ok = None
        _announced = False
        _nvenc_retry_at=0.


def nvenc_failed():
    """Do not repeatedly initialize a hardware session that just failed."""
    global _nvenc_ok, _nvenc_retry_at
    with _probe_lock:
        _nvenc_ok=False;_nvenc_retry_at=time.monotonic()+60


def _configured(args):
    args=list(args)
    codec=args[args.index('-c:v')+1]
    key='FFMPEG_NVENC_PRESET' if codec=='h264_nvenc' else 'FFMPEG_X264_PRESET'
    value=os.getenv(key)
    allowed=tuple('p'+str(i) for i in range(1,8)) if codec=='h264_nvenc' else X264_PRESETS
    if value is not None:
        if value not in allowed:raise ValueError(f'{key} must be one of {", ".join(allowed)}')
        args[args.index('-preset')+1]=value
    return args


def cpu_fallback_command(command):
    """Change encoder settings only; preserve filters, timing, audio and quality tier."""
    command=list(command)
    if 'h264_nvenc' not in command:return command
    cq=command[command.index('-cq')+1] if '-cq' in command else '25'
    crf='16' if float(cq)<=20 else '18' if float(cq)<=25 else '22'
    output=[];i=0
    remove={'-preset','-rc','-cq','-b:v','-spatial-aq','-temporal-aq','-tune','-gpu','-multipass'}
    while i<len(command):
        if command[i] in remove and i+1<len(command):i+=2;continue
        output.append('libx264' if command[i]=='h264_nvenc' else command[i]);i+=1
    profile=_configured(['-c:v','libx264','-preset','medium' if crf=='16' else 'fast','-crf',crf])
    # Codec was already replaced; append only its quality/speed arguments.
    return output[:-1]+profile[2:]+[output[-1]]


def video_encode_args(tier=QUALITY):
    """Return the codec/quality args for one encode, honoring FFMPEG_ENCODER."""
    global _announced
    if tier not in _X264_ARGS:
        raise ValueError(f"Unknown encode tier: {tier!r}")

    mode = os.environ.get("FFMPEG_ENCODER", "x264").strip().lower()
    use_nvenc = False
    if mode in ("nvenc", "auto") and not getattr(_encoder_context,'cpu',False):
        use_nvenc = nvenc_available()
        if mode == "nvenc" and not use_nvenc:
            print("⚠️ [Encoder] FFMPEG_ENCODER=nvenc but h264_nvenc is not "
                  "usable here — falling back to libx264")

    if not _announced:
        _announced = True
        print(f"🎞️ [Encoder] video encoder: {'h264_nvenc' if use_nvenc else 'libx264'} "
              f"(FFMPEG_ENCODER={mode})")

    if os.getenv("QUALITY_PRESET") == "studio":
        if use_nvenc:
            return _configured(["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq",
                    "-rc", "vbr", "-cq", "20", "-b:v", "0", "-spatial-aq", "1",
                    "-temporal-aq", "1", "-pix_fmt", "yuv420p"])
        return _configured(["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"])
    return _configured((_NVENC_ARGS if use_nvenc else _X264_ARGS)[tier])


def escape_filter_value(value):
    r"""Escape a path/value for use inside a quoted FFmpeg filter argument.

    Windows absolute paths are why this exists: ``:`` separates filter options,
    so an interpolated ``C:/x/y.txt`` makes the parser look for an option named
    ``/x/y.txt`` and the whole filtergraph fails to build.

    NOTE: an apostrophe in the path cannot be made safe here. ffmpeg's
    filtergraph parser is not a shell -- the shell idiom ``'\''`` was tried on
    29-jul-2026 and is worse than doing nothing: it drops the apostrophe AND
    swallows the following option, so ``ass='...Earth'\''s.ass':fontsdir='...'``
    resolved to a filename of "...Earths.ass:fontsdir=..." and failed to open.

    The only reliable answer is to keep apostrophes OUT of any path that is
    interpolated into a filter. Callers generate their own filenames, so they
    control this: use a neutral name, never one derived from a video title.
    """
    return value.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


# An mp4 that ffmpeg abandoned before writing the moov atom is a few dozen
# bytes of ftyp, or nothing at all. Anything a real cut produces is orders of
# magnitude larger, so this only ever catches a failed encode.
MIN_CUT_BYTES = 1024

# Legacy bounded retries for non-hardware cut failures. A diagnosed NVENC
# failure now retries once on CPU immediately (TASK-010); no hardware loop.
CUT_RETRY_WAITS = (3, 9)


def cut_clip(input_video, clip_temp_path, start, end, clip_number):
    """Cut [start, end] out of the source into ``clip_temp_path``.

    Raises RuntimeError with ffmpeg's own stderr when the cut does not produce
    a playable file. That report is the point: since dec-2025 the cut ran with
    its return code ignored and stderr captured into a pipe nobody read, so a
    failed cut handed an empty file to the reframer and the job's only visible
    error was "moov atom not found" three layers downstream — from ffmpeg,
    TransNetV2 and PySceneDetect in turn, each naming the temp file rather
    than the encode that never wrote it (prod, 9-sep-2026: three clips of one
    job lost, cause unrecoverable because the stderr had been discarded).

    A failed hardware session retries once with matching-tier libx264. Other
    failures retain the existing bounded retry schedule. Each attempt times
    out after 180 seconds; the production-size initialization probe is cached
    and rechecked after a runtime-failure cooldown.
    """
    encode_args = video_encode_args(QUALITY_FAST)
    command = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-to', str(end),
        '-i', input_video,
        *encode_args,
        *audio_encode_args(),
        '-pix_fmt','yuv420p','-movflags','+faststart',
        clip_temp_path
    ]

    def _run():
        result = subprocess.run(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, errors="replace",timeout=180)
        # ffmpeg has been seen exiting 0 having written nothing, so the file
        # itself is the verdict, not just the return code.
        size = os.path.getsize(clip_temp_path) if os.path.exists(clip_temp_path) else 0
        ok = result.returncode == 0 and size >= MIN_CUT_BYTES
        return ok, f"exit {result.returncode}, {size} bytes\n{(result.stderr or '').strip()[-800:]}"

    for attempt, wait in enumerate(CUT_RETRY_WAITS + (None,), start=1):
        ok, report = _run()
        if ok:
            if attempt > 1:
                print(f"   ✅ Clip {clip_number} cut on attempt {attempt}.")
            return
        from render_runtime import hardware_failure
        if 'h264_nvenc' in command and hardware_failure(report):
            command=cpu_fallback_command(command)
            nvenc_failed()
            print(f'   ⚠️ Clip {clip_number}: NVENC failed; retrying once with libx264 at the matching quality tier.')
            ok,report=_run()
            if ok:return
            break
        if wait is None:
            break
        print(f"   ⚠️ Cut of clip {clip_number} failed ({report}) — "
              f"retrying in {wait}s.")
        time.sleep(wait)

    raise RuntimeError(
        f"ffmpeg could not cut clip {clip_number} ({start}s-{end}s) from "
        f"{os.path.basename(input_video)} in {len(CUT_RETRY_WAITS) + 1} "
        f"attempts: {report}")


