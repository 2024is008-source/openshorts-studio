import json
import pytest
from adaptive_analysis.benchmark import evaluate,COVERAGE,MODES


def test_all_categories_and_three_modes_without_fabricating_human_metrics(tmp_path):
    path=tmp_path/'artifact.json';path.write_text(json.dumps(dict(moments=[dict(start=2,end=10)],metrics=dict(requests={'text':1,'visual':0},video_seconds=0))))
    samples=[dict(id=category,category=category,reference_origin='synthetic',references=[dict(start=2,end=10)],artifacts={mode:path.name for mode in MODES}) for category in COVERAGE]
    report=evaluate(dict(synthetic=True,samples=samples),tmp_path)
    assert len(report['results'])==21 and not report['missing_categories']
    assert not report['acceptance_ready'] and all(r['candidate_recall']==1 for r in report['results'])
    assert all(r['human_preference'] is None and r['false_event_claims'] is None and r['upload_seconds'] is None for r in report['results'])


def test_missing_artifacts_and_unreviewed_labels_never_pass_acceptance(tmp_path):
    report=evaluate(dict(samples=[dict(id='one',category='challenge',references=[dict(start=0,end=5)],artifacts={})]),tmp_path)
    assert not report['acceptance_ready'] and report['missing_categories']
    assert all(r['status']=='missing_artifact' for r in report['results'])


def test_invalid_reference_bounds_are_rejected(tmp_path):
    with pytest.raises(ValueError):evaluate(dict(samples=[dict(id='bad',category='football',references=[dict(start=2,end=1)])]),tmp_path)
