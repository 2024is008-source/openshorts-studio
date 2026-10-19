"""Reframe engine v2: analyze in Python, render natively in ffmpeg.

v1 decodes every frame at full resolution in OpenCV, crops/resizes in numpy
and pipes raw frames back into ffmpeg. v2 splits that into:

  1. ANALYSIS — one ffmpeg-decoded pass at <=640px feeding the same detectors
     and the same SmoothedCameraman/SpeakerTracker state machines as v1.
     Bounded-error timestamped keyframes freeze the smoothed shot trajectory.
  2. RENDER — one ffmpeg process per scene doing decode -> dynamic crop
     (sendcmd) -> scale -> encode natively (TRACK scenes), or the blurred
     background filtergraph (GENERAL scenes); segments are then concatenated
     with stream copy and the audio mapped straight from the source clip.

No raw-frame piping, no second full-res decode, one less intermediate encode.
Automatic callers retain the v1 fallback; explicit/validated decisions fail closed.

Pure helpers (sendcmd/concat generation, scene slicing) have no heavy imports
so they stay unit-testable in CI.
"""
import os
import subprocess
import tempfile
import math
import re
import threading

from framing_geometry import (contain_background, crop_size, crop_position,
                              finite, validate_source, compact_keyframes, sample_keyframes,retain_regions,background_soften)

import active_speaker
import camera_inset
import punch_in
import screencast_layout
import layout_ranges
import split_layout
from ffmpeg_utils import (video_encode_args, escape_filter_value, QUALITY_FAST,
                          METADATA_SCRUB)

ANALYSIS_MAX_WIDTH = 640


# Short-form platforms (TikTok / Reels / Shorts) expect a 1080-wide vertical
# upload; anything smaller is treated as low quality and re-encoded from the
# already-soft source. The crop region is whatever the source height allows, so
# a 720p input yields a 406x720 crop — we scale that up to the delivery floor
# rather than shipping sub-HD. Sources that already exceed it are left alone
# (never downscale quality the user supplied).
DELIVERY_MIN_WIDTH = 1080


# --- pure helpers (CI-testable) --------------------------------------------

def delivery_size(orig_w, orig_h, aspect_ratio):
    """Output (width, height) for a reframe of this source.

    Picks the largest crop the source allows, then upscales to
    ``DELIVERY_MIN_WIDTH`` if that crop is narrower. Both dimensions come back
    even (x264/NVENC reject odd ones).
    """
    validate_source(orig_w, orig_h, aspect_ratio)
    # Explicit delivery preset; preserve the historical source-size floor by
    # default for callers exporting sources above full HD.
    if os.getenv('REFRAME_OUTPUT_SIZE', 'fullhd' if os.getenv('EDIT_DIRECTOR')=='1' else 'source') == 'fullhd':
        return DELIVERY_MIN_WIDTH, max(2, round(DELIVERY_MIN_WIDTH / aspect_ratio / 2) * 2)
    out_h = orig_h
    out_w = int(out_h * aspect_ratio)
    if out_w > orig_w:
        out_w = orig_w
        out_h = int(out_w / aspect_ratio)

    if out_w < DELIVERY_MIN_WIDTH:
        out_w = DELIVERY_MIN_WIDTH
        out_h = int(round(out_w / aspect_ratio))

    return out_w + (out_w % 2), out_h + (out_h % 2)


def source_already_fits(orig_w, orig_h, aspect_ratio, tol=0.01):
    """True when the source already matches the target aspect.

    Such a source has no width to throw away, so every layout that rearranges
    the frame is a downgrade: GENERAL puts it in a blurred bed, SPLIT stacks
    two crops of an already-narrow frame, SCREENCAST/INSET carve panels out of
    it. TRACK is the only one that leaves it alone — its crop is the whole
    frame — so a vertical upload should pass straight through.
    """
    validate_source(orig_w, orig_h, aspect_ratio)
    return abs(orig_w / float(orig_h) - aspect_ratio) <= aspect_ratio * tol


def dedupe_sendcmd_lines(xs, fps, target="crop@c"):
    """sendcmd lines setting crop x per frame, deduped to change-points.

    Timestamps are relative to the segment (the render seeks per scene).
    """
    return dedupe_sendcmd_axis(xs, fps, 'x', target)


def dedupe_sendcmd_axis(values, fps, axis, target='crop@c'):
    lines = []
    prev = None
    for i, x in enumerate(values):
        if x != prev:
            lines.append(f"{i / fps:.4f} {target} {axis} {x};")
            prev = x
    return lines


def scene_frame_ranges(scene_boundaries, strategies, total_frames):
    """Clamp scene (start, end) frame ranges to the decoded frame count,
    dropping empty ranges. Each range keeps its strategy so later indices
    can't misalign when a range is dropped."""
    ranges = []
    for i, (start_f, end_f) in enumerate(scene_boundaries):
        strategy = strategies[i] if i < len(strategies) else 'TRACK'
        start_f = max(0, min(start_f, total_frames))
        end_f = max(start_f, min(end_f, total_frames))
        if end_f > start_f:
            ranges.append((start_f, end_f, strategy))
    return ranges


def concat_list_content(segment_paths):
    # Single quotes per concat-demuxer spec; our paths are tempfile-generated
    # (no quotes in them).
    return "".join(f"file '{p}'\n" for p in segment_paths)


