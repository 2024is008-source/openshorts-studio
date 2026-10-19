"""Offline A/B/C artifact evaluator. Never sends media or invokes an AI API.

Run: python -m adaptive_analysis.benchmark manifest.json report.json
Manifest samples identify category, human reference intervals and three saved
analysis artifacts (existing, transcript, adaptive). Missing measurements stay
null; generated fixtures never count as human quality evidence.
"""
import json
import math
from pathlib import Path
import sys

COVERAGE=('podcast-motivation','podcast-education','podcast-comedy','challenge','cricket','football','silent')
MODES=('existing','transcript','adaptive')


def interval(row):
    a,b=row.get('start'),row.get('end')
    if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a+b) or not 0<=a<b:raise ValueError('Invalid benchmark interval')
    return a,b


def iou(a,b):
    x,y=interval(a);u,v=interval(b)
    return max(0,min(y,v)-max(x,u))/(max(y,v)-min(x,u))


def evaluate(manifest,root):
    output=[];covered=set();human_ready=True
    for sample in manifest.get('samples',[]):
        category=sample['category']
        if category not in COVERAGE:raise ValueError('Unsupported benchmark category')
        references=sample.get('references',[])
        for row in references:interval(row)
        human=sample.get('reference_origin')=='human' and not manifest.get('synthetic',False)
        reviewed=sample.get('reviews',{})
        def complete_review(mode):
            value=reviewed.get(mode,{})
            return (isinstance(value,dict) and all(type(value.get(k)) in (int,float) and 0<=value[k]<=1 for k in ('story_completeness','human_preference'))
                and type(value.get('false_event_claims')) is int and value['false_event_claims']>=0)
        human_ready=human_ready and human and bool(references) and all(complete_review(mode) for mode in MODES)
        covered.add(category)
        for mode in MODES:
            path=sample.get('artifacts',{}).get(mode)
            if not path:
                output.append(dict(sample=sample['id'],category=category,mode=mode,status='missing_artifact'));human_ready=False;continue
            data=json.loads((root/path).read_text(encoding='utf-8'))
            rows=data.get('shorts',data.get('moments',[]))
            for row in rows:interval(row)
            matches=[]
            for ref in references:
                best=max(rows,key=lambda r:iou(ref,r),default=None)
                if best is not None and iou(ref,best)>=.5:matches.append((ref,best))
            metrics=data.get('metrics',{});cost=data.get('cost_analysis',{})
            review=reviewed.get(mode,{}) if human else {}
            output.append(dict(sample=sample['id'],category=category,mode=mode,status='evaluated',quality_basis='human' if human else 'synthetic_or_unreviewed',
                reference_count=len(references),clip_count=len(rows),
                candidate_recall=len(matches)/len(references) if references else None,
                mean_boundary_error_seconds=sum((abs(a['start']-b['start'])+abs(a['end']-b['end']))/2 for a,b in matches)/len(matches) if matches else None,
                story_completeness=review.get('story_completeness'),human_preference=review.get('human_preference'),false_event_claims=review.get('false_event_claims'),
                tokens=metrics.get('usage') or {k:cost.get(k) for k in ('input_tokens','output_tokens','thinking_tokens')},
                requests=metrics.get('requests'),video_seconds=metrics.get('video_seconds'),analysis_seconds=metrics.get('elapsed_seconds'),
                retries=metrics.get('retry_count'),upload_seconds=metrics.get('upload_seconds'),
                local_processing_seconds=metrics.get('local_processing_seconds'),rendering_seconds=metrics.get('rendering_seconds')))
    missing=sorted(set(COVERAGE)-covered)
    return dict(schema=1,synthetic=manifest.get('synthetic',False),missing_categories=missing,
        acceptance_ready=human_ready and bool(output) and not missing,results=output,
        limitations=['No model calls are made by this evaluator. Missing provider or human measurements are not estimated.',
            'Synthetic reference recall tests software behavior; it establishes no real-world quality improvement.',
            'Acceptance readiness records completeness of evidence, not an automatic approval or change of default.'])


def main():
    source=Path(sys.argv[1]);target=Path(sys.argv[2])
    target.write_text(json.dumps(evaluate(json.loads(source.read_text(encoding='utf-8')),source.parent),indent=2),encoding='utf-8')


if __name__=='__main__':main()
