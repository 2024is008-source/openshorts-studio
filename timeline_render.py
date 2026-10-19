"""Cancellable local compositor: cached parts -> assembly -> caption derivative."""
import array
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

import caption_renderer
import export_quality as quality
import framing_geometry as geometry
import recut
import timeline_project as project
from ffmpeg_utils import METADATA_SCRUB, escape_filter_value
import render_runtime


Cancelled=render_runtime.Cancelled


def check(cancel):
    if cancel.is_set(): raise Cancelled('Editor render cancelled.')


def run(command, cancel, timeout=180):
    """Kill/reap a child on cancellation or timeout; no shell or user argv."""
    return render_runtime.run(command,cancel,timeout)


def cached(path):
    """A receipt binds a successfully finished artifact to its current bytes."""
    try:
        saved=json.loads(Path(str(path)+'.cache.json').read_text())
        return saved == project.identity(path) and Path(path).stat().st_size > 0
    except (OSError, ValueError): return False


def receipt(path):
    from story_director import atomic_json
    atomic_json(str(path)+'.cache.json', project.identity(path))


def mix_audio(path, settings, duration, directory, cancel, progress):
    """Reuse the measured audio master, then apply explicit export gain/fades.

    Keep the clean caption derivative immutable so cached renders cannot receive
    gain twice. Music is a project-local imported stem, never an arbitrary path.
    """
    import shutil
    import audio_mastering
    folder=Path(directory).resolve()
    music=None
    if settings['music']:
        music=(folder/'media'/settings['music']).resolve()
        if not music.is_relative_to(folder/'media') or not music.is_file():raise ValueError('Imported music is unavailable.')
    target=folder/f'editor_audio_{project.digest([project.identity(path),settings,project.identity(music)])}.mp4'
    if cached(target):return str(target)
    progress(86,'Mastering timeline audio')
    with tempfile.TemporaryDirectory(prefix='temp_editor_audio_',dir=folder) as work:
        temporary=Path(work)/'master.mp4';shutil.copyfile(path,temporary)
        if settings['normalize']:
            cfg=audio_mastering.settings({'AUDIO_NORMALIZE':'1','AUDIO_MASTERING':'1',
                'AUDIO_TARGET_LUFS':str(settings['target']),'AUDIO_TRUE_PEAK':str(settings['ceiling']),
                'AUDIO_FADE_SECONDS':'0'})
            audio_mastering.master(temporary,config=cfg,music=music)
        check(cancel)
        gain=0 if settings['mute'] else settings['volume']
        filters=[f'volume={gain}']
        fade=min(settings['fade'],duration/2)
        if fade:filters += [f'afade=t=in:st=0:d={fade}',f'afade=t=out:st={duration-fade}:d={fade}']
        output=Path(work)/'output.mp4'
        run(['ffmpeg','-nostdin','-y','-v','error','-i',str(temporary),'-map','0:v:0','-map','0:a:0',
            '-c:v','copy','-af',','.join(filters),'-c:a','aac','-ar','48000','-ac','2',
            *METADATA_SCRUB,'-movflags','+faststart',str(output)],cancel,180)
        check(cancel);os.replace(output,target);receipt(target)
    return str(target)


def encode(size=None,audio_copy=False,options=None):
    import reframe_v2
    args=reframe_v2.director_encoder(*(size or (1080,1920)))
    if options:
        import ffmpeg_utils
        mode=options.get('encoder','auto');tier=options.get('quality','balanced')
        gpu=(mode=='nvenc' and ffmpeg_utils.nvenc_available() and min(size or (1080,1920))>=160) or (mode=='auto' and 'h264_nvenc' in args)
        if gpu:
            args=['-c:v','h264_nvenc','-preset',{'fast':'p2','balanced':'p4','high':'p6'}[tier],'-rc','vbr','-cq',str({'fast':26,'balanced':22,'high':18}[tier]),'-b:v','0']
        else:args=['-c:v','libx264','-preset',{'fast':'veryfast','balanced':'fast','high':'medium'}[tier],'-crf',str({'fast':26,'balanced':22,'high':18}[tier])]
    return [*args,'-pix_fmt','yuv420p',
            *(['-c:a','copy'] if audio_copy else ['-c:a','aac','-ar','48000','-ac','2']),
            *METADATA_SCRUB,'-movflags','+faststart']


def compose_filter(info, crop, size):
    width,height=size; video,_=quality.streams(info)
    if crop['mode']=='crop':
        w,h=geometry.crop_size(video['width'],video['height'],width/height)
        x,y=geometry.crop_position(video['width'],video['height'],w,h,
                                  crop['x']*video['width'],crop['y']*video['height'])
        return f'[0:v]crop={w}:{h}:{x}:{y},scale={width}:{height},setsar=1[v]'
    return geometry.contain_background(width,height)