# How much of the frame height the real content should fill in GENERAL layout.
#
# Fitting a 16:9 source to the full output width leaves it 608px tall in a
# 1920px frame — the content is 32% of the screen and 68% is blurred filler.
# That reads as a thumbnail floating in soup, and it is what a GENERAL scene
# looked like in real delivered clips (audited 26-jul-2026).
#
# Scaling the content up and letting the sides overflow trades width for
# presence, and the trade has to stay conservative: GENERAL is chosen for group
# shots and landscapes, exactly the material where cropping the sides cuts
# someone out of frame. At 0.42 a 16:9 source keeps ~76% of its width while
# going from 32% to 42% of the frame height. 0.55 was tried and rejected — it
# reaches 55% height but throws away 42% of the width.
#
# This tuning is retained for SMART_REFRAME=0 only. Within that compatibility
# path, GENERAL_CONTENT_HEIGHT_RATIO=0.32 restores the old full-width behaviour.
GENERAL_CONTENT_HEIGHT_RATIO = float(
    os.environ.get("GENERAL_CONTENT_HEIGHT_RATIO", "0.42"))


def full_width_content_height(orig_w, orig_h, out_w):
    """Height the source fills when its FULL width is kept (even)."""
    fg_h = int(round(out_w * orig_h / float(orig_w)))
    return fg_h + (fg_h % 2)


def general_filtergraph(out_w, out_h, content_h=None, orig_w=None, orig_h=None):
    """Preserve the full source over a blurred cover background by default.

    SMART_REFRAME=0 restores the historical foreground-height tuning below.
    That layout's bg fills the frame (centre-
    cropped, blurred), fg is scaled to a readable share of the height and
    centred, overflowing the sides rather than floating small in the middle.

    ``content_h`` overrides the height ratio. Passing the full-width height
    turns the side-cropping off entirely, which is what a scene full of charts
    or spreadsheets needs: the default 0.42 ratio buys presence by throwing away
    ~24% of the width, and on that material the discarded columns are the point.

    ``orig_w``/``orig_h`` floor the foreground at the height where the source
    fills the output width. The 0.42 ratio buys presence on a LANDSCAPE source
    by overflowing the sides; on a portrait one the same number is a shrink —
    an already-9:16 upload came back as a 453px sliver floating over a blurred
    copy of itself. Filling the width is the floor, never the target.
    """
    if os.getenv('SMART_REFRAME', '1') != '0':
        return contain_background(out_w, out_h)
    fg_h = content_h if content_h else int(out_h * GENERAL_CONTENT_HEIGHT_RATIO)
    if orig_w and orig_h:
        fg_h = max(fg_h, full_width_content_height(orig_w, orig_h, out_w))
    fg_h += fg_h % 2
    return (
        f"[0:v]split=2[bga][fga];"
        f"[bga]scale=-2:{out_h},crop=w=min(iw\\,{out_w}):h={out_h},"
        f"scale={out_w}:{out_h},{background_soften(out_w,out_h)}[bg];"
        # Scale by HEIGHT, then trim any overflow to the output width. crop
        # centres by default, and min() makes it a no-op when the scaled source
        # is already narrower than the frame (portrait/square sources).
        f"[fga]scale=-2:{fg_h},crop=w=min(iw\\,{out_w}):h=ih[fg];"
        f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[v]"
    )


