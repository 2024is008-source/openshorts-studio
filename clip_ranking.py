"""Versioned, evidence-limited editorial ranking. No model or media calls."""
import copy
import hashlib
import json
import math
import os
import re

VERSION=1
DEFAULT_WEIGHTS={'hook':25,'story':25,'engagement':20,'visual':15,'pacing':10,'ending':5}


def score(value):
    if isinstance(value,bool): return None
    try:
        number=float(value)
        return round(number,4) if math.isfinite(number) and 0<=number<=100 else None
    except (ValueError,TypeError,OverflowError): return None


def normalize_weights(values=None):
    if values is None: values=DEFAULT_WEIGHTS
    if not isinstance(values,dict) or set(values)!=set(DEFAULT_WEIGHTS):
        raise ValueError('Weights must specify hook, story, engagement, visual, pacing and ending.')
    try: parsed={key:float(values[key]) for key in DEFAULT_WEIGHTS}
    except (ValueError,TypeError,OverflowError): raise ValueError('Weights must be numbers.')
    if (any(isinstance(values[key],bool) or not math.isfinite(v) or not 0<=v<=100 for key,v in parsed.items())
            or not sum(parsed.values())):
        raise ValueError('Weights must be finite numbers from 0 to 100, with a positive total.')
    total=sum(parsed.values())
    return {key:round(value if abs(total-100)<1e-6 else value/total*100,8) for key,value in parsed.items()}


def configured_weights():
    try: return normalize_weights(json.loads(os.environ['CLIP_SCORE_WEIGHTS']))
    except (KeyError,ValueError,TypeError): return normalize_weights()


def weighted_score(metrics,weights=None):
    weights=normalize_weights(weights)
    available={key:score(metrics.get(key)) for key in DEFAULT_WEIGHTS}
    coverage=sum(weights[key] for key,value in available.items() if value is not None)
    overall=(sum(value*weights[key] for key,value in available.items() if value is not None)/coverage
             if coverage else None)
    return dict(overall=round(overall,1) if overall is not None else None,metrics=available,
        weights=weights,coverage_percent=round(coverage,2),
        effective_weights={key:round(weights[key]/coverage*100,4) if value is not None and coverage else 0
                           for key,value in available.items()})


