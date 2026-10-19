"""Opt-in local ASR acceptance. Calls the existing engine; never calls Gemini."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop.generation_review import progress

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();video=Path(args.video).resolve();out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True);(out/'transcription-check').mkdir(exist_ok=True)
    job=dict(status='processing',native_started_at=time.time(),logs=['Job started by worker.','Transcribing video...'])
    engine=SimpleNamespace(OUTPUT_DIR=str(out),jobs={'transcription-check':job})
    def snapshot():
        data=progress(engine,'transcription-check')
        temp=out/'live-progress.tmp';temp.write_text(json.dumps(data),encoding='utf-8');os.replace(temp,out/'live-progress.json')
        with (out/'progress-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(data)+'\n')
    class Logs:
        def __init__(self):self.pending=''
        def write(self,value):
            self.pending+=value
            while '\n' in self.pending:
                line,self.pending=self.pending.split('\n',1)
                if line.strip():
                    job['logs'].append(line.strip());snapshot()
            return len(value)
        def flush(self):pass
    snapshot()
    try:
        with contextlib.redirect_stdout(Logs()):
            from transcribe_backends import transcribe_media
            transcript=transcribe_media(str(video))
        job['logs'].append('Transcribing… 100% (finished)');snapshot()
        (out/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False),encoding='utf-8')
        stage=next(s for s in progress(engine,'transcription-check')['stages'] if s['id']=='transcribe')
        assert stage['state']=='completed' and stage['percent']==100
        report=dict(success=True,source=str(video),freshLocalTranscription=True,paidRequests=0,segments=len(transcript['segments']),words=sum(len(s.get('words',[])) for s in transcript['segments']),elapsedSeconds=time.time()-job['native_started_at'],language=transcript['language'])
    except Exception as error:
        report=dict(success=False,error=f'{type(error).__name__}: {error}',paidRequests=0)
    (out/'asr-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
