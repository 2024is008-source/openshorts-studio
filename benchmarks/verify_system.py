"""TASK-011 read-only media audit. No Gemini calls, downloads or source edits.

Run with the repository venv. Reports/contact sheets go to output/task011-review.
Visual heuristics and timestamp consistency are not speech/semantic certification.
"""
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio_mastering
import export_quality as quality
import render_runtime
from caption_timing import relative_words


def caption_audit(transcript, start, end):
    """Audit the existing normalized caption clock without inventing alignment."""
    words = relative_words(transcript, start, end)
    return dict(status='PASS' if words else 'UNVERIFIED', tokens=len(words),
        aligned_tokens=sum(bool(w['aligned']) for w in words),
        interval=[start, end],
        finite_inside_clip=all(0 <= w['start'] < w['end'] <= end-start for w in words),
        nonoverlapping=all(a['end'] <= b['start'] for a, b in zip(words, words[1:])),
        scope='Normalized retained timestamps only; no independent ASR accuracy measurement.')


def ass_audit(text, duration):
    def seconds(value):
        h, m, s = value.split(':')
        return int(h)*3600+int(m)*60+float(s)
    errors = []
    events = 0
    for line in text.splitlines():
        if not line.startswith('Dialogue:'):
            continue
        events += 1
        try:
            fields = line.split(',', 9)
            a, b = seconds(fields[1]), seconds(fields[2])
            if not 0 <= a < b <= duration+.011:
                errors.append(dict(event=events, start=a, end=b, problem='outside clip or empty'))
        except (ValueError, IndexError):
            errors.append(dict(event=events, problem='malformed dialogue'))
    return dict(status='FAIL' if errors else 'PASS' if events else 'UNVERIFIED',
        events=events, errors=errors, scope='ASS event bounds; overlapping visual layers are permitted.')


def sampled_cuts(path):
    """Bounded coarse candidates for spot-check selection, not exact cut labels."""
    proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-threads', '2',
        '-i', str(path), '-t', '180', '-an', '-vf',
        r'scale=192:-2,fps=3,select=gt(scene\,0.30),showinfo',
        '-filter_threads', '1', '-f', 'null', '-'],
        capture_output=True, check=True, timeout=40)
    return sorted(set(float(t) for t in re.findall(
        r'pts_time:([\d.]+)', proc.stderr.decode('utf-8', 'replace'))))


