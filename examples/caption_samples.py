"""Reproducible local caption samples; synthetic media, no API requests."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import caption_renderer
from subtitles import _escape_ffmpeg_filter_value


def main():
    from PIL import Image,ImageDraw
    directory=ROOT/'output'/'task004-caption-samples';directory.mkdir(parents=True,exist_ok=True)
    screenshots=ROOT/'screenshots';screenshots.mkdir(exist_ok=True)
    transcript={'segments':[{'words':[dict(word=' '+w,start=a,end=b) for w,a,b in
        [('Clear',.1,.55),('words.',.6,1.05),('Perfect',1.2,1.65),('timing.',1.7,2.3)]]}]}
    tiles=[]
    for preset in caption_renderer.DISPLAY_PRESETS:
        ass=directory/f'{preset}.ass';video=directory/f'{preset}.mp4';still=directory/f'{preset}.png'
        caption_renderer.generate(transcript,0,2.5,ass,preset=preset)
        safe=_escape_ffmpeg_filter_value(str(ass))
        subprocess.run(['ffmpeg','-v','error','-y','-nostdin','-f','lavfi','-i',
            'color=c=0x21364D:s=1080x1920:r=30:d=2.5','-vf',
            f"drawbox=x=0:y=0:w=iw:h=ih/2:color=0x29465F:t=fill,ass=filename='{safe}'",
            '-c:v','libx264','-threads','2','-preset','ultrafast','-crf','22',str(video)],check=True,timeout=30)
        subprocess.run(['ffmpeg','-v','error','-y','-ss','0.8','-i',str(video),'-frames:v','1',str(still)],check=True,timeout=10)
        image=Image.open(still).convert('RGB');image.thumbnail((216,384))
        tile=Image.new('RGB',(236,424),'#121a24');tile.paste(image,(10,25));ImageDraw.Draw(tile).text((10,8),preset,fill='white')
        tiles.append(tile)
    sheet=Image.new('RGB',(236*len(tiles),424),'#121a24')
    for i,tile in enumerate(tiles):sheet.paste(tile,(236*i,0))
    sheet.save(screenshots/'task004-advanced-caption-presets.png')
    (directory/'transcript.json').write_text(json.dumps(transcript),encoding='utf-8')
    print('Samples:',directory)
    print('Contact sheet:',screenshots/'task004-advanced-caption-presets.png')


if __name__=='__main__':main()
