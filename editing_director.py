"""Typed decisions at the existing v2 analysis/render boundary. No AI requests."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

import caption_timing
import framing_geometry as geometry

VERSION = 1
KINDS = ('challenge', 'emotional', 'comedy', 'podcast', 'educational', 'general')
POLICIES = {
    'challenge': ('bold-creator', 'Preserve the challenge, visible action and result; keep source order.'),
    'emotional': ('cinematic', 'Hold reactions and the final spoken thought; do not shorten emotional pauses.'),
    'comedy': ('dynamic-highlight', 'Keep setup and reaction together; preserve the source punchline timing.'),
    'podcast': ('podcast', 'Prefer stable speaker framing; split only with grounded scene evidence and independent views.'),
    'educational': ('clean-minimal', 'Preserve demonstrations, objects and readable full-frame context.'),
    'general': ('clean-minimal', 'Keep natural cuts and complete available speech; preserve uncertain visual context.'),
}


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, strict=True)


class Region(Decision):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Keyframe(Region):
    time: float = Field(ge=0)


class Segment(Decision):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class Shot(Decision):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    segment_index: int = Field(ge=0)
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    layout: Literal['TRACK','CENTER','BLUR','SPLIT','EDITORIAL']
    renderer: Literal['TRACK','GENERAL','SPLIT','EDITORIAL','WIDE','SCREENCAST','INSET']
    keyframes: list[Keyframe] = Field(default_factory=list,max_length=108000)
    interpolation: Literal['hold','linear'] = 'hold'
    regions: list[Region] = Field(default_factory=list,max_length=2)
    faces: list[Region] = Field(default_factory=list,max_length=32)
    protected_regions: list[Region] = Field(default_factory=list,max_length=32)
    focus_x: float | None = Field(default=None,ge=0)
    caption_position: Literal['top','middle','bottom'] = 'bottom'
    reason: str = Field(max_length=500)


class Caption(Decision):
    text: str = Field(min_length=1,max_length=2000)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    segment_index: int = Field(ge=0)
    aligned: bool


class Hook(Decision):
    text: str = Field(max_length=300)
    start: float = 0.0
    end: float = Field(ge=0)
    evidence: Literal['opening_source_quote','disabled','unavailable']
    enabled: bool = False
    style: Literal['classic','dark','yellow','red','outline','outline_yellow'] = 'outline'
    animation: Literal['none','fade','scale-pop','slide-up','spring','highlight-reveal'] = 'fade'
    y: float | None = Field(default=None,ge=.04,le=.26)
    kind: Literal['challenge','curiosity','emotional','question','fact','funny'] = 'curiosity'


class Audio(Decision):
    continuous_source_audio: bool = False
    available: bool = False
    window_seconds: float = Field(default=.2,gt=0)
    energy: list[float] = Field(default_factory=list,max_length=10000)
    quiet_intervals: list[list[float]] = Field(default_factory=list,max_length=10000)
    gain_db: float = Field(default=0,ge=-12,le=6)
    note: str = 'Relative energy only; quiet is not proof of unwanted silence. Original audio retained.'


class EditPlan(Decision):
    version: Literal[1] = 1
    source_ref: str = Field(min_length=1,max_length=255)
    source_identity: dict
    width: int = Field(ge=2,le=16384)
    height: int = Field(ge=2,le=16384)
    source_duration: float = Field(gt=0)
    duration: float = Field(gt=0,le=1800)
    fps: float = Field(gt=0,le=240)
    output_width: int = Field(ge=2,le=8192)
    output_height: int = Field(ge=2,le=8192)
    kind: Literal['challenge','emotional','comedy','podcast','educational','general']
    strategy: str
    segments: list[Segment] = Field(min_length=1,max_length=12)
    shots: list[Shot] = Field(min_length=1,max_length=2000)
    captions: list[Caption] = Field(default_factory=list,max_length=12000)
    caption_preset: Literal['clean-minimal','bold-creator','dynamic-highlight','podcast','cinematic','openshorts-dynamic','creator-bold','clean-podcast','minimal','green-pop','teal-reveal','paper-focus']
    captions_enabled: bool = True
    hook: Hook
    audio: Audio
    transitions: list = Field(default_factory=list,max_length=0)
    ending: dict
    evidence: dict
    auto_edit: dict | None = None

    @model_validator(mode='after')
    def validate_timeline(self):
        if self.auto_edit is not None:
            import auto_edit
            self.auto_edit=auto_edit.normalize(self.auto_edit,self.duration)
        if Path(self.source_ref).name!=self.source_ref or any(c in self.source_ref for c in '/\\:') or self.source_ref in ('.','..'):
            raise ValueError('source_ref must be a local basename, never a path.')
        if self.output_width%2 or self.output_height%2:raise ValueError('Output dimensions must be even.')
        cursor=0.0
        for seg in self.segments:
            if not (seg.source_start<seg.source_end<=self.source_duration+.001 and
                    abs(seg.start-cursor)<.002 and abs(seg.end-seg.start-(seg.source_end-seg.source_start))<.002):
                raise ValueError('Selected segments must be valid, contiguous and traceable to source.')
            cursor=seg.end
        if abs(cursor-self.duration)>.11:raise ValueError('Selected segments do not cover the clip.')
        cursor=0.0
        for shot in self.shots:
            if shot.segment_index>=len(self.segments):raise ValueError('Shot refers to a missing segment.')
            seg=self.segments[shot.segment_index]
            if not (abs(shot.start-cursor)<.002 and shot.start<shot.end<=seg.end+.001 and shot.start>=seg.start-.002):
                raise ValueError('Shot boundaries must cover the timeline without gaps or cross-source cuts.')
            if abs(shot.source_start-(seg.source_start+shot.start-seg.start))>.002 or abs(shot.source_end-(seg.source_start+shot.end-seg.start))>.002:
                raise ValueError('Shot source timestamps do not match selected footage.')
            if shot.source_end>self.source_duration+.001:raise ValueError('Shot extends past source.')
            capabilities={'TRACK':{'TRACK','CENTER'},'GENERAL':{'BLUR'},'WIDE':{'BLUR'},
                          'SPLIT':{'SPLIT'},'EDITORIAL':{'EDITORIAL'},'SCREENCAST':{'EDITORIAL'},'INSET':{'EDITORIAL'}}
            if shot.layout not in capabilities[shot.renderer]:raise ValueError('Layout is incompatible with renderer.')
            if shot.renderer=='TRACK' and not shot.keyframes:raise ValueError('Crop layout needs crop keyframes.')
            if shot.layout=='CENTER' and len(shot.keyframes)!=1:raise ValueError('Center crop must be static within its shot.')
            if shot.renderer in ('SPLIT','SCREENCAST') and len(shot.regions)!=2:raise ValueError('Two-region composition needs two independent regions.')
            if shot.renderer=='SPLIT' and shot.regions[0]==shot.regions[1]:raise ValueError('Split regions must be independent.')
            if shot.renderer=='INSET' and len(shot.regions)!=1:raise ValueError('Inset composition needs one validated source region.')
            previous=-1
            for key in shot.keyframes:
                if key.width<2 or key.height<2:raise ValueError('Crop dimensions must be at least two source pixels.')
                if not 0<=key.time<shot.end-shot.start+.00001 or key.time<=previous:raise ValueError('Keyframes must be ordered within their own shot.')
                previous=key.time
            if shot.keyframes and shot.keyframes[0].time!=0:raise ValueError('Every shot resets its crop at time zero.')
            for box in [*shot.keyframes,*shot.regions,*shot.faces,*shot.protected_regions]:
                if box.x+box.width>self.width+.001 or box.y+box.height>self.height+.001:raise ValueError('Crop/subject regions exceed source dimensions.')
            if shot.focus_x is not None and shot.focus_x>self.width:raise ValueError('Focus exceeds source dimensions.')
            cursor=shot.end
        if abs(cursor-self.duration)>.002:raise ValueError('Shot coverage is incomplete.')
        for caption in self.captions:
            if caption.segment_index>=len(self.segments):raise ValueError('Caption refers to missing source segment.')
            seg=self.segments[caption.segment_index]
            if not (seg.start<=caption.start<caption.end<=min(seg.end,self.duration)+.001):raise ValueError('Invalid caption timing.')
            if abs(caption.source_start-(seg.source_start+caption.start-seg.start))>.002 or abs(caption.source_end-(seg.source_start+caption.end-seg.start))>.002:
                raise ValueError('Caption lost source alignment.')
        if self.hook.start!=0 or self.hook.end>self.duration or (self.hook.enabled and (not self.hook.text or self.hook.end<=0 or self.hook.evidence!='opening_source_quote')):
            raise ValueError('Unsupported or ungrounded hook.')
        if self.hook.text:
            opening=' '.join(c.text.strip() for c in self.captions if c.start<3)
            if self.hook.text not in opening:raise ValueError('Headline must quote retained opening speech.')
        if any(not 0<=v<=1 or not math.isfinite(v) for v in self.audio.energy):raise ValueError('Invalid audio energy.')
        for interval in self.audio.quiet_intervals:
            if len(interval)!=2 or not 0<=interval[0]<interval[1]<=self.duration+.001:raise ValueError('Invalid quiet interval.')
        if self.ending.get('end')!=self.duration or self.ending.get('action')!='preserve':raise ValueError('Ending must preserve the selected source conclusion.')
        return self


def enabled():return os.getenv('EDIT_DIRECTOR','0')=='1'


def identity(path):
    stat=os.stat(path)
    return dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)


def selected_category(context):
    import category_intelligence as ci
    requested=os.getenv('AMCE_CATEGORY','auto')
    if requested!='auto':
        try:return ci.selection(requested,{})
        except ValueError:return None
    value=((context or {}).get('analysis') or {}).get('category_selection')
    if value:
        try:ci.resolve(value['primary_category'],value.get('subcategory','auto'));return value
        except (ValueError,KeyError,TypeError):return None
    return None


def kind_for(context):
    requested=os.getenv('EDIT_DIRECTOR_STRATEGY','auto')
    if requested in KINDS:return requested,'configured'
    chosen=selected_category(context)
    if chosen:
        cat,sub=chosen['primary_category'],chosen.get('subcategory','auto')
        kind='challenge' if cat=='challenge' else 'educational' if (cat,sub)==('podcast','education') else 'comedy' if (cat,sub)==('podcast','comedy') else 'podcast' if cat=='podcast' else 'general'
        return kind,'selected_category'
    moments=(context.get('analysis') or {}).get('moments') or []
    votes=[m.get('editing_kind') for m in moments if isinstance(m,dict) and m.get('editing_kind') in KINDS
           and overlaps_context(m,context)]
    return (max(KINDS,key=lambda k:votes.count(k)),'retained_video_analysis') if votes else ('general','safe_default')


def overlaps_context(moment,context):
    try:
        a,b=float(moment['start']),float(moment['end'])
        return math.isfinite(a) and math.isfinite(b) and a>=0 and b>a and any(
            min(b,s['end'])>max(a,s['start']) for s in context.get('segments',[dict(start=0,end=1e12)]))
    except (ValueError,TypeError,KeyError):return False


def scene_layout_policy(context,start_frame,end_frame,fps):
    """Map retained visual-layout evidence to an assembled scene, without AI calls.

    Preserve requirements win conflicts. A split needs explicit visual evidence
    covering most of this scene; a genre, transcript keyword or two faces is not
    evidence that two panels help the viewer.
    """
    chosen=selected_category(context)
    if chosen and chosen['primary_category']=='sports_highlights':
        return 'preserve_scene','Sports category safety policy: ball/player tracking is unavailable; preserve the field and action context.'
    duration=max(0.,(end_frame-start_frame)/fps)
    if not duration:return 'uncertain','No usable scene duration.'
    segments=source_segments(context or {},end_frame/fps)
    intervals=[];reasons=[]
    analysis=(context or {}).get('analysis') or {}
    shot_observations=analysis.get('scene_observations') or []
    moments=shot_observations or analysis.get('moments') or []
    for segment in segments:
        lo=max(start_frame/fps,segment['start']);hi=min(end_frame/fps,segment['end'])
        if hi<=lo:continue
        a=segment['source_start']+lo-segment['start'];b=segment['source_start']+hi-segment['start']
        for moment in moments:
            if not isinstance(moment,dict):continue
            try:
                observed_start=float(moment.get('layout_source_start',moment['start']))
                observed_end=float(moment.get('layout_source_end',moment['end']))
            except (KeyError,TypeError,ValueError):continue
            if not math.isfinite(observed_start) or not math.isfinite(observed_end):continue
            left=max(a,observed_start);right=min(b,observed_end)
            if right<=left:continue
            if shot_observations and right-left<(b-a)*.5:continue
            evidence=moment.get('layout_evidence') or moment.get('visual_evidence')
            if not isinstance(evidence,str) or not evidence.strip():continue
            intent=moment.get('layout_intent','uncertain')
            if moment.get('preserve_context') is True or intent in ('preserve_scene','demonstration'):
                return 'preserve_scene','Retained visual evidence requires shared scene context: '+evidence[:350]
            if intent=='single_subject':
                return 'uncertain','Retained visual evidence favors one subject rather than two panels: '+evidence[:350]
            if intent=='two_speaker_split':
                offset=segment['start']-segment['source_start']
                intervals.append((left+offset,right+offset));reasons.append(evidence)
    end=-1.;covered=0.
    for a,b in sorted(intervals):
        covered+=max(0.,b-max(a,end));end=max(end,b)
    if covered>=duration*.8:
        return 'two_speaker_split','Retained visual evidence supports independent speaker views: '+reasons[0][:350]
    return 'uncertain','No sufficient retained scene evidence for a split; preserve the shared scene.'


def context_shots(context,ranges,fps):
    """Map only explicit inspected full-frame requirements onto local shots."""
    if not context:return set()
    chosen=selected_category(context)
    if chosen and chosen['primary_category']=='sports_highlights':return {row[0] for row in ranges}
    if (context.get('analysis') or {}).get('scene_observations'):
        return {a for a,b,_ in ranges if scene_layout_policy(context,a,b,fps)[0]=='preserve_scene'}
    segments=source_segments(context,max(e for _,e,_ in ranges)/fps)
    moments=(context.get('analysis') or {}).get('moments') or []
    preserve=set()
    for a,b,_ in ranges:
        for seg in segments:
            lo=max(a/fps,seg['start']);hi=min(b/fps,seg['end'])
            if hi<=lo:continue
            local=dict(segments=[dict(start=seg['source_start']+lo-seg['start'],end=seg['source_start']+hi-seg['start'])])
            if any(isinstance(m,dict) and (m.get('preserve_context') is True or m.get('layout_intent') in ('preserve_scene','demonstration')) and (m.get('layout_evidence') or m.get('visual_evidence')) and overlaps_context(m,local) for m in moments):
                preserve.add(a)
    return preserve


def source_segments(context,duration):
    rows=context.get('segments') or [dict(start=0,end=duration)]
    output=[];offset=0.0
    for row in rows:
        a,b=round(float(row['start']),6),round(float(row['end']),6)
        end=round(offset+b-a,6)
        output.append(dict(source_start=a,source_end=b,start=offset,end=end));offset=end
    return output


def captions_for(context,segments):
    output=[]
    for index,seg in enumerate(segments):
        words=caption_timing.relative_words(context.get('transcript') or {},seg['source_start'],seg['source_end'])
        for w in words:
            output.append(dict(text=w['word'],start=round(seg['start']+w['start'],4),end=round(seg['start']+w['end'],4),
                source_start=round(seg['source_start']+w['start'],4),source_end=round(seg['source_start']+w['end'],4),
                segment_index=index,aligned=w['aligned']))
    return output


def audio_decision(envelope,duration,window=.2):
    values=[float(v) for v in envelope if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1]
    quiet=[];start=None
    for i,v in enumerate(values+[1]):
        if v<.015 and start is None:start=i*window
        elif v>=.015 and start is not None:
            end=min(duration,i*window)
            if end-start>=.6:quiet.append([round(start,4),round(end,4)])
            start=None
    return dict(available=bool(values),energy=values,quiet_intervals=quiet,window_seconds=window,gain_db=0.0)


def compile_plan(*,media,width,height,fps,out_size,ranges,xs,ys,crop_size,splits=None,
                 screencasts=None,inset=None,editorial=False,focus=None,context=None,subjects=None,protected=None,beats=(),audio=None):
    """Freeze actual detector results; renderers may not make fresh decisions."""
    import split_layout
    import screencast_layout
    import punch_in
    context=context or {};splits=splits or {};screencasts=screencasts or {};focus=focus or {};subjects=subjects or {};protected=protected or {}
    audio={**(audio or audio_decision([],len(xs)/fps)),
        'continuous_source_audio':bool(context.get('pacing_audio_continuity'))}
    duration=len(xs)/fps;segments=source_segments(context,duration)
    kind,kind_evidence=kind_for(context);preset,policy=POLICIES[kind]
    configured=os.getenv('CAPTION_PRESET')
    import caption_renderer
    if configured=='classic':preset='bold-creator'
    if configured in caption_renderer.PRESETS:preset=configured
    captions=captions_for(context,segments);shots=[];cw,ch=crop_size
    joins=[s['end'] for s in segments[:-1]]
    def logical_time(frame):
        value=frame/fps
        return next((t for t in joins if abs(t-value)<=.51/fps),value)
    for a,b,native in ranges:
        # Split at every EDL join, even when shot detection found no visual cut.
        for si,segment in enumerate(segments):
            start=max(logical_time(a),segment['start']);end=min(logical_time(b),segment['end'],duration)
            if end-start<1e-5:continue
            first=max(a,round(start*fps));last=min(b,round(end*fps));renderer=native
            if renderer=='ALTERNATE':renderer='TRACK'
            # Detail + context duplicates source imagery; require an explicit layout
            # choice, never infer it from a story genre or a missing subject.
            if renderer=='GENERAL' and editorial and width/height>=1.3:
                renderer='EDITORIAL'
            layout={'GENERAL':'BLUR','WIDE':'BLUR','SPLIT':'SPLIT','SCREENCAST':'EDITORIAL','INSET':'EDITORIAL','EDITORIAL':'EDITORIAL'}.get(renderer,'TRACK')
            regions=[];keys=[];interpolation='hold'
            if renderer=='TRACK':
                px=[geometry.crop_position(width,height,cw,ch,geometry.finite(x,(width-cw)/2)+cw/2)[0] for x in xs[first:last]]
                py=[geometry.crop_position(width,height,cw,ch,cy=geometry.finite(y,(height-ch)/2)+ch/2)[1] for y in ys[first:last]]
                if not px:px=[geometry.crop_position(width,height,cw,ch)[0]];py=[geometry.crop_position(width,height,cw,ch)[1]]
                boxes=punch_in.crop_boxes(px,punch_in.zoom_curve(len(px),fps,beats,start_offset=start),cw,ch,width,height) if beats and ch>=height-2 else [(cw,ch,x,y) for x,y in zip(px,py)]
                previous=None
                for frame,box in enumerate(boxes):
                    if box==previous:continue
                    w,h,x,y=box;previous=box
                    keys.append(dict(time=round(frame/fps,6),x=float(x),y=float(y),width=float(w),height=float(h)))
                if os.getenv('REFRAME_KEYFRAMES','1')!='0' and native!='ALTERNATE':
                    keys=geometry.compact_keyframes(boxes,fps);interpolation='linear'
                if len(keys)==1 and abs(keys[0]['x']-(width-cw)/2)<=2 and abs(keys[0]['y']-(height-ch)/2)<=2:layout='CENTER'
            elif renderer=='SPLIT':
                for centre in splits[a]:
                    w,h,x,y,_=split_layout.split_geometry(width,height,*out_size,centre)
                    regions.append(dict(x=float(x),y=float(y),width=float(w),height=float(h)))
            elif renderer=='SCREENCAST':
                # Save complete native geometry as two explicit source regions.
                _,speaker_h=screencast_layout.content_bands(width,height,*out_size)
                sw,sh,sx,sy=width,height,0,0
                fw,fh,fx,fy=screencast_layout.speaker_crop(width,height,out_size[0],speaker_h,screencasts[a])
                regions=[dict(x=float(sx),y=float(sy),width=float(sw),height=float(sh)),dict(x=float(fx),y=float(fy),width=float(fw),height=float(fh))]
            elif renderer=='INSET':
                x,y,w,h=inset;regions=[dict(x=float(x),y=float(y),width=float(w),height=float(h))]
            detected=[]
            face_boxes=subjects.get(a,[])
            if renderer=='SPLIT' and not face_boxes:
                face_boxes=[split_layout.as_box(c) for c in splits[a] if len(c)>=4]
            for box in face_boxes[:32]:
                x,y,w,h=box;x=max(0,min(width-1,x));y=max(0,min(height-1,y))
                detected.append(dict(x=float(x),y=float(y),width=float(max(1,min(w,width-x))),height=float(max(1,min(h,height-y)))))
            occupied=[]
            for x,y,w,h in protected.get(a,[])[:32]:
                x=max(0,min(width-1,x));y=max(0,min(height-1,y))
                occupied.append(dict(x=float(x),y=float(y),width=float(max(1,min(w,width-x))),height=float(max(1,min(h,height-y)))))
            shots.append(dict(start=start,end=end,segment_index=si,
                source_start=segment['source_start']+start-segment['start'],source_end=segment['source_start']+end-segment['start'],
                layout=layout,renderer=renderer,keyframes=keys,interpolation=interpolation,regions=regions,faces=detected,protected_regions=occupied,
                focus_x=float(focus.get(a,width/2)) if renderer=='EDITORIAL' else None,
                caption_position='middle' if layout in ('SPLIT','EDITORIAL') else 'bottom',
                reason=(context.get('_scene_layout_reasons',{}).get(a) or ('Existing scene/subject analysis; context is preserved when a subject crop is unsafe.' if layout in ('BLUR','EDITORIAL') else 'Existing bounded tracking or simultaneous-subject evidence; reset at this shot boundary.'))[:500]))
    # A decode can end less than one frame before the requested cut boundary.
    if not shots:raise ValueError('No usable scenes for the selected footage.')
    duration=shots[-1]['end']
    words=[c for c in captions if c['start']<duration]
    for c in words:
        if c['end']>duration:c['source_end']-=c['end']-duration;c['end']=duration
    import hook_layer
    suggestion=hook_layer.suggest(words,duration,context_kind=kind,scenes=[s['start'] for s in shots])
    headline=suggestion['text'] if suggestion else ''
    last=words[-1]['text'] if words else ''
    hook=dict(text=headline,start=0.0,end=min(3.0,duration),enabled=os.getenv('AUTO_HOOK')=='1' and bool(headline),
              evidence='opening_source_quote' if headline else 'unavailable',kind=suggestion['kind'] if suggestion else 'curiosity')
    result=EditPlan.model_validate(dict(source_ref=Path(context.get('source_path') or media).name,
        source_identity=context.get('source_identity') or identity(context.get('source_path') or media),
        source_duration=float(context.get('source_duration') or max(s['source_end'] for s in segments)),
        width=width,height=height,fps=float(fps),duration=duration,output_width=out_size[0],output_height=out_size[1],
        kind=kind,strategy=policy,segments=segments,shots=shots,captions=words,caption_preset=preset,
        captions_enabled=os.getenv('AUTO_CAPTIONS','1')!='0',hook=hook,audio=audio or audio_decision([],duration),transitions=[],
        ending=dict(action='preserve',end=duration,speech_complete=bool(last and last.rstrip().endswith(('.','!','?','。','！','？'))),
                    note='Keep selected source ending and reactions; punctuation does not prove semantic resolution.'),
        evidence=dict(kind=kind_evidence,visual_context=bool((context.get('analysis') or {}).get('moments')),
                      tracking='existing v2 detections',transitions='natural source cuts only'))).model_dump(mode='json')
    category_choice=selected_category(context)
    if category_choice:result['evidence']['category_selection']=category_choice
    import auto_edit
    result['auto_edit']=auto_edit.generate(result,context.get('analysis'))
    if result['hook']['enabled']:
        y=hook_layer.placement({k:result['hook'][k] for k in ('text','start','end','style','animation','y')},hook_regions(result))
        if y is None:result['hook'].update(enabled=False,evidence='disabled')
        else:result['hook']['y']=y
    return result


def save(path,plan):
    from story_director import atomic_json
    atomic_json(str(path)+'.edit.json',EditPlan.model_validate(plan).model_dump(mode='json'))


def load(path):
    import json
    return EditPlan.model_validate(json.loads(Path(str(path)+'.edit.json').read_text(encoding='utf-8'))).model_dump(mode='json')


def caption_faces(plan):
    """Map retained source face boxes into output space; no new detector pass."""
    import reframe_v2
    output=[];ow,oh=plan['output_width'],plan['output_height']
    for shot in plan['shots']:
        views=[]
        if shot['renderer']=='TRACK':
            for key in shot['keyframes']:
                views.append((key,0.0,0.0,1.0,1.0))
        elif shot['layout']=='SPLIT':
            views=[(r,0.0,i*.5,1.0,.5) for i,r in enumerate(shot['regions'])]
        elif shot['renderer']=='EDITORIAL':
            w,h,x,y,dh,ch=reframe_v2.editorial_geometry(plan['width'],plan['height'],ow,oh,shot['focus_x'])
            views=[(dict(x=x,y=y,width=w,height=h),0.0,0.0,1.0,dh/oh)]
        else:
            scale=min(ow/plan['width'],oh/plan['height']);w=plan['width']*scale/ow;h=plan['height']*scale/oh
            views=[(dict(x=0,y=0,width=plan['width'],height=plan['height']),(1-w)/2,(1-h)/2,w,h)]
        # A conservative envelope avoids repeated equivalent face records.
        for face in [*shot['faces'],*shot.get('protected_regions',[])]:
            mapped=[]
            for box,x,y,w,h in views:
                left=max(face['x'],box['x']);top=max(face['y'],box['y'])
                right=min(face['x']+face['width'],box['x']+box['width']);bottom=min(face['y']+face['height'],box['y']+box['height'])
                if right>left and bottom>top:
                    mapped.append((x+(left-box['x'])/box['width']*w,y+(top-box['y'])/box['height']*h,
                                   x+(right-box['x'])/box['width']*w,y+(bottom-box['y'])/box['height']*h))
            if mapped:
                left=min(v[0] for v in mapped);top=min(v[1] for v in mapped)
                output.append(dict(start=shot['start'],end=shot['end'],x=left,y=top,
                                   width=max(v[2] for v in mapped)-left,height=max(v[3] for v in mapped)-top))
    import auto_edit
    return auto_edit.caption_regions(output,plan.get('auto_edit'))


def hook_regions(plan):
    """Keep full context compositions clear as well as known moving faces."""
    protected=caption_faces(plan)
    for shot in plan['shots']:
        if shot['layout']=='EDITORIAL':
            # These layouts were chosen because the distributed content matters.
            protected.append(dict(start=shot['start'],end=shot['end'],x=0.,y=0.,width=1.,height=.6))
    return protected


def render_layers(clean,output,decisions,*,size=None,runner=None,caption_asset=None):
    """One caption/headline implementation shared by directed final and preview."""
    import shutil
    import tempfile
    import caption_renderer
    from ffmpeg_utils import escape_filter_value,METADATA_SCRUB
    import reframe_v2
    plan=EditPlan.model_validate(decisions).model_dump(mode='json')
    width,height=size or (plan['output_width'],plan['output_height'])
    execute=runner or reframe_v2._run
    words=[dict(word=' '+c['text'],start=c['start'],end=c['end'],aligned=c['aligned']) for c in plan['captions']]
    transcript={'segments':[dict(start=0,end=plan['duration'],words=words)]}
    with tempfile.TemporaryDirectory(prefix='director_captions_') as work:
        import auto_edit
        settings=plan.get('auto_edit')
        original_clean=str(clean)
        if settings:
            clean=auto_edit.render(clean,Path(work)/'effects.mp4',settings,(width,height),plan['fps'],execute,reframe_v2.director_encoder(width,height))
            transcript=auto_edit.emphasize(transcript,settings)
        ass=Path(work)/'captions.ass'
        made=False
        if plan['captions_enabled']:
            protected=caption_faces(plan)
            if plan['hook']['enabled']:
                protected.append(dict(start=0,end=plan['hook']['end'],x=.05,y=.1,width=.9,height=.15))
            made=caption_renderer.generate(transcript,0,plan['duration'],str(ass),width,height,
                plan['caption_preset'],auto_effects=auto_edit.active(settings),splits=[(s['start'],s['end']) for s in plan['shots'] if s['layout']=='SPLIT'],
                editorials=[(s['start'],s['end']) for s in plan['shots'] if s['layout']=='EDITORIAL'],faces=protected,
                blurs=[(s['start'],s['end'],(1+min(width/plan['width'],height/plan['height'])*plan['height']/height)/2) for s in plan['shots'] if s['layout']=='BLUR'])
            import render_runtime
            render_runtime.require_captions(transcript,0,plan['duration'],True,made)
        if plan['hook']['enabled']:
            if not made:
                # Generate the normal header via an isolated placeholder, then remove its events.
                caption_renderer.generate({'segments':[dict(start=0,end=.05,text='header')]},0,plan['duration'],str(ass),width,height)
                content=ass.read_text(encoding='utf-8-sig')
                ass.write_text('\n'.join(line for line in content.splitlines() if not line.startswith('Dialogue:'))+'\n',encoding='utf-8-sig')
            import hook_layer
            headline=plan['hook']
            event=hook_layer.ass_event({k:headline[k] for k in ('text','start','end','style','animation','y')},width,height,faces=hook_regions(plan))
            ass.write_text(hook_layer.append_ass(ass.read_text(encoding='utf-8-sig'),event),encoding='utf-8-sig')
            made=made or bool(event)
        if made:
            if caption_asset is not None:
                # Reusable caption-only asset for later independent hook edits.
                if plan['hook']['enabled']:raise ValueError('Caption asset must not contain a headline.')
                shutil.copyfile(ass,caption_asset)
            execute(['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_threads','1','-i',str(clean),
                     '-vf',f"ass=filename='{escape_filter_value(str(ass))}':fontsdir='{escape_filter_value(str(Path(__file__).parent/'fonts'))}'",'-map','0:v:0','-map','0:a?',
                     *reframe_v2.director_encoder(width,height),'-c:a','aac',*METADATA_SCRUB,'-movflags','+faststart',str(output)])
        else:shutil.copyfile(clean,output)
        effects_applied=str(clean)!=original_clean
    return bool(made or effects_applied)
