"""Isolated native acceptance fixture. Synthetic cues, no AI or transcription."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import editing_director

directory=Path(sys.argv[1]).resolve()
subprocess.run([sys.executable,str(ROOT/'tools/prepare_clipper_smoke.py'),str(directory)],check=True)
folder=directory/'library/output/review-smoke';source=folder/'example_clip_1.mp4'
words={'segments':[dict(start=.2,end=2.5,words=[dict(word=' 100',start=.5,end=.9),dict(word=' local tests.',start=1.,end=1.7)])]}
analysis={'moments':[{'editing_cues':[dict(kind='surprise',start=.4,end=2.,quote='100 local tests.',
    evidence='Synthetic test observation, not a claim about the test-pattern footage.',confidence=.95)]}]}
plan=editing_director.compile_plan(media=str(source),width=320,height=180,fps=24.,out_size=(320,180),
    ranges=[(0,72,'TRACK')],xs=[0]*72,ys=[0]*72,crop_size=(320,180),
    context={'source_path':str(source),'segments':[dict(start=0,end=3)],'transcript':words,'analysis':analysis},
    subjects={0:[[145,55,20,25]]})
editing_director.save(source,plan)
meta=folder/'example_metadata.json';data=json.loads(meta.read_text())
data['transcript']=words;data['shorts'][0]['edit_decision_file']=source.name+'.edit.json'
meta.write_text(json.dumps(data),encoding='utf-8')
(directory/'auto-edit.check').write_text('Local acceptance fixture; do not call Gemini.',encoding='utf-8')
print('Prepared saved director effects for native undo/reopen/preview acceptance.')
