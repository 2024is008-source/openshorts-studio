"""Independent local discovery, conservative fusion and explainable selection."""
import math
import statistics
from .runtime import digest

PADDING={'sports_highlights':(6,8),'challenge':(4,6),'cricket':(6,8),'football':(6,8),'general':(3,4)}


def local_candidates(index,category,limit=40):
    rows=index.get('motion') or [];audio=index.get('audio') or [];signals=[]
    values=[r['peak_change'] for r in rows];median=statistics.median(values) if values else 0
    deviations=[abs(v-median) for v in values];threshold=max(.025,median+3*(statistics.median(deviations) if deviations else 0))
    for row in rows:
        if row['peak_change']>threshold or row['peak_change']>=.08 and row['mean_change']>=.02:
            signals.append((row['start'],row['end'],'measured_image_change',min(1,row['peak_change']/max(threshold*2,.001))))
    for previous,row in zip(audio,audio[1:]):
        if row['relative_rms']-previous['relative_rms']>.4:signals.append((row['start'],row['end'],'relative_audio_novelty',.5))
    # A cut alone is not important; only retain cuts accompanying another measured cue.
    for scene in index.get('scenes',[]):
        if any(abs(a-scene['start'])<2 for a,b,kind,score in signals):
            signals.append((scene['start'],min(scene['end'],scene['start']+1),'cut_near_measured_activity',.35))
    for before,after in zip(index.get('speaker_turns') or [],(index.get('speaker_turns') or [])[1:]):
        if before['speaker']!=after['speaker']:signals.append((after['start'],after['end'],'retained_speaker_change',.35))
    lead,tail=PADDING.get('challenge' if category.startswith('challenge') else category,(2,3));duration=index['duration'];result=[]
    buckets={}
    for signal in signals:
        bucket=min(limit*2-1,int(signal[0]/max(duration,.001)*limit*2))
        if bucket not in buckets or signal[3]>buckets[bucket][3]:buckets[bucket]=signal
    for a,b,kind,score in sorted(buckets.values(),key=lambda s:s[0]):
        start=max(0,a-lead);end=min(duration,max(b+tail,start+6))
        if end-start<3:continue
        result.append(dict(id=digest(['local',start,end,kind])[:20],start=start,end=end,origins=['local_visual'],
            evidence=[dict(channel='local_measurement',kind=kind,start=a,end=b)],importance=score,
            visual_need='video',uncertainty=['Potential event window; action and sporting outcome not established.'],
            title='Unverified visual activity',story_complete=False))
    return fuse(result,duration,limit,category)


