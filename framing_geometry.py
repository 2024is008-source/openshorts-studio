"""Shared, bounded crop geometry. No detection or pixel-colour heuristics."""
import math
import os


def finite(value, default):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def validate_source(width, height, aspect=9 / 16):
    if (not all(math.isfinite(float(v)) for v in (width, height, aspect))
            or width < 2 or height < 2 or aspect <= 0):
        raise ValueError('source dimensions must be at least 2 and aspect must be positive')


def crop_size(width, height, aspect, tightness=1):
    """Largest even crop that fits, optionally tightened around a subject."""
    validate_source(width, height, aspect)
    h = min(height, width / aspect) * max(.3, min(finite(tightness, 1), 1))
    w = min(width, h * aspect)
    return max(2, int(w) // 2 * 2), max(2, int(h) // 2 * 2)


def crop_position(width, height, crop_w, crop_h, cx=None, cy=None):
    """Clamp finite source-pixel centres to even in-bounds offsets."""
    validate_source(width, height)
    if (not all(math.isfinite(float(v)) for v in (crop_w, crop_h))
            or not 2 <= crop_w <= width or not 2 <= crop_h <= height):
        raise ValueError('crop dimensions must fit inside the source')
    cx = finite(cx, width / 2)
    cy = finite(cy, height / 2)
    x = max(0, min(int(round(cx - crop_w / 2)), width - crop_w))
    y = max(0, min(int(round(cy - crop_h / 2)), height - crop_h))
    return x // 2 * 2, y // 2 * 2


def subject_position(width, height, crop_w, crop_h, centre):
    """Place a face in the upper third, retaining the whole head when possible.

    Size-bearing face centres use headroom constraints. Manual (x, y) centres
    retain the historical 42% anchor and are bounded the same way.
    """
    cx, cy = finite(centre[0], width / 2), finite(centre[1], height / 2)
    anchor = .34 if len(centre) >= 4 else .42
    x, y = crop_position(width, height, crop_w, crop_h, cx,
                         cy + crop_h * (.5 - anchor))
    if len(centre) >= 4:
        face_h = max(0, finite(centre[3], 0))
        if face_h <= crop_h:
            # Keep a modest margin above the head without pushing the chin out.
            low = max(0, cy + face_h / 2 - crop_h)
            high = min(height - crop_h, cy - face_h * .65)
            if low <= high:
                y = int(max(low, min(y, high))) // 2 * 2
    return x, y


def caption_safe_ratio():
    """Bottom UI/caption reserve; applied to text, never to a subject crop."""
    return max(.05, min(finite(os.getenv('CAPTION_SAFE_BOTTOM_RATIO'), .20), .35))


def needs_context(candidates, width, height, aspect=9/16):
    """A crop must not discard another primary face or slice a close-up.

    Ignore small extras relative to the largest face; this uses only detections
    already sampled by the scene classifier, not another model call.
    """
    if not candidates:
        return False
    boxes = [c['box'] for c in candidates]
    largest = max(w*h for _, _, w, h in boxes)
    primary = [(x,y,w,h) for x,y,w,h in boxes
               if w >= width*.045 and w*h >= largest*.35]
    if not primary:
        return False
    crop_w, crop_h = crop_size(width, height, aspect)
    span_x = max(x+w for x,y,w,h in primary) - min(x for x,y,w,h in primary)
    span_y = max(y+h for x,y,w,h in primary) - min(y for x,y,w,h in primary)
    return span_x > crop_w*.95 or span_y > crop_h*.95


def blur_strength():
    """1080px reference sigma, bounded even for malformed local settings."""
    return max(12., min(96., finite(os.getenv('REFRAME_BLUR_STRENGTH'), 64.)))


def background_soften(out_w, out_h):
    # Blur a small texture for a stronger, inexpensive backdrop. Foreground
    # is on a separate branch, so text, faces and intentional dark content stay.
    w=max(2,round(out_w/16)*2); h=max(2,round(out_h/16)*2)
    sigma=max(1.,blur_strength()*w/1080)
    return (f'scale={w}:{h},gblur=sigma={sigma:.3f}:steps=2,'
            f'scale={out_w}:{out_h},eq=brightness=-0.06:saturation=0.7')


def contain_background(out_w, out_h, source='0:v', output='v', prefix='bed'):
    """Preserve the entire image over a cover-scaled blurred duplicate.

    Explicit cover/contain scaling handles landscape, square and tall inputs.
    Every output pixel comes from the source; intentional dark content remains.
    """
    return (
        f'[{source}]split=2[{prefix}a][{prefix}b];'
        f'[{prefix}a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,'
        f'crop={out_w}:{out_h},setsar=1,{background_soften(out_w,out_h)}[{prefix}bg];'
        f'[{prefix}b]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:'
        f'force_divisible_by=2,setsar=1[{prefix}fg];'
        f'[{prefix}bg][{prefix}fg]overlay=x=(W-w)/2:y=(H-h)/2,'
        f'setsar=1[{output}]'
    )


def compact_keyframes(boxes, fps, tolerance=2.):
    """Bounded-error linear source-pixel paths, reset independently per shot.

    Analysis samples are already temporally smoothed. Simplify at most one
    second at a time, preserving turns/stops without quadratic whole-clip work.
    Preview and export interpolate these same decisions; neither redetects faces.
    """
    if not math.isfinite(fps) or fps<=0:raise ValueError('A positive frame rate is required.')
    if not boxes:return []
    def key(index):
        w,h,x,y=boxes[index]
        return dict(time=round(index/fps,6),x=float(x),y=float(y),width=float(w),height=float(h))
    if all(box==boxes[0] for box in boxes):return [key(0)]
    keep={0,len(boxes)-1};step=max(1,round(fps));tolerance=max(0.,finite(tolerance,2.))
    for first in range(0,len(boxes)-1,step):
        last=min(len(boxes)-1,first+step);keep.update((first,last));pending=[(first,last)]
        while pending:
            a,b=pending.pop()
            error=0.;worst=None
            for i in range(a+1,b):
                p=(i-a)/(b-a)
                distance=max(abs(boxes[i][axis]-(boxes[a][axis]*(1-p)+boxes[b][axis]*p)) for axis in range(4))
                if distance>error:error,worst=distance,i
            if worst is not None and error>tolerance:
                keep.add(worst);pending.extend(((a,worst),(worst,b)))
    return [key(i) for i in sorted(keep)]


def sample_keyframes(keys, fps, duration, width, height, interpolation='linear'):
    """Reconstruct bounded even crop commands from a timestamped shot path."""
    if not keys or not math.isfinite(fps) or fps<=0 or not 0<duration<=1800:
        raise ValueError('A valid shot path, duration and frame rate are required.')
    result=[];index=0
    for frame in range(math.ceil(duration*fps-1e-6)):
        t=frame/fps
        while index+1<len(keys) and keys[index+1]['time']<=t+1e-6:index+=1
        a=keys[index];b=keys[min(index+1,len(keys)-1)]
        p=(max(0,min(1,(t-a['time'])/(b['time']-a['time']))) if b['time']>a['time'] and interpolation=='linear' else 0.)
        values={name:a[name]*(1-p)+b[name]*p for name in ('width','height','x','y')}
        w=max(2,min(width//2*2,int(round(values['width']/2))*2));h=max(2,min(height//2*2,int(round(values['height']/2))*2))
        x,y=crop_position(width,height,w,h,values['x']+w/2,values['y']+h/2)
        result.append((w,h,x,y))
    return result


def associate_faces(candidates, known, frame, width, next_id, ttl=30):
    """One-to-one, two-dimensional local identity matching (not recognition).

    Motion prediction survives short occlusions/crossings. Geometry establishes
    continuity only; it cannot identify a person or establish who is speaking.
    """
    faces=[]
    for candidate in candidates:
        try:
            x,y,w,h=map(float,candidate['box'])
            if not all(math.isfinite(v) for v in (x,y,w,h)) or w<=0 or h<=0:continue
            faces.append(dict(box=[x,y,w,h],score=max(0.,finite(candidate.get('score'),w*h))))
        except (KeyError,TypeError,ValueError):continue
    known=[k for k in known if 0<=frame-k['last_frame']<=ttl]
    pairs=[]
    for i,face in enumerate(faces):
        x,y,w,h=face['box'];cx,cy=x+w/2,y+h/2
        for old in known:
            dt=max(1,frame-old['last_frame'])
            px=old['center']+old.get('vx',0)*min(dt,ttl*.4)
            py=old.get('cy',cy)+old.get('vy',0)*min(dt,ttl*.4)
            distance=math.hypot(cx-px,cy-py)
            ratio=max(w*h,old.get('area',w*h))/max(1,min(w*h,old.get('area',w*h)))
            if distance<width*.15 and ratio<=3:
                pairs.append((distance/width+abs(math.log(ratio))*.025,old['id'],i,old))
    assigned={};used=set()
    for _,pid,i,old in sorted(pairs,key=lambda p:p[:3]):
        if i not in assigned and pid not in used:assigned[i]=old;used.add(pid)
    current=[];updated=[k for k in known if k['id'] not in used]
    for i,face in enumerate(faces):
        x,y,w,h=face['box'];cx,cy=x+w/2,y+h/2;old=assigned.get(i)
        pid=old['id'] if old else next_id
        if old is None:next_id+=1
        dt=max(1,frame-old['last_frame']) if old else 1
        vx=(cx-old['center'])/dt if old else 0.;vy=(cy-old.get('cy',cy))/dt if old else 0.
        updated.append(dict(id=pid,center=cx,cy=cy,area=w*h,last_frame=frame,
            vx=max(-width*.15,min(width*.15,vx)),vy=max(-width*.15,min(width*.15,vy))))
        current.append(dict(face,id=pid))
    return current,updated,next_id


def retain_regions(rows, boxes, limit=32):
    """Keep bounded evidence; merge late detections instead of forgetting them."""
    for box in boxes:
        if len(rows)<limit:rows.append(list(box));continue
        x,y,w,h=rows[-1];bx,by,bw,bh=box
        left,top=min(x,bx),min(y,by)
        rows[-1]=[left,top,max(x+w,bx+bw)-left,max(y+h,by+bh)-top]
