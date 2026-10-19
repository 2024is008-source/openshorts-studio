"""
Pure helpers for the Gemini clip-selection pipeline.

Standard-library only so both main.py and gemini_worker.py can import it and
the logic stays unit-testable without the heavy video dependencies.
"""

import hashlib
import json
import math
import os
import re

# USD per 1M tokens (input, output incl. thinking), from ai.google.dev pricing.
MODEL_PRICES = {
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.5-flash-lite-lite": (0.10, 0.40),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),  # deprecated (shut down 2026-06-01)
}


def lookup_model_prices(model_name):
    """Longest-prefix match against MODEL_PRICES; None if unknown."""
    name = str(model_name or "").lower()
    best_key = None
    for key in MODEL_PRICES:
        if name.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return MODEL_PRICES[best_key] if best_key else None


def clip_count_targets(n_windows):
    """How many clips to ask the detail pass for, given the shortlist size.

    Measured on prod 3-ago-2026: 408 of 429 jobs (95%) delivered 3 clips or
    fewer, the mode being ONE, while the prompt was free to return one per
    shortlisted window. Users who received 1-3 clips came back a second day
    0.4% of the time; those who received 4-9 came back 16.1% — so the clip
    count, not the clip quality, is what the retention curve hangs on.

    The old prompt biased hard the other way ("prefer one great clip per
    candidate window") and handed the model two unbounded licences to drop
    clips (the 2-second rule and STANDS ALONE both end in "or skip it"), with
    no floor to stop it collapsing to a single clip. This puts a floor and a
    realistic ceiling on it instead.

    ``CLIP_TARGET_MIN`` / ``CLIP_TARGET_MAX`` override both for A/B runs
    without a deploy (the reframe-testing harness drives them).
    """
    import os

    n = max(1, int(n_windows or 1))
    # Floor grows with the material: 3 windows -> 3, 5 -> 4, 10+ -> 6.
    low = max(2, min(6, n // 2 + 2))
    # Ceiling allows a rich window to yield more than one without inviting padding.
    high = min(12, max(4, n * 2))
    low = min(low, high)

    def _override(name, current):
        raw = os.environ.get(name)
        if not raw:
            return current
        try:
            return max(1, int(raw))
        except ValueError:
            return current

    low = _override("CLIP_TARGET_MIN", low)
    high = _override("CLIP_TARGET_MAX", high)
    return low, max(low, high)


def trim_to_best(shorts, max_clips):
    """Cut an over-long detail-pass result down to ``max_clips`` BY SCORE.

    The detail pass hands its clips back in transcript order, batch after
    batch, so slicing the list keeps the EARLIEST clips rather than the best
    ones. On a 9-minute walkthrough that quietly threw away everything past
    minute three: the model proposed clips across the whole video, and the
    ones covering the demo, the MCP walkthrough and the close were the tail
    that got dropped. Worse, the failure scales the wrong way — the more
    generous the model is, the more of the video disappears.

    That sabotages the windowing: get_viral_clips builds scoring windows
    precisely because "a single call over the whole transcript clusters picks
    near the start", and a positional slice puts the clustering right back.

    Ranking is by ``predicted_score`` (the detail prompt already asks for it,
    and nothing else was reading it here). Ties keep transcript order, and the
    survivors come back in transcript order too, so clip numbering still runs
    front to back the way every caller downstream expects.
    """
    max_clips = max(1, int(max_clips or 1))
    if len(shorts) <= max_clips:
        return list(shorts)

    def score(item):
        try:
            value = float(item[1].get("selection_score", item[1].get("predicted_score")) or 0)
            return value if math.isfinite(value) else 0.0
        except (TypeError, ValueError, AttributeError):
            return 0.0

    indexed = list(enumerate(shorts))
    best = sorted(indexed, key=score, reverse=True)[:max_clips]
    return [item for _, item in sorted(best, key=lambda pair: pair[0])]


def clip_duration_bounds():
    """The clip length band (seconds) the selection prompts and word-snapping
    enforce. ``CLIP_MIN_SECONDS`` / ``CLIP_MAX_SECONDS`` override the classic
    15-60 — set per job by /api/process when the user asks for a specific
    length, or by hand for A/B runs. Values are clamped to platform-sane
    limits and re-ordered so bad input degrades instead of breaking the job.
    """
    import os

    def _read(name, default):
        try:
            value = float(os.environ.get(name, ""))
            return value if math.isfinite(value) else default
        except ValueError:
            return default

    lo = _read("CLIP_MIN_SECONDS", 15.0)
    hi = _read("CLIP_MAX_SECONDS", 60.0)
    lo = min(max(lo, 5.0), 175.0)
    hi = min(max(hi, 10.0), 180.0)
    if hi < lo + 5.0:  # keep a real band: degenerate ranges starve the model
        hi = min(180.0, lo + 5.0)
    return round(lo, 3), round(hi, 3)


def compact_words(words, precision=2):
    """Round word timestamps for prompts — full float precision wastes tokens."""
    return [
        {
            "w": w.get("w", ""),
            "s": round(float(w.get("s", 0)), precision),
            "e": round(float(w.get("e", 0)), precision),
        }
        for w in words
    ]


def build_transcript_windows(transcript_result, video_duration,
                             window_seconds=90, overlap_seconds=30):
    """
    Build scoring windows aligned to Whisper segment boundaries, so a sentence
    (and usually a viral moment) is never cut in half mid-window. Windows grow
    segment by segment to roughly window_seconds (up to 1.25x for the closing
    segment) and the next window starts ~overlap_seconds before the previous
    end, also snapped to a segment start.
    """
    segments = []
    for segment in transcript_result.get("segments", []):
        if not isinstance(segment,dict): continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        if not valid_range(segment.get('start'),segment.get('end'),video_duration):
            continue
        segments.append((float(segment.get("start", 0)), float(segment.get("end", 0)), text))
    segments.sort()

    windows = []
    window_index = 1
    i = 0
    n = len(segments)
    while i < n:
        w_start = segments[i][0]
        j = i
        # Extend while the NEXT segment still fits within a tolerant cap, so the
        # window closes on a segment boundary near window_seconds.
        while j + 1 < n and segments[j + 1][1] - w_start <= window_seconds * 1.25:
            j += 1
            if segments[j][1] - w_start >= window_seconds:
                break
        w_end = segments[j][1]
        windows.append({
            "id": f"window_{window_index:03d}",
            "start": round(w_start, 3),
            "end": round(w_end, 3),
            "text": " ".join(seg[2] for seg in segments[i:j + 1]),
        })
        window_index += 1

        if j >= n - 1:
            break
        # Next window starts at the first segment beginning after (end - overlap),
        # but always makes progress.
        target = w_end - overlap_seconds
        k = i + 1
        while k <= j and segments[k][0] < target:
            k += 1
        i = max(k, i + 1)

    if not windows:
        windows.append({
            "id": "window_001",
            "start": 0.0,
            "end": round(float(video_duration), 3),
            "text": str(transcript_result.get("text", "") or ""),
        })
    return windows


def snap_clip_to_words(start, end, words, video_duration,
                       min_duration=15.0, max_duration=60.0,
                       search_window=1.5, max_lead=0.35, max_tail=0.45):
    """
    Snap Gemini-proposed clip boundaries onto real word boundaries plus a bit
    of the surrounding silence. LLMs are bad at millisecond arithmetic; the
    word-level timestamps are ground truth, so cuts land in pauses instead of
    mid-word.

    words: [{'w','s','e'}, ...] for the whole video, sorted by start.
    Returns (start, end); falls back to the input if no words are nearby or
    snapping cannot satisfy the duration bounds.
    """
    original = (round(float(start), 3), round(float(end), 3))
    if not words:
        return original

    starts = [float(w.get("s", 0)) for w in words]
    ends = [float(w.get("e", 0)) for w in words]

    # START: snap to the nearest word start, then lead into the silence before it.
    new_start = float(start)
    candidates = [s for s in starts if abs(s - new_start) <= search_window]
    if candidates:
        word_start = min(candidates, key=lambda s: abs(s - new_start))
        prev_ends = [e for e in ends if e <= word_start]
        if prev_ends:
            gap = max(0.0, word_start - max(prev_ends))
            lead = min(max_lead, gap / 2)
        else:
            lead = max_lead
        new_start = max(0.0, word_start - lead)

    # END: snap to the nearest word end, then trail into the silence after it.
    new_end = float(end)
    candidates = [e for e in ends if abs(e - new_end) <= search_window]
    if candidates:
        word_end = min(candidates, key=lambda e: abs(e - new_end))
        next_starts = [s for s in starts if s >= word_end]
        if next_starts:
            gap = max(0.0, min(next_starts) - word_end)
            tail = min(max_tail, gap / 2)
        else:
            tail = max_tail
        new_end = min(float(video_duration), word_end + tail)

    # Repair duration bounds while staying on word boundaries.
    if new_end - new_start < min_duration:
        target = new_start + min_duration
        later = sorted(e for e in ends if e >= target)
        if later and later[0] - new_start <= max_duration:
            new_end = min(float(video_duration), later[0] + 0.2)
        else:
            return original
    if new_end - new_start > max_duration:
        target = new_start + max_duration
        earlier = [e for e in ends if new_start < e <= target]
        new_end = (max(earlier) + 0.2) if earlier else target
        new_end = min(new_end, new_start + max_duration, float(video_duration))

    if new_end <= new_start or new_end - new_start < min_duration:
        return original
    return (round(new_start, 3), round(new_end, 3))


STORY_SELECTION_VERSION = 3
_SENTENCE_END = re.compile(r'[.!?。！？][\s\"\'”’»)]*$')


class CandidateBatch(list):
    """Carry skipped window IDs through existing provider batch bisection."""
    def __init__(self, items=(), *, blocked=()):
        super().__init__(items)
        self.blocked=set(blocked)


def valid_range(start, end, duration):
    """Never coerce absent timestamps to zero or clamp invalid AI ranges."""
    try:
        if any(isinstance(v,bool) for v in (start,end,duration)): return False
        a, b, d = float(start), float(end), float(duration)
        return all(math.isfinite(v) for v in (a,b,d)) and 0 <= a < b <= d
    except (TypeError, ValueError, OverflowError):
        return False


def speech_units(transcript, duration):
    """Use punctuation and observed word gaps, retaining speaker/source timing.

    ASR segments without words remain usable, but text-only transcripts cannot
    establish boundaries. Timestamp gaps are a silence proxy, not a new VAD run.
    """
    units = []
    for segment in (transcript or {}).get('segments', []):
        if not isinstance(segment,dict): continue
        words = []
        for word in segment.get('words', []) or []:
            if not isinstance(word,dict): continue
            if valid_range(word.get('start'),word.get('end'),duration):
                words.append(dict(start=float(word['start']),end=float(word['end']),
                                  text=str(word.get('word') or '').strip()))
        words.sort(key=lambda w:w['start'])
        if not words:
            if valid_range(segment.get('start'),segment.get('end'),duration) and str(segment.get('text') or '').strip():
                units.append(dict(start=float(segment['start']),end=float(segment['end']),
                    text=str(segment['text']).strip(), complete=bool(_SENTENCE_END.search(str(segment['text']))),
                    speaker=segment.get('speaker'), timing='segment'))
            continue
        pending = []
        for i, word in enumerate(words):
            pending.append(word)
            gap = i+1 < len(words) and words[i+1]['start']-word['end'] >= 1.2
            punctuation = bool(_SENTENCE_END.search(word['text']))
            if punctuation or gap or i == len(words)-1:
                units.append(dict(start=pending[0]['start'],end=word['end'],
                    text=' '.join(w['text'] for w in pending),complete=punctuation,
                    speaker=segment.get('speaker'),timing='word',words=list(pending)))
                pending=[]
    merged=[]
    for unit in sorted(units,key=lambda u:(u['start'],u['end'])):
        if (merged and not merged[-1]['complete'] and
                merged[-1]['speaker']==unit['speaker'] and
                0<=unit['start']-merged[-1]['end']<=.6):
            previous=merged[-1]
            previous.update(end=unit['end'],text=previous['text']+' '+unit['text'],
                            complete=unit['complete'],timing='word' if previous['timing']==unit['timing']=='word' else 'segment')
            previous['words']=previous.get('words',[])+unit.get('words',[])
        else: merged.append(dict(unit))
    return merged


def story_boundaries(start, end, units, duration, minimum=15, maximum=60, scene_cuts=(), preserve_visual=False):
    """Extend to nearby complete speech; reject a sentence that cannot fit.

    Simultaneous speakers are handled as a union of intersecting speech. Never
    truncate a sentence just to repair a duration target. Quiet visual moments
    with no intersecting speech keep their original boundaries.
    """
    if not valid_range(start,end,duration): return None
    a,b=float(start),float(end)
    touched=[u for u in units if u['end']>a and u['start']<b]
    if touched:
        first,last=touched[0],max(touched,key=lambda u:u['end'])
        # A request starting deep inside a long sentence is unusable.
        if first['start']<a-3 or last['end']>b+6: return None
        a,b=first['start'],last['end']
        # Include overlapping speakers exposed by the extension as well.
        for _ in range(3):
            active=[u for u in units if u['end']>a and u['start']<b]
            na=max(0,min([a]+[u['start'] for u in active]))
            nb=min(duration,max([b]+[u['end'] for u in active]))
            if (na,nb)==(a,b): break
            a,b=na,nb
        if any(u['start'] < a < u['end'] or u['start'] < b < u['end'] for u in units): return None
        previous=max([0]+[u['end'] for u in units if u['end']<=a])
        following=min([duration]+[u['start'] for u in units if u['start']>=b])
        a=max(0,a-min(.15,(a-previous)/2))
        b=min(duration,b+min(.25,(following-b)/2))
        if preserve_visual:
            # A watched reaction/payoff may continue after the last spoken word.
            a=min(a,float(start));b=max(b,float(end))
    else:
        for key in ('start','end'):
            original=a if key=='start' else b
            nearby=[float(t) for t in scene_cuts if valid_range(0,t,duration) and abs(t-original)<=.4]
            if nearby:
                if key=='start': a=min(nearby,key=lambda t:abs(t-original))
                else: b=min(nearby,key=lambda t:abs(t-original))
    if not minimum <= b-a <= maximum: return None
    return round(a,3),round(b,3)


def score_story(clip, units, visual_moments=(), target=None):
    """Explainable editorial heuristics; unavailable evidence is explicitly null."""
    a,b=clip['start'],clip['end']
    speech=[u for u in units if u['end']>a and u['start']<b]
    opening=' '.join(' '.join(w['text'] for w in u['words'] if w['start']<a+3)
                     if u.get('words') else u['text'] for u in speech if u['start']<a+3)
    unresolved=bool(re.match(r'^(and|but|so|that|this|it|he|she|they)\b',opening,re.I))
    complete=bool(speech and speech[-1]['complete'])
    coverage=min(1,sum(max(0,min(b,u['end'])-max(a,u['start'])) for u in speech)/(b-a))
    visual=[m for m in visual_moments if valid_range(m.get('start'),m.get('end'),float('1e12'))
            and min(b,float(m['end']))>max(a,float(m['start'])) and m.get('visual_evidence')]
    ratings=clip.get('story_scores') or {}
    grounded=None
    if clip.get('story'):
        import story_director
        grounded=story_director.grounded_story(clip,units,visual_moments)
        ratings={story_director.STORY_METRICS[r['criterion']]:r['score'] for r in grounded['ratings']}
    def rating(name):
        from clip_ranking import score
        return score(ratings.get(name)) if isinstance(ratings,dict) else None
    components=dict(
        hook_strength=rating('hook_strength') if rating('hook_strength') is not None else (75 if re.search(r'[?？]|\d',opening) else 45 if opening else None),
        standalone_context=rating('standalone_context') if rating('standalone_context') is not None else (35 if unresolved else 70 if speech else None),
        narrative_completeness=rating('narrative_completeness') if rating('narrative_completeness') is not None else (75 if complete and not unresolved else 40 if speech else None),
        visual_interest=rating('visual_interest') if visual else None,
        emotional_engagement=rating('emotional_engagement'),
        pacing=round(100*coverage) if speech else None,
        ending_quality=rating('ending_quality') if rating('ending_quality') is not None else (85 if complete else 30 if speech else None))
    notes=[]
    if unresolved: notes.append('Opening may require earlier context (English lexical heuristic).')
    if speech and not complete: notes.append('Ending lacks sentence punctuation; review speech continuity.')
    if not speech: notes.append('No usable speech timing; narrative evidence is limited.')
    if not visual: notes.append('Visual interest was not inferred from transcript alone; emotion ratings, if present, are provider judgments.')
    intervals=sorted((max(a,u['start']),min(b,u['end'])) for u in speech)
    merged=[]
    for x,y in intervals:
        if merged and x<=merged[-1][1]: merged[-1][1]=max(y,merged[-1][1])
        else: merged.append([x,y])
    coverage=sum(y-x for x,y in merged)/(b-a)
    components['pacing']=round(coverage*100) if speech else None
    report=dict(components=components,notes=notes,source_range={'start':a,'end':b},
                opening_text=opening,ending_text=speech[-1]['text'] if speech else '',
                timing='word' if speech and all(u['timing']=='word' for u in speech) else 'segment' if speech else 'visual',
                evidence=dict(speech_coverage=round(coverage,3),sentence_ending=complete,
                    visual_context_available=bool(visual),provider_ratings=bool(ratings),
                    rating_fields=[key for key in components if rating(key) is not None],
                    max_speech_gap=round(max([right[0]-left[1] for left,right in zip(merged,merged[1:])]+[0]),3) if speech else None,
                    leading_pause=round(max(0,speech[0]['start']-a),3) if speech else None,
                    trailing_pause=round(max(0,b-speech[-1]['end']),3) if speech else None),
                scoring_method='editorial heuristics and optional provider ratings; not a view prediction')
    import clip_ranking
    if grounded:
        report['evidence'].update(story_mode=grounded['mode'],grounded_ratings=grounded['ratings'])
    ranking=clip_ranking.explain(report,clip_ranking.configured_weights())
    if target:
        clip_ranking.adjust(ranking,'duration_target',min(12,abs((b-a)-target)/target*12))
    ranking['strongest_moment']=clip_ranking.strongest_moment(clip,visual_moments)
    report.update(score=ranking['overall'],ranking=ranking)
    return report


def select_story_candidates(candidates, transcript, duration, minimum=15, maximum=60,
                            limit=12, visual_moments=(), scene_cuts=(), target=None,learning_context=None):
    if not valid_range(0,duration,duration):return []
    if duration<=minimum:minimum=min(.5,duration)
    units=speech_units(transcript,duration)
    prepared=[]
    for item in candidates:
        if not isinstance(item,dict): continue
        bounds=story_boundaries(item.get('start'),item.get('end'),units,duration,minimum,maximum,scene_cuts,
                                preserve_visual=bool(item.get('visual_evidence')))
        if bounds is None: continue
        clip={**item,'start':bounds[0],'end':bounds[1]}
        import story_director
        story=story_director.grounded_story(clip,units,visual_moments)
        if item.get('story'):
            # New responses cannot fall back to ungrounded legacy AI ratings.
            clip['story_scores']={story_director.STORY_METRICS[r['criterion']]:r['score'] for r in story['ratings']}
            clip['story']=story
        report=score_story(clip,units,visual_moments,target)
        clip.update(selection_score=report['score'],selection_report=report,ranking_report=report['ranking'])
        measured={r['criterion']:r for r in story['ratings']}
        clip['story_report']=dict(version=story_director.STORY_VERSION,start=bounds[0],end=bounds[1],
            mode=story['mode'],main_idea=story['idea'],evidence=story['evidence'],beats=story['beats'],
            main_idea_basis='Extractive source evidence; visual/audio descriptions are provider observations.',
            hook_suggestion=story['hook_quote'],ending_rationale=story['ending_note'],
            scores={key:measured.get(key) for key in story_director.STORY_METRICS},
            limitations=story['limitations'],score=report['score'])
        audio=[]
        for moment in visual_moments:
            if not isinstance(moment,dict):continue
            for row in moment.get('audio_context',[]):
                if (isinstance(row,dict) and valid_range(row.get('start'),row.get('end'),duration)
                        and row['end']>bounds[0] and row['start']<bounds[1] and row not in audio):audio.append(row)
        clip['story_report']['signals']=dict(scene_cuts=[t for t in scene_cuts if valid_range(bounds[0],t,bounds[1])],
            audio_context=audio,speech=report['evidence'])
        clip['story_mode']=story['mode']
        prepared.append(clip)
    from learning.highlight_ranking import apply as rank_highlights
    prepared=rank_highlights(prepared,**(learning_context or {}))
    limit=max(limit,sum(bool(c.get('learning_protected')) for c in prepared))
    def redundancy_for(clip,kept):
        tokens=set(re.findall(r'\w+',clip['selection_report']['ending_text'].lower()))
        redundancy=0
        for old in kept:
            overlap=max(0,min(clip['end'],old['end'])-max(clip['start'],old['start']))
            if overlap/min(clip['end']-clip['start'],old['end']-old['start'])>.65:
                redundancy=100;break
            other=set(re.findall(r'\w+',old['selection_report']['ending_text'].lower()))
            if len(tokens)>=6 and tokens and other:
                redundancy=max(redundancy,100*len(tokens&other)/len(tokens|other))
        return redundancy
    kept=[]
    while prepared and len(kept)<limit:
        def priority(c):
            learned=c.get('local_ranking') or {}
            value=learned.get('relevance_score')*100 if learned.get('score_kind')=='model_raw_score' else (c['selection_score'] or 0)
            return 1000+value if c.get('learning_protected') else value
        ranked=[(priority(c)-r*.1,-i,c,r) for i,c in enumerate(prepared)
                if (r:=redundancy_for(c,kept))<80 or c.get('learning_protected')]
        if not ranked: break
        adjusted,_,clip,redundancy=max(ranked,key=lambda row:row[:2])
        prepared.remove(clip)
        clip['selection_report']['redundancy']=round(redundancy,1)
        import clip_ranking
        clip_ranking.adjust(clip['ranking_report'],'redundancy',redundancy*.1,
                            'Similar ending speech to another selected candidate.' if redundancy else None)
        clip['selection_report']['score']=clip['ranking_report']['overall']
        clip['selection_score']=clip['ranking_report']['overall']
        clip['story_report'].update(score=clip['selection_score'],rank=len(kept)+1)
        clip['story_report']['scores']['redundancy']=dict(score=round(100-redundancy,1),
            reason='Distinctness from higher-ranked candidates using source overlap and retained ending-text similarity.',
            overlap_or_similarity=round(redundancy,1))
        kept.append(clip)
    return sorted(kept,key=lambda c:c['start'])


def fallback_story_candidates(transcript,duration,minimum=15,maximum=60,target=None):
    """Bounded source extracts; never fabricate dialogue, dates, or timestamps."""
    if not valid_range(0,duration,duration):return []
    if duration<=minimum:minimum=min(.5,duration)
    units=speech_units(transcript,duration)
    target=target or (minimum+maximum)/2
    rows=[]
    # Spread starts over the entire source, including its ending, at most 256.
    stride=max(1,math.ceil(len(units)/255))
    indices=sorted(set(range(0,len(units),stride))|({len(units)-1} if units else set()))
    for i in indices:
        first=units[i]
        endings=[]
        for last in units[i:]:
            length=last['end']-first['start']
            if length>maximum: break
            if length>=minimum and last['complete']: endings.append(last)
        if not endings: continue
        bounds=None
        for last in sorted(endings,key=lambda u:abs(u['end']-first['start']-target)):
            bounds=story_boundaries(first['start'],last['end'],units,duration,minimum,maximum)
            if bounds: break
        if bounds is None: continue
        quote=' '.join(first['text'].split()[:10])
        rows.append(dict(start=bounds[0],end=bounds[1],predicted_score=None,
            video_title_for_youtube_short=quote[:100],viral_hook_text=quote,
            video_description_for_tiktok='',video_description_for_instagram='',
            selection_origin='deterministic_transcript_fallback'))
    return rows


def selection_cache_key(transcript,duration,context,settings):
    payload=[STORY_SELECTION_VERSION,transcript,duration,context,settings]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