def contact_sheet(path, times, output):
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
    sheet = Image.new('RGB', (1080, 540*((len(times)+3)//4)), '#202020')
    draw = ImageDraw.Draw(sheet)
    for i, stamp in enumerate(times):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1',
            '-ss', str(stamp), '-i', str(path), '-frames:v', '1', '-vf',
            'scale=270:480:force_original_aspect_ratio=decrease', '-filter_threads', '1',
            '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
            capture_output=True, check=True, timeout=10)
        image = Image.open(io.BytesIO(result.stdout)).convert('RGB')
        x, y = (i % 4)*270, (i//4)*540
        sheet.paste(image, (x+(270-image.width)//2, y+30))
        draw.text((x+8, y+8), f'{stamp:.3f}s', fill='white', font=font)
    sheet.save(output)


def media_audit(path, role, directory, identifier):
    result = dict(id=identifier, file=str(path.resolve()), role=role)
    if not path.is_file():
        return dict(result, status='UNAVAILABLE')
    try:
        info = quality.probe(path)
        expected = quality.expectations(info)
        # These are delivery requirements, independent of whatever probe found.
        if role != 'source':
            expected.update(width=1080, height=1920, aspect=9/16,
                video_codec='h264', pixel_format='yuv420p', audio_codec='aac')
        result['technical'] = quality.validate(path, identifier, expected)
        duration = expected['duration']
        if quality.streams(info)[1]:
            result['audio'] = audio_mastering.measure(path, audio_mastering.settings(),
                duration, time.monotonic()+60, prepared=False)
        else:
            result['audio'] = dict(status='NO_AUDIO', expected=None)
        cuts = sampled_cuts(path)
        stamps = quality.sample_times(duration, cuts, limit=8)
        image = directory/f'{identifier}.png'
        contact_sheet(path, stamps, image)
        result.update(status=result['technical']['status'], metadata=info,
            visual=dict(contact_sheet=str(image.resolve()), times=stamps,
                coarse_cut_candidates=cuts, cut_sample_fps=3,
                scope='Human contact-sheet review required; no facial emotion inference.'))
        ass = path.with_suffix('.ass')
        if ass.is_file():
            result['caption_asset'] = ass_audit(ass.read_text(encoding='utf-8-sig'), duration)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result.update(status='ERROR', error_type=type(exc).__name__)
    return result


def saved_editor_audit(metadata, folder):
    """Exercise existing preview/final/cache against retained, timed real speech.

    Work goes to a new review directory. The original project is never saved or
    published. Existing canonical clean framing is preserved, not reanalyzed.
    """
    import timeline_project as project
    import timeline_render
    import video_templates

    data = json.loads(metadata.read_text(encoding='utf-8'))
    clip = data['shorts'][2]
    canonical = metadata.with_name(metadata.name.replace('_metadata.json', '_clip_3.mp4'))
    if not canonical.is_file():
        return dict(status='UNAVAILABLE', reason='Retained clean canonical clip is missing.')
    rows = project.captions(data.get('transcript'))
    bounds = dict(start=clip['start'], end=clip['end'])
    edits = project.initial(clip, [bounds], None)['edits']
    edits.update(template=video_templates.selected('creator-energy'),
        template_content=dict(headline=dict(text='', start=0, end=1.8), labels=[]))
    edits = project.normalize(edits, bounds['end'], rows)
    (folder/'editor-decisions.json').write_text(json.dumps(edits, indent=2), encoding='utf-8')
    fps = quality.rate(quality.streams(quality.probe(canonical))[0]['avg_frame_rate'])
    common = dict(edits=edits, rows=rows, source=None, canonical=str(canonical),
        canonical_range=bounds, fps=fps, audio=True, directory=folder,
        cancel=threading.Event(), progress=lambda *args: None)
    outputs = {}
    for mode, size in [('preview', (270, 480)), ('final', (1080, 1920))]:
        path, cache = timeline_render.render(size=size, **common)
        expected = quality.expectations(quality.probe(canonical), size=size,
            duration=bounds['end']-bounds['start'], speech_expected=True)
        expected.update(video_codec='h264', pixel_format='yuv420p', audio_codec='aac')
        report = quality.enforce(path, 'real-editor-'+mode, expected,
            master_audio=True, audio_config=video_templates.audio_settings(edits['template']))
        timeline_render.receipt(path)
        outputs[mode] = dict(path=path, cache=cache, quality=report,
            decisions_digest=project.digest(edits))
    reopened, reused = timeline_render.render(size=(1080, 1920), **common)
    result = dict(status='PASS', outputs=outputs, reopened_same_file=reopened==outputs['final']['path'],
        cache=reused, scope='Existing clean framing + retained transcript -> template preview/final; no live AI/ASR.')
    if not result['reopened_same_file'] or reused['segment_hits'] != len(edits['segments']):
        raise ValueError('Unchanged saved editor failed to reuse its final artifact')
    (folder/'editor-integration.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    return result


def save_sections(report, folder):
    sections = {
        'technical-video': [dict(id=m['id'], role=m['role'], status=m['status'], report=m.get('technical')) for m in report['media']],
        'caption-timing': dict(retained_transcript=report['captions'], assets=[dict(id=m['id'], **m['caption_asset'])
            for m in report['media'] if 'caption_asset' in m], scope='Timing consistency, not independent ASR accuracy.'),
        'audio': [dict(id=m['id'], measurements=m.get('audio')) for m in report['media']],
        'layout': [dict(id=m['id'], **m['visual']) for m in report['media'] if 'visual' in m],
        'feature-availability': report['capabilities'],
        'application-errors': dict(media_errors=[dict(id=m['id'], error=m.get('error_type'))
            for m in report['media'] if m['status']=='ERROR'], note='See TASK-011 report for test/build/lint outcomes.'),
    }
    for name, value in sections.items():
        (folder/(name+'.json')).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def main():
    folder = ROOT/'output/task011-review'
    folder.mkdir(parents=True, exist_ok=True)
    report = dict(version=1, checked_at=time.time(), capabilities=render_runtime.capabilities(),
        scope='Read-only existing media; no live Gemini, ASR or source regeneration.', media=[], captions=[])
    references = Path.home()/'Downloads'
    cases = [
        (references/'Eating A Store For $1,000,000 Challenge!.mp4', 'reference', 'reference-store'),
        (references/'One Million Calorie Challenge_ Running for Family!.mp4', 'reference', 'reference-running'),
        (ROOT/'screenshots/reframing-task003/synthetic-tracking-1080x1920.mp4', 'fixture', 'tracking'),
        (ROOT/'screenshots/animated-hooks/scale-pop-1080x1920.mp4', 'fixture', 'hook'),
        (ROOT/'output/task004-caption-samples/openshorts-dynamic.mp4', 'fixture', 'captions'),
    ]
    cases += [(ROOT/f'output/task008-templates/{name}.mp4', 'fixture', f'template-{name}')
        for name in ['creator-energy', 'minimal-studio', 'story-focus', 'podcast', 'challenge']]
    job = ROOT/'output/864f088a-e8cf-4836-adc1-bfdd398fdd60'
    metadata = next(job.glob('*_metadata.json'), None)
    if metadata:
        data = json.loads(metadata.read_text(encoding='utf-8'))
        for index in [0, 2, 11]:
            clip = data['shorts'][index]
            name = clip.get('delivered_file') or Path(clip.get('video_url', '')).name
            if name:
                cases.append((job/name, 'existing-export', f'legacy-{index+1}'))
            report['captions'].append(dict(id=f'legacy-{index+1}',
                **caption_audit(data.get('transcript'), clip['start'], clip['end'])))
    for path, role, identifier in cases:
        row = media_audit(path, role, folder, identifier)
        report['media'].append(row)
        # Save progress, so an interruption cannot masquerade as a complete run.
        report['complete'] = False
        (folder/'media-report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(identifier, row['status'], flush=True)
    if metadata:
        editor_folder = folder/'real-editor'
        editor_folder.mkdir(exist_ok=True)
        report['editor_integration'] = saved_editor_audit(metadata, editor_folder)
        if report['editor_integration'].get('status')=='PASS':
            report['media'].append(media_audit(Path(report['editor_integration']['outputs']['final']['path']),
                'new-export',folder,'real-editor-final'))
    report['complete'] = True
    (folder/'media-report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    save_sections(report, folder)


if __name__ == '__main__':
    main()