def render(*, edits, rows, source, canonical, canonical_range, size, fps, audio,
           directory, cancel, progress, watermark=None, canonical_segments=None, previous=None,continuous_audio=False,encoding=None):
    """Both preview and final call this function with different dimensions only."""
    folder=Path(directory); folder.mkdir(exist_ok=True)
    canonical_segments=canonical_segments or [canonical_range]
    previous=previous or {}
    def encoder(size=None,audio_copy=False):return encode(size,audio_copy,options=encoding)
    deadline=time.monotonic()+600
    stage={'low':0,'high':10,'duration':None,'label':'Preparing export'}
    def execute(command):
        def measured(row):
            fraction=row.get('fraction')
            value=stage['low']+int((stage['high']-stage['low'])*(fraction or 0))
            progress(value,f'{stage["label"]} · {row["frame"]} frames · {row["time_seconds"]:.1f}s')
        with render_runtime.progress_scope(measured):
            return render_runtime.run(command,cancel,min(180,max(.1,deadline-time.monotonic())),duration=stage['duration'])
    reusable=(not encoding and previous.get('crop')==edits['crop'] and previous.get('size')==list(size)
              and previous.get('fps')==fps and previous.get('audio')==audio
              and previous.get('watermark')==bool(watermark)
              and previous.get('source_identity')==project.identity(source))
    parts=[]; keys=[]; hits=0;copied=0
    with tempfile.TemporaryDirectory(prefix='temp_editor_', dir=folder) as work:
        work=Path(work)
        for i,segment in enumerate(edits['segments']):
            check(cancel)
            cached_bounds=project.mapped_bounds(segment,canonical_segments)
            preserve=(edits['crop']['mode']=='preserve' or previous.get('crop')==edits['crop']) and canonical and cached_bounds is not None
            path=canonical if preserve else source
            if not path: raise ValueError('Retained source is required for this crop or source range.')
            bounds=cached_bounds if preserve else segment
            crop=dict(mode='preserve',x=.5,y=.5) if preserve else edits['crop']
            key=project.digest([project.segment_key(path,bounds,crop,size,fps,audio),encoder(size),render_runtime.limits()['threads']])
            # Watermarked and unrestricted projects never share render artifacts.
            key=project.digest([key, bool(watermark)])
            target=folder/f'editor_part_{key}.mp4'
            if reusable and previous.get('encoder_signature')==render_runtime.encoder_signature():
                for old_segment,old_key in zip(previous.get('segments',[]),previous.get('segment_keys',[])):
                    if old_segment==segment and isinstance(old_key,str) and re.fullmatch(r'[a-f0-9]{24}',old_key):
                        old_target=folder/f'editor_part_{old_key}.mp4'
                        if cached(old_target):key,target=old_key,old_target;break
            if cached(target): hits+=1
            else:
                stage.update(low=10+int(55*i/len(edits['segments'])),high=10+int(55*(i+1)/len(edits['segments'])),
                    duration=bounds['end']-bounds['start'],label='Encoding video segment')
                info=quality.probe(path)
                if audio and not quality.streams(info)[1]: raise ValueError('Expected source audio is missing.')
                temporary=work/'part.mp4'
                video,source_audio=quality.streams(info)
                source_duration=quality.number(video.get('duration'),quality.number(info.get('format',{}).get('duration')))
                passthrough=(preserve and bounds['start']==0 and source_duration is not None and
                    abs(bounds['end']-source_duration)<.001 and (video['width'],video['height'])==tuple(size) and
                    video.get('codec_name')=='h264' and video.get('pix_fmt')=='yuv420p' and
                    video.get('sample_aspect_ratio','1:1') in ('1:1','1/1') and
                    abs((quality.rate(video.get('avg_frame_rate')) or 0)-fps)<.001 and
                    bool(source_audio)==bool(audio) and (not audio or source_audio.get('codec_name')=='aac'))
                if passthrough:
                    import shutil
                    shutil.copy2(path,temporary);copied+=1
                else:
                    vf=compose_filter(info,crop,size)
                    execute(['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_complex_threads','1',
                     '-ss',str(bounds['start']),'-t',str(bounds['end']-bounds['start']),'-i',str(path),
                     '-filter_complex',vf,'-map','[v]',*(['-map','0:a:0'] if audio else ['-an']),
                     '-r',str(fps),*encoder(size),str(temporary)])
                check(cancel)
                os.replace(temporary,target); receipt(target)
            parts.append(target);keys.append(key)
            progress(10+int(55*(i+1)/len(edits['segments'])), 'Rendering changed video segments')
        clean_key=project.assembly_key(keys)
        if continuous_audio and audio and len(parts)>1:clean_key=project.digest([clean_key,'continuous-audio-v1'])
        clean=folder/f'editor_clean_{clean_key}.mp4'
        if not cached(clean):
            stage.update(low=65,high=70,duration=recut.total_duration(edits['segments']),label='Assembling video')
            listing=work/'parts.txt'
            # All entries are app-generated hashes beneath the work directory.
            listing.write_text(''.join(f"file '{p.name}'\n" for p in parts),encoding='utf-8')
            # A local list in the cache directory avoids quoting workspace paths.
            local_list=folder/f'temp_editor_{uuid.uuid4().hex}.txt'
            try:
                local_list.write_bytes(listing.read_bytes())
                if continuous_audio and audio and len(parts)>1:
                    bounds=[dict(start=0.,end=s['end']-s['start']) for s in edits['segments']]
                    execute(recut.continuous_cut_command(None,bounds,str(work/'joined.mp4'),video_args=encoder(size),input_paths=parts))
                else:execute(recut.concat_command(str(local_list),str(work/'joined.mp4')))
                if watermark: watermark(str(work/'joined.mp4'),execute)
                check(cancel)
                os.replace(work/'joined.mp4',clean);receipt(clean)
            finally:
                local_list.unlink(missing_ok=True)
        progress(70,'Reusing clean video; applying caption decisions')
        mapped=project.transcript(rows,edits)
        import auto_edit
        settings=edits.get('auto_edit')
        base_clean=clean;base_clean_key=clean_key
        if settings and edits['crop']['mode']!='preserve':
            import copy
            settings=copy.deepcopy(settings);settings.update(zoom=False,tracking=False)
        if settings:
            effect_key=project.digest([clean_key,auto_edit.VERSION,settings,size,fps])
            effected=folder/f'editor_effects_{effect_key}.mp4'
            if not cached(effected):
                stage.update(low=70,high=76,duration=recut.total_duration(edits['segments']),label='Rendering AI effect decisions')
                applied=auto_edit.render(clean,work/'effects.mp4',settings,size,fps,execute,encoder(size))
                if applied!=str(clean):
                    os.replace(applied,effected);receipt(effected)
            if cached(effected):clean=effected;clean_key=effect_key
            mapped=auto_edit.emphasize(mapped,settings)
        caption_faces=auto_edit.caption_regions([f for s in (settings or {}).get('scenes',[]) for f in s.get('caption_regions',[])],settings)
        import layout_ranges
        mapped_ranges=[project.mapped_bounds(s,canonical_segments) for s in edits['segments']]
        ranges=layout_ranges.remap(layout_ranges.read(canonical),mapped_ranges) if canonical and all(mapped_ranges) and edits['crop']['mode']=='preserve' else []
        layout_ranges.write(str(clean),ranges)
        layout_ranges.write(str(base_clean),ranges)
        caption_settings=dict(renderer_version=caption_renderer.RENDER_VERSION,face_placement_version=caption_renderer.FACE_PLACEMENT_VERSION,settings=
            dict(style=edits['style'],template=edits.get('template'),content=edits.get('template_content')) if edits.get('template') else edits['style'])
        selected_effects=auto_edit.active(settings)
        if selected_effects:caption_settings['auto_effects']=selected_effects
        caption_digest=project.caption_key(clean_key,{'transcript':mapped,'layouts':ranges},caption_settings)
        target=folder/f'editor_output_{caption_digest}.mp4'
        if not cached(target):
            stage.update(low=70,high=85,duration=recut.total_duration(edits['segments']),label='Rendering captions and overlays')
            temporary=work/'output.mp4'; ass=work/'captions.ass'
            made=False
            if edits.get('template'):
                import video_templates
                video_templates.render(clean,temporary,edits['template'],mapped,recut.total_duration(edits['segments']),
                    text=edits.get('template_content'),size=size,ranges=ranges,captions=edits['style']['enabled'],runner=execute,auto_effects=auto_edit.active(settings),
                    **({'faces':caption_faces} if caption_faces else {}))
                made=True
            elif edits['style']['enabled']:
                # Caption geometry shares the existing ASS path at both sizes.
                made=caption_renderer.generate(mapped,0,recut.total_duration(edits['segments']),str(ass),
                    *size,preset=edits['style']['preset'],position=edits['style']['position'],auto_effects=auto_edit.active(settings),
                    faces=caption_faces,
                    **edits['style'].get('appearance',{}),
                    splits=layout_ranges.split_ranges(ranges),editorials=layout_ranges.editorial_ranges(ranges),blurs=layout_ranges.blur_ranges(ranges))
                render_runtime.require_captions(mapped,0,recut.total_duration(edits['segments']),True,made)
            if made and not edits.get('template'):
                escaped=str(ass).replace('\\','/').replace(':',r'\:').replace("'",r"\'")
                execute(['ffmpeg','-y','-v','error','-nostdin','-threads','2','-filter_threads','1','-i',str(clean),
                     '-vf',f"ass=filename='{escaped}':fontsdir='{escape_filter_value(str(Path(__file__).parent/'fonts'))}'",'-map','0:v:0','-map','0:a?',
                     *encoder(size,audio_copy=True),str(temporary)])
            elif not made:
                import shutil
                try: os.link(clean,temporary)
                except OSError: shutil.copyfile(clean,temporary)
            check(cancel);os.replace(temporary,target);receipt(target)
        layout_ranges.write(str(target),[(r['start'],r['end'],r['layout']) for r in ranges])
        progress(85,'Validating rendered output')
        check(cancel)
        return str(target),dict(segment_hits=hits,segment_count=len(parts),clean_key=base_clean_key,
                               effects_applied=clean!=base_clean,
                               source_passthrough_parts=copied,
                               segment_keys=keys,
                               output_key=caption_digest,template_applied=bool(edits.get('template')),captions_applied=bool(edits['style']['enabled'] and any(
                                   s.get('words') for s in mapped['segments'])))


