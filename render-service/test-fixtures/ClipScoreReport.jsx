import React from 'react';

const LABELS = { hook: 'Hook', story: 'Story completeness', engagement: 'Engagement', visual: 'Visual interest', pacing: 'Pacing', ending: 'Ending' };
function StoryEvidence({ story }) {
    if (!story) return null;
    if (story.stale) return <p className="text-xs text-muted">Story evidence predates the current timeline. New source analysis is needed for story explanations.</p>;
    return <details className="text-xs border border-rule rounded-input p-3 my-2">
        <summary className="cursor-pointer">Story evidence · {story.mode} · rank {story.rank ?? 'unassessed'}</summary>
        <p className="mt-2">{story.main_idea || 'No semantic story summary was established.'}</p>
        <p className="text-muted">{story.main_idea_basis}</p>
        <p className="mt-2">Hook suggestion: {story.hook_suggestion || 'No suitable complete opening quote.'}</p>
        <p className="mt-2">Ending: {story.ending_rationale}</p>
        <dl className="grid grid-cols-2 gap-1 mt-2">{Object.entries(story.scores || {}).map(([key, value]) => <React.Fragment key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt><dd>{value == null ? 'Not assessed' : `${value.score}/100 · ${value.reason}`}</dd>
        </React.Fragment>)}</dl>
        <p className="text-muted mt-2">Evidence uses original source timestamps. Observed expressions do not establish internal emotional states.</p>
        <ul className="space-y-2 mt-2">{(story.evidence || []).map((e, i) => <li key={i}>
            <span>{e.start.toFixed(2)}–{e.end.toFixed(2)}s · {e.channel === 'transcript' ? 'Source speech' : `Provider observation: ${e.channel}`}</span>
            <p>{e.channel === 'transcript' ? e.quote : e.description}</p>
        </li>)}</ul>
        {(story.limitations || []).map((text, i) => <p className="text-muted mt-2" key={i}>{text}</p>)}
    </details>;
}
export default function ClipScoreReport({ clip, onSeek }) {
    const report = clip.ranking_report;
    if (clip.ranking_stale) return <p className="text-xs text-muted my-2">Timeline or crop changed. Rescore saved analysis to update this clip’s editorial ranking.</p>;
    if (!report) return <><p className="text-xs text-muted my-2">No weighted breakdown is stored. Rescore saved analysis to assess available metrics.</p><StoryEvidence story={clip.story_report} /></>;
    const moment = report.strongest_moment;
    return <><StoryEvidence story={clip.story_report} /><div className="text-xs border border-rule rounded-input p-3 my-2">
        <p>{report.summary}</p>
        <p className="text-muted mt-1">Scoring v{report.scoring_version} · {report.coverage_percent}% evidence coverage · {report.method}</p>
        <details className="mt-2"><summary className="cursor-pointer">Score breakdown and reasons</summary>
            <div className="overflow-x-auto"><table className="w-full text-left mt-2"><thead><tr><th>Factor</th><th>Score</th><th>Weight</th><th>Reason</th></tr></thead>
                <tbody>{Object.entries(LABELS).map(([key, label]) => <tr key={key} className="align-top border-t border-rule">
                    <td className="py-2 pr-2">{label}</td><td>{report.metrics?.[key] == null ? 'Not assessed' : `${report.metrics[key]}/100`}</td>
                    <td className="px-2">{Number(report.weights?.[key] || 0).toFixed(1)}%</td><td>{report.reasons?.[key]}</td>
                </tr>)}</tbody></table></div>
            <p className="mt-2">Weighted base: {report.base_score ?? 'not assessed'}. Final: {report.overall ?? 'not assessed'}.</p>
            {Object.entries(report.adjustments || {}).filter(([, value]) => value > 0).map(([name, value]) => <p key={name}>{name.replaceAll('_', ' ')} adjustment: −{value} points</p>)}
            <p className="mt-2">Missing factors are excluded from the average. Scores with different evidence coverage need careful comparison.</p>
        </details>
        <p className="mt-2"><strong>Detected opening:</strong> {report.detected_hook || 'Not assessed from retained timed speech.'}</p>
        <p className="mt-2"><strong>Strongest inspected moment:</strong> {moment ? <>
            {moment.text} · source {moment.source_time.toFixed(2)}s · <button className="underline" onClick={() => onSeek?.(moment.clip_time)}>play at clip {moment.clip_time.toFixed(2)}s</button>
            <span className="block text-muted">{moment.basis}</span>
        </> : 'Not assessed; no rated moment with valid source timing was retained.'}</p>
        <details className="mt-2"><summary className="cursor-pointer">Suggested improvements</summary>
            {report.improvements?.length ? <ul className="list-disc pl-4 mt-2">{report.improvements.map((text, i) => <li key={i}>{text}</li>)}</ul>
                : <p className="mt-2">No specific issue was established by the retained evidence. This is not a claim that the clip is perfect.</p>}
        </details>
    </div></>;
}
