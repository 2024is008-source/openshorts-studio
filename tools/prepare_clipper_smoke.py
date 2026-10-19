"""Prepare an isolated, unpaid native review acceptance library."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--image');parser.add_argument('--video');parser.add_argument('--start',type=float,default=0);args=parser.parse_args()
    root=Path(args.directory).resolve();folder=root/'library'/'output'/'review-smoke'
    if folder.exists(): raise SystemExit('Use a fresh diagnostic directory; existing fixtures are preserved.')
    folder.mkdir(parents=True)
    video=folder/'example_clip_1.mp4'
    if args.video:
        inputs=['-ss',str(args.start),'-i',str(Path(args.video).resolve()),'-t','3','-vf','scale=640:360','-r','24']
    elif args.image:
        inputs=['-loop','1','-i',str(Path(args.image).resolve()),'-f','lavfi','-i','sine=frequency=440:duration=3','-vf','scale=640:360:force_original_aspect_ratio=increase,crop=640:360,zoompan=z=1.02+0.001*on:x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d=1:s=320x180:fps=24','-t','3']
    else: inputs=['-f','lavfi','-i','testsrc2=s=320x180:r=24:d=3','-f','lavfi','-i','sine=frequency=440:duration=3']
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*inputs,'-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
    shutil.copyfile(video,folder/'example_clip_2.mp4')
    (folder/'example.srt').write_text('1\n00:00:00,000 --> 00:00:02,900\nLocal native review fixture.\n',encoding='utf-8')
    clips=[dict(start=0,end=3,title='Local review fixture '+str(i+1),video_url=f'/videos/review-smoke/example_clip_{i+1}.mp4',ranking_report=dict(overall=95-i*7,reasons=['Mock editorial score for automated testing']),tags=['Fixture'],hook_text='Local test source') for i in range(3)]
    (folder/'example_metadata.json').write_text(json.dumps(dict(title='Local acceptance fixture',source_video=video.name,output_format='horizontal',shorts=clips)),encoding='utf-8')
    print('Prepared local real-video excerpt; no AI provider calls.' if args.video else 'Prepared local synthetic media; no AI provider calls.')