def editorial_geometry(orig_w, orig_h, out_w, out_h, focus_x=None):
    """A full-height detail view above a full-width context view.

    The lower panel preserves every person and any source captions. The upper
    panel uses the space that would otherwise be a large blurred duplicate.
    Both panels are taken from the same source frame and preserve their aspect
    ratios. ``focus_x`` is a source-pixel centre chosen from sampled faces.
    """
    validate_source(orig_w, orig_h, out_w / out_h)
    context_h = max(2, min(full_width_content_height(orig_w, orig_h, out_w),
                         int(out_h * .45) // 2 * 2))
    detail_h = out_h - context_h
    crop_w, crop_h = crop_size(orig_w, orig_h, out_w / detail_h)
    x, y = crop_position(orig_w, orig_h, crop_w, crop_h, focus_x)
    return crop_w, crop_h, x, y, detail_h, context_h


def editorial_filtergraph(orig_w, orig_h, out_w, out_h, focus_x=None):
    crop_w, crop_h, x, y, detail_h, context_h = editorial_geometry(
        orig_w, orig_h, out_w, out_h, focus_x)
    context = (f'[context]scale={out_w}:{context_h},setsar=1[bottom]'
               if abs(context_h - out_w * orig_h / orig_w) <= 2 else
               contain_background(out_w, context_h, 'context', 'bottom', 'contextbed'))
    return (
        f"[0:v]split=2[detail][context];"
        f"[detail]crop=w={crop_w}:h={crop_h}:x={x}:y={y},"
        f"scale={out_w}:{detail_h}[top];"
        + context + ';[top][bottom]vstack=inputs=2,setsar=1[v]'
    )


def _scene_focus_x(video_path, start_f, end_f, frame_w):
    """Choose one stable crop centre for a group scene from three samples."""
    import cv2
    import main as m

    cap = cv2.VideoCapture(video_path)
    centres = []
    try:
        for fraction in (.2, .5, .8):
            cap.set(cv2.CAP_PROP_POS_FRAMES,
                    int(start_f + (end_f - start_f - 1) * fraction))
            ok, frame = cap.read()
            if not ok:
                continue
            faces = m.detect_face_candidates(frame)
            if faces:
                xs = [c['box'][0] + c['box'][2] / 2 for c in faces]
                centres.append((min(xs) + max(xs)) / 2)
    finally:
        cap.release()
    return sorted(centres)[len(centres)//2] if centres else frame_w / 2


# --- analysis ---------------------------------------------------------------


def _watch_dimensions(stream, expected, changed):
    """Drain decoder diagnostics, retaining only a source-size change flag."""
    for line in iter(stream.readline, b''):
        if b'Parsed_showinfo' in line:
            match = re.search(rb'\bs:(\d+)x(\d+)\b', line)
            if match and tuple(map(int, match.groups())) != expected:
                changed.set()

def apply_crop_overrides(xs, strategies, scene_boundaries, overrides,
                         crop_w, orig_w, orig_h=None, splits=None):
    """Frame the scenes the user positioned by hand.

    ``overrides`` maps a scene index to either

      * a number — the crop CENTRE as a fraction of the source width, giving a
        single locked 9:16 window for that scene; or
      * ``{"top": v, "bottom": v}`` — two centres, stacking those two regions
        one above the other (the SPLIT layout). Each half is either a bare
        fraction (horizontal only) or ``{"x": f, "y": f}``; SPLIT crops are
        SHORTER than the source, so they carry a vertical centre too.

    Fractions travel instead of pixels because the editor knows where it
    dropped the rectangle, not the source's dimensions, and the same number
    survives a source re-encode at another resolution.

    A hand-framed scene overrides its automatic verdict outright: the single
    form forces TRACK so a scene the detector had sent to GENERAL (blurred
    background) comes back to a vertical crop, and the split form writes
    straight into ``splits``, so the user can stack a scene the detector never
    proposed — no dependency on SPLIT_LAYOUT being switched on.

    Runs after every automatic pass, including the ALTERNATE writes, so a
    manual choice always wins. Unknown scene indices and malformed values are
    skipped rather than rejected: a stale editor tab must not fail the render.
    """
    max_x = max(0, orig_w - crop_w)

    def to_x(fraction):
        number = float(fraction)
        if not math.isfinite(number):
            raise ValueError('crop centre must be finite')
        return max(0, min(int(round(number * orig_w - crop_w / 2)), max_x))

    for raw_idx, value in (overrides or {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError, OverflowError):
            continue
        if not 0 <= idx < len(scene_boundaries):
            continue
        start_f, end_f = scene_boundaries[idx]
        end_f = min(end_f, len(xs))
        if end_f <= start_f:
            continue

        if isinstance(value, dict):
            # Split: the halves are centres in SOURCE PIXELS, which is what
            # split_filtergraph expects — unlike the single-crop path, there is
            # no crop window to offset by.
            # split_geometry reads centre[0]/centre[1]: each half is a POINT,
            # not a horizontal position, because its crop is shorter than the
            # source and has to be placed vertically as well.
            def point(half):
                if isinstance(half, dict):
                    fx, fy = float(half['x']), float(half.get('y', 0.5))
                else:
                    fx, fy = float(half), 0.5
                if not math.isfinite(fx) or not math.isfinite(fy):
                    raise ValueError('crop centre must be finite')
                return (max(0, min(fx, 1)) * orig_w,
                        max(0, min(fy, 1)) * orig_h)

            try:
                centres = (point(value['top']), point(value['bottom']))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if splits is None or not orig_h:
                continue
            splits[start_f] = centres
            strategies[idx] = 'SPLIT'
            continue

        try:
            x = to_x(value)
        except (TypeError, ValueError, OverflowError):
            continue
        xs[start_f:end_f] = [x] * (end_f - start_f)
        strategies[idx] = 'TRACK'
        # A scene taken over by a single locked crop must not also carry a
        # stale split recipe from the detector.
        if splits is not None:
            splits.pop(start_f, None)

    return xs, strategies


def _analyze_trajectory(input_video, scenes_boundaries, scene_strategies,
                        fps, orig_w, orig_h, cameraman, tracker, ys=None,
                        allow_context=True, subject_evidence=None, context_evidence=None):
    """Replays v1's per-frame decision loop on a downscaled ffmpeg-decoded
    stream. Returns xs: crop x per frame (None on GENERAL frames)."""
    import numpy as np
    import main as m
    import editing_director
    reset_at_cut=m.SCENE_CUT_RESET or editing_director.enabled() or os.getenv('SMART_REFRAME','1')!='0'

    small_w = min(ANALYSIS_MAX_WIDTH, orig_w)
    if small_w % 2:
        small_w -= 1
    small_h = max(int(orig_h * small_w / orig_w), 2)
    if small_h % 2:
        small_h += 1
    scale_x, scale_y = orig_w / small_w, orig_h / small_h
    frame_bytes = small_w * small_h * 3

    proc = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-loglevel", "info", "-i", input_video,
         # No checksum or extra decode pass: inspect dimensions before scale
         # normalizes them, so fixed render coordinates cannot silently drift.
         "-vf", f"showinfo=checksum=0,scale={small_w}:{small_h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=frame_bytes * 4)

    changed_dimensions = threading.Event()
    diagnostics = None
    if getattr(proc, 'stderr', None) is not None:
        diagnostics = threading.Thread(target=_watch_dimensions,
            args=(proc.stderr, (orig_w, orig_h), changed_dimensions), daemon=True)
        diagnostics.start()

    xs = []
    frame_number = 0
    current_scene_index = 0
    coverage = {}
    context_coverage={};missing={};last_context={};context_available=True
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape((small_h, small_w, 3))

            if current_scene_index < len(scenes_boundaries):
                start_f, end_f = scenes_boundaries[current_scene_index]
                while frame_number >= end_f and current_scene_index < len(scenes_boundaries) - 1:
                    current_scene_index += 1
                    start_f, end_f = scenes_boundaries[current_scene_index]

            strategy = (scene_strategies[current_scene_index]
                        if current_scene_index < len(scene_strategies) else 'TRACK')

            # SPLIT, SCREENCAST and WIDE crops are static (fixed boxes for the
            # whole scene), so like GENERAL they need no camera trajectory.
            # ALTERNATE gets one written in after this pass.
            if strategy in ('GENERAL', 'SPLIT', 'SCREENCAST', 'WIDE',
                            'INSET', 'ALTERNATE'):
                cameraman.current_center_x = orig_w / 2
                cameraman.target_center_x = orig_w / 2
                xs.append(None)
                if ys is not None:
                    ys.append(None)
            else:
                is_scene_start = (
                    current_scene_index < len(scenes_boundaries)
                    and frame_number == scenes_boundaries[current_scene_index][0])
                cut = is_scene_start and reset_at_cut
                if cut:
                    # New shot: forget the old subject and cut to the new one
                    # (see SmoothedCameraman.begin_scene).
                    tracker.reset()
                    cameraman.begin_scene()

                candidates = []
                if frame_number % m.DETECT_STRIDE == 0 or cut:
                    person_box=None
                    candidates = (m.detect_portrait_candidates(frame) if
                        __import__('video_templates').framing_preference()=='auto' else m.detect_face_candidates(frame))
                    for cand in candidates:
                        cand['box'] = [int(v * s) for v, s in
                                       zip(cand['box'], (scale_x, scale_y, scale_x, scale_y))]
                        cand['score'] = cand['box'][2] * cand['box'][3]
                    if subject_evidence is not None:
                        rows=subject_evidence.setdefault(start_f,[])
                        retain_regions(rows,[c['box'] for c in candidates])
                    target_box = tracker.get_target(candidates, frame_number, orig_w)
                    if __import__('video_templates').framing_preference()=='auto' and candidates:
                        primary=[c['box'] for c in candidates if c['score']>=max(c['score'] for c in candidates)*.35]
                        left=min(x for x,y,w,h in primary);right=max(x+w for x,y,w,h in primary)
                        top=min(y for x,y,w,h in primary);bottom=max(y+h for x,y,w,h in primary)
                        if right-left<=cameraman.crop_width*.9 and bottom-top<=cameraman.crop_height*.9:
                            target_box=[left,top,right-left,bottom-top]
                    if target_box:
                        cameraman.update_target(target_box)
                    elif not candidates and (frame_number % m.YOLO_FALLBACK_STRIDE == 0 or cut):
                        person_box = m.detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target([int(v * s) for v, s in
                                zip(person_box, (scale_x, scale_y, scale_x, scale_y))])
                    missing.setdefault(current_scene_index,[]).append(bool(target_box or person_box))

                x1, _y1, _x2, _y2 = cameraman.get_crop_box(force_snap=is_scene_start)
                if candidates and allow_context:
                    # A camera cannot both pan gently and follow a subject
                    # teleporting beyond the crop. Preserve this entire scene
                    # if a sustained set of detections would be cut off.
                    largest = max(c['score'] for c in candidates)
                    primary = [c['box'] for c in candidates if c['score'] >= largest*.35]
                    samples, misses = coverage.get(current_scene_index, (0, 0))
                    missed = any(x < x1 or x+w > _x2 or y < _y1 or y+h > _y2
                                 for x,y,w,h in primary)
                    coverage[current_scene_index] = samples+1, misses+int(missed)
                    if (context_available and os.getenv('SMART_REFRAME','1')!='0' and
                        os.getenv('REFRAME_SUBJECT_CONTEXT','1')!='0' and
                        frame_number-last_context.get(current_scene_index,-fps)>=max(1,round(fps*.75)) and
                        (cameraman.crop_width<orig_w-2 or cameraman.crop_height<orig_h-2)):
                        last_context[current_scene_index]=frame_number
                        try:
                            regions=m.detect_framing_regions(frame)
                            people=[r for r in regions if r['label']=='person']
                            largest=max((r['box'][2]*r['box'][3] for r in people),default=0)
                            automatic=__import__('video_templates').framing_preference()=='auto'
                            regions=[r for r in regions if r['label']!='person' or (
                                not automatic and r['box'][2]*r['box'][3]>=largest*.35)]
                            boxes=[[v*s for v,s in zip(r['box'],(scale_x,scale_y,scale_x,scale_y))] for r in regions]
                            bad=any(x<x1-2 or x+w>_x2+2 or y<_y1-2 or y+h>_y2+2 for x,y,w,h in boxes)
                            n,fail=context_coverage.get(current_scene_index,(0,0));context_coverage[current_scene_index]=(n+1,fail+int(bad))
                            if context_evidence is not None:
                                saved=context_evidence.setdefault(start_f,[])
                                retain_regions(saved,boxes)
                        except Exception as exc:
                            # Optional detector/context failure cannot lose a clip.
                            context_available=False
                            print(f'   ⚠️ Body/object framing unavailable ({type(exc).__name__}); retaining face/context routing.')
                xs.append(x1)
                if ys is not None:
                    ys.append(_y1)

            frame_number += 1
    finally:
        proc.stdout.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError('frame analysis decoder did not exit')
        finally:
            if diagnostics is not None:
                diagnostics.join(timeout=2)
                proc.stderr.close()

    if proc.returncode:
        raise RuntimeError('frame analysis decoder failed')
    if changed_dimensions.is_set():
        raise RuntimeError('source resolution changed; adaptive frame rendering is required')

    if os.getenv('SMART_REFRAME', '1') != '0':
        for scene_index, (samples, misses) in coverage.items():
            if samples >= 3 and misses / samples >= .35:
                scene_strategies[scene_index] = 'GENERAL'
        if allow_context:
            for scene_index,(samples,misses) in context_coverage.items():
                if samples>=2 and misses/samples>=.5:scene_strategies[scene_index]='GENERAL'
            for scene_index,seen in missing.items():
                # Brief occlusions hold the last crop; sustained missing
                # subjects use the full shot instead of an off-centre ghost crop.
                if len(seen)>=max(3,round(fps/max(1,m.DETECT_STRIDE))) and sum(seen)/len(seen)<.4:
                    scene_strategies[scene_index]='GENERAL'

    return xs


# --- render -----------------------------------------------------------------

def _run(cmd):
    import render_runtime
    return render_runtime.run(cmd,timeout=1800)


def render(input_video, final_output_video, aspect_ratio, content_ranges=None,
           force_strategy=None, crop_overrides=None, director_context=None):
    """Full v2 reframe of one clip. Raises on failure (caller falls back).

    ``content_ranges`` comes from screencast_layout.detect_content_ranges() on
    the SOURCE video, already translated into this clip's timeline. None or []
    means the layout never triggers, which is the default.

    ``force_strategy`` ('WIDE' / 'TRACK' / any layout the render loop knows)
    applies that layout to EVERY scene, skipping the classifier and the layout
    upgrades — the clip editor's whole-clip framing override.

    ``crop_overrides`` maps scene index -> crop centre as a fraction of the
    source width, for scenes the user framed by hand in the editor. Scenes not
    listed keep the automatic camera, so correcting one bad shot never disturbs
    the ones the tracker got right. Applied AFTER force_strategy: a per-scene
    hand position always beats the whole-clip choice for the scenes it names.
    """
    import main as m
    auto_content_ranges = content_ranges is None
    content_ranges = content_ranges or []

    print("   🚀 Reframe engine v2 (ffmpeg-native render)")
    scenes, fps = m.detect_scenes(input_video)
    fps = float(fps)  # PySceneDetect can hand back a Fraction
    orig_w, orig_h = m.get_video_resolution(input_video)

    # The previous code had the detector but never invoked it from this render
    # path, so SCREENCAST/WIDE could be enabled yet receive no ranges. Run it
    # only when auto-layout enabled the module and the caller did not already
    # provide translated source ranges.
    if auto_content_ranges and screencast_layout.ENABLED and not force_strategy:
        try:
            import cv2
            _cap = cv2.VideoCapture(input_video)
            _frames = int(_cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            _clip_fps = float(_cap.get(cv2.CAP_PROP_FPS) or fps or 30.0)
            _cap.release()
            _duration = _frames / _clip_fps if _frames else 0.0
            if _duration > 0:
                content_ranges = screencast_layout.detect_content_ranges(
                    input_video, _duration)
        except Exception as e:
            print(f"   ⚠️ Important-scene analysis failed ({e}) — "
                  f"keeping face/scene routing.")

    out_w, out_h = delivery_size(orig_w, orig_h, aspect_ratio)

    if not scenes:
        import cv2
        cap = cv2.VideoCapture(input_video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(total, fps))]

    scene_boundaries = [(s.get_frames(), e.get_frames()) for s, e in scenes]
    import editing_director
    if editing_director.enabled() and director_context:
        from scenedetect import FrameTimecode
        offset=0;joins=[]
        for part in director_context.get('segments',[])[:-1]:
            offset+=part['end']-part['start'];joins.append(round(offset*fps))
        boundaries=sorted(set([v for pair in scene_boundaries for v in pair]+joins))
        scenes=[(FrameTimecode(a,fps),FrameTimecode(b,fps)) for a,b in zip(boundaries,boundaries[1:]) if b>a]
        scene_boundaries=[(s.get_frames(),e.get_frames()) for s,e in scenes]
    # A source shot vertical is already the output: nothing to reframe. The
    # scene classifier still sends its face-less shots (a slide, a chart, a
    # screen recording) to GENERAL, and GENERAL on such a source shrank the
    # whole frame into the middle of a blurred copy of itself. Skip the
    # classifier and every layout upgrade instead of trying to survive them.
    passthrough = source_already_fits(orig_w, orig_h, aspect_ratio)
    if force_strategy:
        strategies = [force_strategy] * len(scenes)
        content_ranges = []  # no screencast/inset upgrades over an explicit choice
        print(f"   🎯 Framing override: every scene -> {force_strategy}")
    elif passthrough:
        strategies = ['TRACK'] * len(scenes)
        content_ranges = []
        print(f"   ↕️  Source is already {orig_w}x{orig_h} vertical — "
              f"passing it through, no reframe")
    else:
        strategies = m.analyze_scenes_strategy(input_video, scenes, aspect_ratio)

    # SPLIT is an upgrade applied on top of the TRACK/GENERAL verdict, keyed by
    # the scene's START FRAME rather than its index: scene_frame_ranges() drops
    # empty ranges, so indices there don't line up with `scenes`. A surviving
    # range always keeps its original start_f (the clamp only bites on scenes
    # that begin past the last decoded frame, and those get dropped).
    splits = {}
    split_scene_of = {}
    detected_splits = {} if passthrough or force_strategy else split_layout.detect_split_scenes(
        input_video, scenes, strategies)
    import editing_director
    layout_reasons={}
    for scene_idx, centres in detected_splits.items():
        a,b=scene_boundaries[scene_idx]
        intent,reason=editing_director.scene_layout_policy(director_context or {},a,b,fps)
        independent=split_layout.independent_split(orig_w,orig_h,out_w,out_h,centres)
        if intent!='two_speaker_split' or not independent:
            strategies[scene_idx]='GENERAL'
            layout_reasons[a]=reason if intent!='two_speaker_split' else 'Detected panel crops overlap or repeat another subject; preserve the full scene.'
            print(f'   Scene {scene_idx}: preserving shared context instead of stacking',flush=True)
            continue
        layout_reasons[a]=reason
        strategies[scene_idx] = 'SPLIT'
        start_f = scene_boundaries[scene_idx][0]
        splits[start_f] = centres
        split_scene_of[start_f] = scene_idx

    director_context=dict(director_context or {})
    director_context['_scene_layout_reasons']=layout_reasons

    # Geometry alone will stack a scene where one person never speaks. Ask who
    # is actually talking before spending half the frame on the other one.
    alternates = {}
    if splits and active_speaker.ENABLED:
        for start_f in list(splits):
            scene_idx = split_scene_of[start_f]
            end_f = scene_boundaries[scene_idx][1]
            verdicts = active_speaker.verdicts_for_scene(
                input_video, start_f, end_f, fps, splits[start_f])
            reliable=active_speaker.reliable(verdicts)
            if reliable and not active_speaker.is_conversation(verdicts):
                a, b = active_speaker.shares(verdicts)
                print(f"   🔇 Scene {scene_idx}: one speaker holds the floor "
                      f"({max(a, b):.0%}) — not stacking")
                del splits[start_f]
                strategies[scene_idx] = 'GENERAL'
            elif reliable and active_speaker.CUT_MODE:
                strategies[scene_idx] = 'ALTERNATE'
                alternates[start_f] = (
                    active_speaker.hold(verdicts), splits.pop(start_f))
    if splits:
        print(f"   🪞 SPLIT layout on {len(splits)} scene(s)")
    if alternates:
        print(f"   🎬 Speaker-cut layout on {len(alternates)} scene(s)")

    # SCREENCAST wins over SPLIT on the rare scene that qualifies for both: two
    # faces beside a chart still means the chart is what the shot is about, and
    # stacking the two speakers would crop it away entirely.
    # A screen with a webcam composited into a corner gets its own layout, and
    # the question "is there an inset" is settled geometrically rather than by
    # asking Gemini: offered as a fourth choice it answered "screencast" on all
    # five clips that had one, while camera_inset.detect finds all five with no
    # false positives. The box is fixed for the whole video, so it is found once.
    inset = None
    if content_ranges and screencast_layout.ENABLED:
        try:
            inset = camera_inset.detect(input_video)
        except Exception as e:
            print(f"   ⚠️ Inset check failed ({e}) — using the screen layouts.")
        if inset:
            print(f"   📹 Webcam inset at {inset}")

    screencasts = {}
    wide_count = 0
    inset_count = 0
    if content_ranges:
        for scene_idx, (plan, centre) in screencast_layout.detect_screencast_scenes(
                input_video, scenes, strategies, content_ranges).items():
            # An inset beats both screen plans: it is the only one that can show
            # the screen whole AND the person at a readable size.
            if inset:
                plan, centre = 'INSET', None
            strategies[scene_idx] = plan
            start_f = scene_boundaries[scene_idx][0]
            splits.pop(start_f, None)
            if plan == 'SCREENCAST':
                screencasts[start_f] = centre
            elif plan == 'INSET':
                inset_count += 1
            else:
                wide_count += 1
    if screencasts:
        print(f"   🖥️ SCREENCAST layout on {len(screencasts)} scene(s)")
    if wide_count:
        print(f"   📐 Full-width layout on {wide_count} scene(s)")
    if inset_count:
        print(f"   📹 Camera-inset layout on {inset_count} scene(s)")

    # The crop geometry comes from the SOURCE dims only — SmoothedCameraman
    # derives crop_width/crop_height from video_width/video_height and never
    # reads the output pair. So out_w/out_h being the (possibly upscaled)
    # delivery size doesn't move the camera; only the final scale= uses it.
    cameraman = m.SmoothedCameraman(out_w, out_h, orig_w, orig_h, aspect_ratio=aspect_ratio,fps=fps)
    tracker = m.SpeakerTracker(cooldown_frames=max(1,round(fps)),fps=fps)

    ys = []
    if editing_director.enabled() and not force_strategy:
        preserve=editing_director.context_shots(director_context,
            [(a,b,s) for (a,b),s in zip(scene_boundaries,strategies)],fps)
        for index,(a,_) in enumerate(scene_boundaries):
            if a in preserve:
                strategies[index]='GENERAL';splits.pop(a,None);alternates.pop(a,None);screencasts.pop(a,None)
                _,reason=editing_director.scene_layout_policy(director_context,a,scene_boundaries[index][1],fps)
                director_context['_scene_layout_reasons'][a]=reason
    subjects = {};protected={}
    xs = _analyze_trajectory(input_video, scene_boundaries, strategies, fps,
                             orig_w, orig_h, cameraman, tracker, ys,
                             allow_context=not force_strategy, subject_evidence=subjects,context_evidence=protected)
    if not xs:
        raise RuntimeError("analysis produced no frames")

    # Beats are found once per clip; each scene takes the ones inside it.
    beats = []
    envelope=active_speaker.audio_envelope(input_video,0,len(xs)/fps,window_s=.2) if editing_director.enabled() else []
    if punch_in.ENABLED:
        beats = (punch_in.emphasis_from_envelope(envelope) if editing_director.enabled()
                 else punch_in.emphasis_times(input_video, len(xs) / fps))
        if beats:
            print(f"   🔍 Punch-in on {len(beats)} beat(s)")

    crop_w, crop_h = cameraman.crop_width, cameraman.crop_height

    # ALTERNATE renders through the TRACK path: hard cuts between two speakers
    # are still just a list of crop x values, so no new filtergraph is needed.
    # The trajectory is written here because the analysis pass deliberately
    # skips these scenes rather than tracking a face through them.
    for start_f, (held, centres) in alternates.items():
        end_f = scene_boundaries[split_scene_of[start_f]][1]
        end_f = min(end_f, len(xs))
        if end_f <= start_f:
            continue
        xs[start_f:end_f] = active_speaker.speaker_xs(
            held, centres, crop_w, orig_w, end_f - start_f, fps)

    # Last word on the trajectory: a scene the user framed by hand beats every
    # automatic verdict above, including the ALTERNATE writes.
    if crop_overrides:
        xs, strategies = apply_crop_overrides(
            xs, strategies, scene_boundaries, crop_overrides, crop_w,
            orig_w, orig_h=orig_h, splits=splits)
        print(f"   ✋ Manual framing on {len(crop_overrides)} scene(s)")

    ranges = scene_frame_ranges(scene_boundaries, strategies, len(xs))
    if not ranges:
        raise RuntimeError("no usable scene ranges")
    editorial = (__import__('video_templates').framing_preference() == 'editorial'
                 and aspect_ratio < 0.7 and orig_w / float(orig_h) >= 1.3)
    if editorial and any(strategy == 'GENERAL' for _, _, strategy in ranges):
        print('   🎞️ Editorial wide scenes: detail + full-width context, no blurred margins')
    import editing_director
    if editing_director.enabled():
        focus={s:_scene_focus_x(input_video,s,e,orig_w) for s,e,strategy in ranges
               if strategy=='GENERAL' and editorial}
        plan=editing_director.compile_plan(media=input_video,width=orig_w,height=orig_h,fps=fps,
            out_size=(out_w,out_h),ranges=ranges,xs=xs,ys=ys,crop_size=(crop_w,crop_h),
            splits=splits,screencasts=screencasts,inset=inset,editorial=editorial,focus=focus,
            context=director_context,subjects=subjects,protected=protected,beats=beats,
            audio=editing_director.audio_decision(envelope,len(xs)/fps))
        return render_decisions(input_video,final_output_video,plan)
    workdir = tempfile.mkdtemp(prefix="reframe_v2_")
    segments = []
    framing_shots=[]
    try:
        for idx, (start_f, end_f, strategy) in enumerate(ranges):
            seg_path = os.path.join(workdir, f"seg_{idx:03d}.mp4")
            ss = start_f / fps
            dur = (end_f - start_f) / fps
            shot_keys=[];interpolation='hold'

            if strategy == 'INSET':
                graph = camera_inset.inset_filtergraph(
                    orig_w, orig_h, out_w, out_h, inset)
            elif strategy == 'SCREENCAST':
                graph = screencast_layout.screencast_filtergraph(
                    orig_w, orig_h, out_w, out_h, screencasts[start_f])
            elif strategy == 'WIDE':
                graph = general_filtergraph(
                    out_w, out_h,
                    full_width_content_height(orig_w, orig_h, out_w))
            elif strategy == 'SPLIT':
                left, right = splits[start_f]
                graph = split_layout.split_filtergraph(
                    orig_w, orig_h, out_w, out_h, left, right)
            elif strategy == 'GENERAL':
                if editorial:
                    focus_x = _scene_focus_x(input_video, start_f, end_f, orig_w)
                    graph = editorial_filtergraph(orig_w, orig_h, out_w, out_h,
                                                   focus_x)
                else:
                    graph = general_filtergraph(out_w, out_h,
                                                orig_w=orig_w, orig_h=orig_h)
            else:
                seg_xs = [crop_position(orig_w, orig_h, crop_w, crop_h,
                          finite(x, (orig_w - crop_w) / 2) + crop_w / 2)[0]
                          for x in xs[start_f:end_f]]
                seg_ys = [crop_position(orig_w, orig_h, crop_w, crop_h,
                          cy=finite(y, (orig_h - crop_h) / 2) + crop_h / 2)[1]
                          for y in ys[start_f:end_f]]
                cmd_path = os.path.join(workdir, f"cmd_{idx:03d}.txt")
                if beats and crop_h >= orig_h - 2:
                    zooms = punch_in.zoom_curve(len(seg_xs), fps, beats,
                                                start_offset=ss)
                    boxes = punch_in.crop_boxes(seg_xs, zooms, crop_w, crop_h,
                                                orig_w, orig_h)
                else:
                    boxes=[(crop_w,crop_h,x,y) for x,y in zip(seg_xs,seg_ys)]
                if os.getenv('REFRAME_KEYFRAMES','1')!='0' and strategy!='ALTERNATE':
                    shot_keys=compact_keyframes(boxes,fps);interpolation='linear'
                    boxes=sample_keyframes(shot_keys,fps,dur,orig_w,orig_h)
                else:
                    shot_keys=[dict(time=i/fps,width=float(w),height=float(h),x=float(x),y=float(y))
                        for i,(w,h,x,y) in enumerate(boxes) if i==0 or boxes[i]!=boxes[i-1]]
                lines=punch_in.sendcmd_lines(boxes,fps)
                w,h,x,y=boxes[0];init=f'w={w}:h={h}:x={x}:y={y}'
                with open(cmd_path, "w") as f:
                    f.write("\n".join(lines) + "\n")
                graph = (
                    f"[0:v]sendcmd=f='{escape_filter_value(cmd_path)}',"
                    f"crop@c={init},"
                    f"scale={out_w}:{out_h},setsar=1[v]"
                )

            _run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{ss:.4f}", "-t", f"{dur:.4f}", "-i", input_video,
                "-filter_complex", graph, "-map", "[v]",
                *video_encode_args(QUALITY_FAST), "-an", seg_path,
            ])
            segments.append(seg_path)
            layout='EDITORIAL' if editorial and strategy=='GENERAL' else {'GENERAL':'BLUR','WIDE':'BLUR','ALTERNATE':'TRACK'}.get(strategy,strategy)
            if (layout=='TRACK' and len(shot_keys)==1 and abs(shot_keys[0]['x']-(orig_w-crop_w)/2)<=2
                and abs(shot_keys[0]['y']-(orig_h-crop_h)/2)<=2):layout='CENTER'
            framing_shots.append(dict(start=ss,end=ss+dur,layout=layout,renderer=strategy,
                interpolation=interpolation,keyframes=shot_keys))

        list_path = os.path.join(workdir, "concat.txt")
        with open(list_path, "w") as f:
            f.write(concat_list_content(segments))

        # Concat video segments (stream copy) + audio straight from the clip.
        _run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-i", input_video,
            "-map", "0:v:0", "-map", "1:a:0?",
            "-c:v", "copy", "-c:a", "copy", *METADATA_SCRUB,
            # +faststart moves the moov atom to the front so the browser <video>
            # can start playing before the whole file downloads. Without it the
            # in-app preview spins forever (download still works) — the moov
            # lands at the end of a plain concat.
            "-movflags", "+faststart",
            final_output_video,
        ])
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    # Tell the caption pass which stretches are stacked (see layout_ranges).
    layout_ranges.write(final_output_video,
                        [(s / fps, e / fps,
                          'EDITORIAL' if editorial and strategy == 'GENERAL' else strategy)
                         for s, e, strategy in ranges], source_size=(orig_w,orig_h), output_size=(out_w,out_h))
    from story_director import atomic_json
    atomic_json(str(final_output_video)+'.framing.json',dict(version=1,width=orig_w,height=orig_h,
        output_width=out_w,output_height=out_h,fps=fps,shots=framing_shots))
    print(f"   ✅ Clip saved to {final_output_video}")
    return True