def _safe_evidence(value):
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,dict): return {str(k):_safe_evidence(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [_safe_evidence(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return str(value)


def explain(report,weights=None):
    """Adapt TASK-003 measurements; no missing metric receives a guessed score."""
    components=report.get('components');evidence=report.get('evidence')
    components=components if isinstance(components,dict) else {}
    evidence=evidence if isinstance(evidence,dict) else {}
    story=[score(components.get(key)) for key in ('standalone_context','narrative_completeness')]
    story=[v for v in story if v is not None]
    ratings=evidence.get('rating_fields') or []
    ratings=ratings if isinstance(ratings,list) else []
    metrics=dict(hook=components.get('hook_strength'),story=sum(story)/len(story) if story else None,
        engagement=components.get('emotional_engagement'),
        visual=components.get('visual_interest') if evidence.get('visual_context_available') and 'visual_interest' in ratings else None,
        pacing=components.get('pacing'),ending=components.get('ending_quality'))
    result=weighted_score(metrics,weights)
    occupancy=evidence.get('speech_coverage')
    occupancy=score(occupancy*100) if isinstance(occupancy,(int,float)) and not isinstance(occupancy,bool) else None
    reasons={
        'hook':"Provider's editorial opening rating." if 'hook_strength' in ratings else
               'Question/number cues in the timed opening; a limited lexical heuristic.',
        'story':'Provider context/completeness ratings and available sentence cues.' if any(k in ratings for k in ('standalone_context','narrative_completeness')) else
                'Opening-context and final-punctuation cues; semantic resolution was not measured.',
        'engagement':"Provider's emotional-engagement judgment; audience response was not measured.",
        'visual':"Provider's visual-interest judgment from inspected footage.",
        'pacing':(f'Transcript speech occupancy: {occupancy:g}%; timing gaps are a silence proxy.' if occupancy is not None else
                  'Retained pacing score; its original timing measurement is unavailable.'),
        'ending':"Provider's ending-quality judgment." if 'ending_quality' in ratings else
                 'Final timed utterance punctuation; this does not prove a story payoff.'}
    if not isinstance(evidence.get('rating_fields'),list):
        for key in reasons:
            if key!='pacing' or occupancy is None:
                reasons[key]='Retained component score; its original rating/cue provenance is unavailable.'
    grounded={r.get('criterion'):r for r in evidence.get('grounded_ratings',[]) if isinstance(r,dict)}
    for metric,criterion in {'hook':'opening_quality','engagement':'value','visual':'visual_relevance','ending':'ending_completeness'}.items():
        if criterion in grounded:
            row=grounded[criterion]
            reasons[metric]=f"Source-grounded provider judgment: {row['reason']} Evidence: {', '.join(row['evidence_ids'])}."
    if any(key in grounded for key in ('context_completeness','narrative_progression')):
        reasons['story']=' '.join(grounded[key]['reason'] for key in ('context_completeness','narrative_progression') if key in grounded)
    for key,value in result['metrics'].items():
        if value is None: reasons[key]='Not assessed: no valid retained evidence for this metric.'
    improvements=[]
    notes=report.get('notes') or []
    notes=[n for n in notes if isinstance(n,str)] if isinstance(notes,list) else []
    if any('earlier context' in n for n in notes):
        improvements.append('Review opening context: an English pronoun/conjunction cue may depend on earlier speech.')
    if result['metrics']['ending'] is not None and evidence.get('sentence_ending') is False:
        improvements.append('Review the last thought: sentence-ending punctuation was not found.')
    gap=evidence.get('max_speech_gap')
    if isinstance(gap,(int,float)) and math.isfinite(gap) and gap>1.2:
        improvements.append(f'Review the {gap:.2f}s transcript gap; the pause may be intentional.')
    if result['metrics']['hook'] is not None and result['metrics']['hook']<50:
        improvements.append('Review the opening: its retained hook rating/cues are weak; preserve source meaning.')
    if result['metrics']['engagement'] is not None and result['metrics']['engagement']<50:
        improvements.append('Review emotional engagement; its retained rating is below 50, without a measured audience outcome.')
    if result['metrics']['visual'] is not None and result['metrics']['visual']<50:
        improvements.append('Review visual interest; its inspected-footage rating is below 50. Cropping was not measured by this score.')
    assessed=[key for key,v in result['metrics'].items() if v is not None]
    strongest=max(assessed,key=lambda key:result['metrics'][key]) if assessed else None
    summary=(f'Highest assessed factor: {strongest} ({result["metrics"][strongest]:g}/100). '
             f'{result["coverage_percent"]:g}% of configured weight has evidence.' if strongest else
             'Insufficient retained evidence to calculate a quality score.')
    result.update(scoring_version=VERSION,base_score=result['overall'],reasons=reasons,
        improvements=improvements,summary=summary,adjustments={},
        evidence=_safe_evidence(evidence),detected_hook=report.get('opening_text') or None,
        strongest_moment=None,method='Initial editorial heuristics; not a prediction of views or viral success.')
    raw=[components,evidence,report.get('opening_text'),report.get('ending_text'),report.get('source_range'),result['weights'],VERSION]
    result['analysis_digest']=hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest()
    return result


def adjust(report,name,deduction,reason=None):
    """Idempotent named adjustments retain an auditable weighted base score."""
    report['adjustments'][name]=round(max(0,min(100,deduction)),2)
    report['overall']=(round(max(0,min(100,report['base_score']-sum(report['adjustments'].values()))),1)
                       if report['base_score'] is not None else None)
    if reason and deduction and reason not in report['improvements']: report['improvements'].append(reason)
    return report


def source_ranges(clip):
    rows=(clip.get('recipe') or {}).get('segments') or [clip]
    result=[]
    for row in rows:
        try:
            a,b=float(row['start']),float(row['end'])
            if math.isfinite(a) and math.isfinite(b) and 0<=a<b: result.append((a,b))
        except (KeyError,ValueError,TypeError): pass
    return result


def redundancy(clip,other):
    left,right=source_ranges(clip),source_ranges(other)
    if not left or not right: return 0
    overlap=sum(max(0,min(b,d)-max(a,c)) for a,b in left for c,d in right)
    duration=min(sum(b-a for a,b in left),sum(b-a for a,b in right))
    if duration and overlap/duration>.65: return 100
    def tokens(c):
        return set(re.findall(r'\w+',str((c.get('selection_report') or {}).get('ending_text') or '').lower()))
    a,b=tokens(clip),tokens(other)
    return 100*len(a&b)/len(a|b) if len(a)>=6 and len(b)>=6 else 0


def strongest_moment(clip,visual_moments):
    ranges=source_ranges(clip);candidates=[];elapsed=0
    for a,b in ranges:
        for moment in visual_moments:
            if not isinstance(moment,dict): continue
            rating=score(moment.get('score',moment.get('predicted_score')))
            try: start,end=float(moment['start']),float(moment['end'])
            except (KeyError,ValueError,TypeError): continue
            if rating is not None and math.isfinite(start) and math.isfinite(end) and start<end and min(b,end)>max(a,start):
                at=max(a,start)
                candidates.append(dict(source_time=at,clip_time=round(elapsed+at-a,3),
                    text=str(moment.get('event') or moment.get('visual_evidence') or 'Inspected source moment'),
                    rating=rating,basis='Highest-rated overlapping inspected moment; not frame-level salience.'))
        elapsed+=b-a
    return max(candidates,key=lambda m:m['rating']) if candidates else None


def rescore_clips(clips,transcript=None,visual_moments=(),weights=None):
    """Keep every clip and all media/settings intact; recompute saved evidence."""
    from clip_selection import score_story,speech_units
    import recut
    weights=normalize_weights(weights if weights is not None else configured_weights())
    ranges=[p for c in clips for p in source_ranges(c)]
    ends=[b for a,b in ranges]+[1]
    for segment in (transcript or {}).get('segments',[]):
        try:
            value=float(segment['end'])
            if math.isfinite(value) and value>0: ends.append(value)
        except (ValueError,TypeError,KeyError): pass
    duration=max(ends)
    units=speech_units(transcript,duration)
    output=[]
    for i,original in enumerate(clips):
        clip=copy.deepcopy(original);parts=source_ranges(clip)
        if transcript and parts:
            if (clip.get('recipe') or {}).get('segments'):
                mapped=recut.virtual_transcript(transcript,[dict(start=a,end=b) for a,b in parts])
                length=sum(b-a for a,b in parts)
                evidence=score_story(dict(clip,start=0,end=length),speech_units(mapped,length),visual_moments=())
            else:
                evidence=score_story(clip,units,visual_moments)
        else:
            evidence=copy.deepcopy(clip.get('selection_report') or {})
            if not isinstance(evidence,dict) or not isinstance(evidence.get('components'),dict):
                evidence={'components':{},'evidence':{}}
        report=explain(evidence,weights)
        original_adjustments=(clip.get('ranking_report') or {}).get('adjustments') or {}
        duration_adjustment=score(original_adjustments.get('duration_target'))
        if duration_adjustment is not None: adjust(report,'duration_target',min(12,duration_adjustment))
        report['strongest_moment']=strongest_moment(clip,visual_moments)
        ident=clip.get('clip_index')
        report['clip_index']=ident if isinstance(ident,int) and not isinstance(ident,bool) and ident>=0 else i
        evidence['ranking']=report
        clip.update(selection_report=evidence,ranking_report=report,selection_score=report['overall'],ranking_stale=False)
        output.append(clip)
    ordered=sorted(enumerate(output),key=lambda row:(-(row[1]['ranking_report']['base_score'] or 0),row[0]))
    previous=[]
    for _,clip in ordered:
        if previous:
            value,match=max(((redundancy(clip,other),other) for other in previous),key=lambda row:row[0])
            if value:
                adjust(clip['ranking_report'],'redundancy',value*.1,
                    f'Similar to clip {match["ranking_report"]["clip_index"]+1}: source overlap or matching ending speech ({value:.1f}/100).')
        clip['selection_score']=clip['ranking_report']['overall']
        clip['selection_report']['score']=clip['selection_score']
        previous.append(clip)
    for rank,clip in enumerate(sorted(output,key=lambda c:-(c['selection_score'] or 0)),1):
        story=clip.get('story_report')
        if not isinstance(story,dict):continue
        recorded=story.get('source_ranges') or [{'start':story.get('start'),'end':story.get('end')}]
        if recorded != [{'start':a,'end':b} for a,b in source_ranges(clip)]:
            story['stale']=True
            continue
        story.update(score=clip['selection_score'],rank=rank)
    return output