def features(*, segments, source, canonical, canonical_range, directory, cancel, canonical_segments=None):
    """Bounded 8 kHz mono waveform + sampled scene changes, no ML requests."""
    canonical_segments=canonical_segments or [canonical_range]
    key=project.digest([project.VERSION,'filmstrip-v1',project.identity(source),project.identity(canonical),segments,canonical_segments])
    cache=Path(directory)/f'editor_features_{key}.json'
    try: return json.loads(cache.read_text())
    except (OSError,ValueError): pass
    waveform=[0.0]*600;cuts=[];offset=0;deadline=time.monotonic()+45
    total=recut.total_duration(segments)
    for segment in segments:
        check(cancel)
        cached_bounds=project.mapped_bounds(segment,canonical_segments)
        inside=canonical and cached_bounds is not None
        path=source or (canonical if inside else None)
        if not path: raise ValueError('Source unavailable for this timeline range.')
        bound=segment if source else cached_bounds
        common=['ffmpeg','-v','info','-nostdin','-threads','1','-ss',str(bound['start']),
                '-t',str(bound['end']-bound['start']),'-i',str(path)]
        info=quality.probe(path)
        if quality.streams(info)[1]:
            raw,_=run([*common,'-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'],cancel,max(.1,deadline-time.monotonic()))
            values=array.array('h');values.frombytes(raw[:len(raw)//2*2])
            for i,value in enumerate(values):
                at=min(599,int((offset+i/8000)/total*600))
                waveform[at]=max(waveform[at],round(abs(value)/32768,4))
        _,log=run([*common,'-an','-vf',"scale=160:-2,fps=2,select='gt(scene,0.35)',showinfo",
                   '-filter_threads','1','-f','null','-'],cancel,max(.1,deadline-time.monotonic()))
        cuts.extend(round(offset+float(t),3) for t in re.findall(r'pts_time:([\d.]+)',log))
        if offset: cuts.append(round(offset,3))
        offset+=segment['end']-segment['start']
    thumbnails=[]
    for index in range(8):
        check(cancel)
        at=total*(index+.5)/8;offset=0
        for segment in segments:
            length=segment['end']-segment['start']
            if at<offset+length:
                bounds=segment if source else project.mapped_bounds(segment,canonical_segments)
                path=source or canonical
                if path and bounds:
                    target=Path(directory)/f'editor_thumb_{key}_{index}.jpg'
                    if not target.exists():
                        run(['ffmpeg','-v','error','-nostdin','-y','-ss',str(bounds['start']+at-offset),'-i',str(path),
                            '-frames:v','1','-vf','scale=160:-2','-threads','1',str(target)],cancel,max(.1,deadline-time.monotonic()))
                    if target.is_file():thumbnails.append(dict(time=round(at,3),path=str(target.resolve())))
                break
            offset+=length
    result=dict(waveform=waveform,scene_boundaries=sorted(set(cuts)),duration=round(total,3),thumbnails=thumbnails,
                scene_method='Sampled scene changes at 2 fps plus edit joins; fast cuts may be missed.')
    from story_director import atomic_json
    atomic_json(cache,result)
    return result