def director_encoder(width,height):
    # Small previews can be below NVENC's minimum frame dimensions.
    if min(width,height)<160:
        from ffmpeg_utils import cpu_encoding
        with cpu_encoding():return video_encode_args(QUALITY_FAST)
    return video_encode_args(QUALITY_FAST)


def render_decisions(input_video, final_output_video, decisions, size=None, runner=None):
    """Replay validated v2 decisions for preview/final; never invoke detectors/AI."""
    import editing_director
    import export_quality
    plan=editing_director.EditPlan.model_validate(decisions).model_dump(mode='json')
    info=export_quality.probe(input_video);video,audio=export_quality.streams(info)
    if not video or (video['width'],video['height'])!=(plan['width'],plan['height']):
        raise ValueError('Prepared source dimensions differ from the edit plan.')
    actual=export_quality.number(info.get('format',{}).get('duration'))
    if actual is None or abs(actual-plan['duration'])>max(.12,2/plan['fps']):
        raise ValueError('Prepared source duration differs from the edit plan.')
    out_w,out_h=size or (plan['output_width'],plan['output_height'])
    if (not all(type(v) is int and 2<=v<=8192 and v%2==0 for v in (out_w,out_h))
            or abs(out_w/out_h-plan['output_width']/plan['output_height'])>.015):
        raise ValueError('Preview must retain the validated output aspect ratio.')
    execute=runner or _run
    with tempfile.TemporaryDirectory(prefix='director_') as work:
        parts=[]
        for i,shot in enumerate(plan['shots']):
            part=os.path.join(work,f'seg_{i:04d}.mp4');native=shot['renderer']
            ow,oh=plan['width'],plan['height']
            if native in ('GENERAL','WIDE'):
                graph=contain_background(out_w,out_h)
            elif native=='EDITORIAL':
                graph=editorial_filtergraph(ow,oh,out_w,out_h,shot['focus_x'])
            elif native in ('SPLIT','SCREENCAST'):
                top_h=(out_h//2)//2*2 if native=='SPLIT' else screencast_layout.content_bands(ow,oh,out_w,out_h)[0]
                bottom_h=out_h-top_h
                top,bottom=shot['regions']
                def region_filter(box,label,w,h):
                    return f"[{label}]crop={box['width']}:{box['height']}:{box['x']}:{box['y']},scale={w}:{h},setsar=1"
                graph=('[0:v]split=2[a][b];'+region_filter(top,'a',out_w,top_h)+'[top];'+
                       region_filter(bottom,'b',out_w,bottom_h)+'[bottom];[top][bottom]vstack=inputs=2,setsar=1[v]')
            elif native=='INSET':
                box=shot['regions'][0]
                graph=camera_inset.inset_filtergraph(ow,oh,out_w,out_h,[int(box[k]) for k in ('x','y','width','height')])
            else:
                commands=[]
                keys=shot['keyframes']
                if shot['interpolation']=='linear':
                    boxes=sample_keyframes(keys,plan['fps'],shot['end']-shot['start'],ow,oh)
                    commands=punch_in.sendcmd_lines(boxes,plan['fps'])
                for key in keys if shot['interpolation']=='hold' else []:
                    for axis,field in [('w','width'),('h','height'),('x','x'),('y','y')]:
                        commands.append(f"{key['time']:.6f} crop@c {axis} {key[field]:g};")
                cmd_path=os.path.join(work,f'crop_{i}.txt')
                with open(cmd_path,'w') as handle:handle.write('\n'.join(commands)+'\n')
                key=shot['keyframes'][0]
                graph=(f"[0:v]sendcmd=f='{escape_filter_value(cmd_path)}',"
                       f"crop@c=w={key['width']}:h={key['height']}:x={key['x']}:y={key['y']},"
                       f"scale={out_w}:{out_h},setsar=1[v]")
            execute(['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_complex_threads','1',
                     '-ss',str(shot['start']),'-t',str(shot['end']-shot['start']),'-i',input_video,
                     '-filter_complex',graph,'-map','[v]','-r',str(plan['fps']),
                     *director_encoder(out_w,out_h),'-pix_fmt','yuv420p','-an',part])
            parts.append(part)
        listing=os.path.join(work,'concat.txt')
        with open(listing,'w') as handle:handle.write(concat_list_content(parts))
        execute(['ffmpeg','-y','-v','error','-nostdin','-f','concat','-safe','0','-i',listing,
                 '-i',input_video,'-map','0:v:0','-map','1:a:0?','-c:v','copy','-c:a','aac',
                 '-af',f"volume={plan['audio']['gain_db']}dB",'-t',str(plan['duration']),
                 *METADATA_SCRUB,'-movflags','+faststart',final_output_video])
    layout_ranges.write(final_output_video,[(s['start'],s['end'],s['layout']) for s in plan['shots']], source_size=(plan['width'],plan['height']), output_size=(out_w,out_h))
    editing_director.save(final_output_video,plan)
    return True