def fuse(candidates,duration,limit=40,category='general'):
    cleaned=[]
    for raw in candidates:
        a,b=raw.get('start'),raw.get('end')
        if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a+b) or not 0<=a<b<=duration:continue
        row={**raw,'start':float(a),'end':float(b),'origins':list(raw.get('origins',[])),
            'evidence':list(raw.get('evidence',[])),'uncertainty':list(raw.get('uncertainty',[]))}
        cleaned.append(row)
    merged=[]
    for row in sorted(cleaned,key=lambda r:(r['start'],r['end'])):
        old=merged[-1] if merged else None
        if old and row['start']<old['end'] and max(row['end'],old['end'])-old['start']<=90:
            old['end']=max(old['end'],row['end']);old['origins']=sorted(set(old['origins']+row['origins']))
            old['evidence']+=row['evidence'];old['importance']=max(old.get('importance',0),row.get('importance',0))
            old['uncertainty']=list(dict.fromkeys(old['uncertainty']+row['uncertainty']))
            # Expanding an interval invalidates a previously complete boundary judgment.
            old['story_complete']=False
            if row.get('visual_need') in ('video','context') or 'local_visual' in old['origins']:old['visual_need']='video'
        else:merged.append(row)
    # Reserve visual-only discovery slots rather than ranking every one below speech.
    local=[r for r in merged if 'local_visual' in r['origins'] and 'transcript' not in r['origins']]
    def diverse(values,count):
        bins={}
        for row in values:
            slot=min(count-1,int(row['start']/max(duration,.001)*count))
            if slot not in bins or row.get('importance',0)>bins[slot].get('importance',0):bins[slot]=row
        return list(bins.values())[:count]
    reserved=diverse(local,max(1,limit//3))
    rest=sorted((r for r in merged if r not in reserved),key=lambda r:(-r.get('importance',0),r['start']))
    chosen=reserved+rest[:max(0,limit-len(reserved))]
    for row in chosen:row['id']=digest([row['start'],row['end'],row['origins']])[:20]
    return sorted(chosen,key=lambda r:r['start'])[:limit]


def visual_decision(row,index,category):
    sports=category in ('cricket','football','sports_highlights')
    if sports or 'local_visual' in row['origins'] or row.get('visual_need') in ('video','context'):return 'video'
    if row.get('visual_need')=='frames':return 'frames'
    if row.get('visual_need')=='none' and 'transcript' in row['origins']:
        # Full-scene preservation is available even when no face/crop path exists.
        return 'none'
    return 'frames' if category.startswith('podcast') else 'video'


def rank(rows,index,category,limit=12,source_group=None):
    import clip_ranking
    import clip_selection
    transcript={'segments':[dict(start=u['start'],end=u['end'],text=u['text']) for u in index['units']]}
    accepted=[]
    for row in rows:
        if row.get('verification_status') not in ('text_grounded','model_observed'):continue
        if category in ('cricket','football','sports_highlights') and row.get('verification_status')!='model_observed':continue
        if row['end']-row['start']<3:continue
        # A topic title produced from ASR/local novelty cannot establish an outcome.
        # Visual clips use the inspected description, never the proposed event title.
        title=(row.get('visual_evidence') or 'Inspected source moment')[:100] if row['verification_status']=='model_observed' else (row.get('hook_quote') or 'Source speech excerpt')[:100]
        item=dict(row,video_title_for_youtube_short=title,viral_hook_text=row.get('hook_quote',''),
            video_description_for_tiktok='',video_description_for_instagram='',
            editing_kind='challenge' if category.startswith('challenge') else 'educational' if category=='podcast-education' else 'comedy' if category=='podcast-comedy' else 'podcast' if category.startswith('podcast') else 'general',
            selection_origin='adaptive_multimodal',layout_intent=row.get('layout_intent','preserve_scene'),preserve_context=row.get('preserve_context',True),
            layout_evidence=row.get('layout_evidence') or 'Conservative context-preserving policy; visual claims require an inspection receipt.')
        item=clip_ranking.rescore_clips([item],transcript,[item] if row.get('verification_status')=='model_observed' else [])[0]
        # Completeness is an explicit model judgment grounded by the retained
        # quote/visual evidence; these are editorial weights, not viral predictions.
        item['adaptive_priority']=float(row.get('importance',0))+.25*bool(row.get('story_complete'))+.15*(row['verification_status']=='model_observed')
        item['ranking_explanation']=f"Sources: {', '.join(row['origins'])}; {row['verification_status']}; "+('model judges the supplied idea complete; ASR remains uncertain.' if row.get('story_complete') else 'story completeness remains uncertain.')
        from category_intelligence import candidate_features
        item['category_features']=candidate_features(item,category)
        accepted.append(item)
    from learning.highlight_ranking import apply as rank_highlights
    accepted=rank_highlights(accepted,source_group,category)
    limit=max(limit,sum(bool(c.get('learning_protected')) for c in accepted))
    def priority(row):
        learned=row.get('local_ranking') or {}
        value=learned['relevance_score'] if learned.get('score_kind')=='model_raw_score' else row['adaptive_priority']
        return (1000 if row.get('learning_protected') else 0)+value
    selected=[]
    for row in sorted(accepted,key=lambda r:(-priority(r),r['start'])):
        if not row.get('learning_protected') and any(max(0,min(row['end'],r['end'])-max(row['start'],r['start']))/min(row['end']-row['start'],r['end']-r['start'])>.5 for r in selected):continue
        selected.append(row)
        if len(selected)>=limit:break
    return selected
