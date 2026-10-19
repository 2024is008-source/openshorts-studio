"""Render local style samples using synthetic media and explicit word fixtures."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import caption_renderer  # noqa: E402
from subtitles import _escape_ffmpeg_filter_value  # noqa: E402


def main():
    from PIL import Image, ImageDraw
    directory = ROOT/'output'/'local-caption-looks'
    directory.mkdir(parents=True, exist_ok=True)
    transcript = {'segments': [{'words': [dict(word=' '+w, start=a, end=b) for w, a, b in
                   [('To', .1, .45), ('get', .65, 1), ('started!', 1.1, 1.6)]]}]}
    sheet = Image.new('RGB', (720, 480), '#10151d')
    results = []
    for i, preset in enumerate(('green-pop', 'teal-reveal', 'paper-focus')):
        ass = directory/f'{preset}.ass'; video = directory/f'{preset}.mp4'
        caption_renderer.generate(transcript, 0, 2, ass, preset=preset)
        safe = _escape_ffmpeg_filter_value(str(ass))
        fonts = _escape_ffmpeg_filter_value(str(ROOT/'fonts'))
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                        'color=c=0x223344:s=1080x1920:r=30:d=2', '-vf',
                        f"ass=filename='{safe}':fontsdir='{fonts}'", '-c:v', 'libx264',
                        '-threads', '2', '-pix_fmt', 'yuv420p', '-preset', 'fast',
                        '-crf', '20', '-movflags', '+faststart', str(video)],
                       check=True, capture_output=True, timeout=60)
        png = directory/f'{preset}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '0.8', '-i', str(video),
                        '-frames:v', '1', str(png)], check=True, capture_output=True, timeout=10)
        picture = Image.open(png).convert('RGB'); picture.thumbnail((240, 427))
        sheet.paste(picture, (i*240, 30))
        ImageDraw.Draw(sheet).text((i*240+10, 10), preset, fill='white')
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                  '-of', 'json', str(video)], timeout=10))
        stream = info['streams'][0]
        assert (stream['width'], stream['height']) == (1080, 1920)
        assert stream['codec_name'] == 'h264' and stream['pix_fmt'] == 'yuv420p'
        results.append(dict(preset=preset, file=video.name, width=stream['width'],
                            height=stream['height'], codec=stream['codec_name'],
                            fps=stream['avg_frame_rate'], duration=stream['duration']))
    sheet.save(directory/'preview.png')
    (directory/'report.json').write_text(json.dumps(dict(synthetic=True, audio_expected=False,
        transcript=transcript, exports=results), indent=2), encoding='utf-8')
    print(directory)


if __name__ == '__main__':
    main()
