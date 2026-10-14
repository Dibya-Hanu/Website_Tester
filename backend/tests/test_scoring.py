from app.core.models import Pillar, Severity, Step
from app.pipeline.scoring import deduplicate, score_report


def test_dedup_retains_sources_evidence_and_verification(make_finding):
    one = make_finding()
    two = make_finding(status="Verified", sources=["independent scanner"])
    output = deduplicate([one,two])
    assert len(output) == 1
    assert output[0].status == "Verified"
    assert output[0].sources == ["test scanner","independent scanner"]


def test_refused_pillar_is_unassessed_not_100(make_finding):
    steps = [Step(id="s",title="security",pillar=Pillar.SECURITY,status="blocked"),
             Step(id="p",title="performance",pillar=Pillar.PERFORMANCE,status="completed")]
    scores, overall, coverage, partial = score_report([Pillar.SECURITY,Pillar.PERFORMANCE], [], steps, {})
    assert scores[Pillar.SECURITY].score is None
    assert scores[Pillar.SECURITY].status == "blocked"
    assert overall == 100 and partial and coverage == 50


def test_lighthouse_caps_performance_score():
    scores, overall, _, _ = score_report([Pillar.PERFORMANCE], [], [Step(id="p",title="Lighthouse",pillar=Pillar.PERFORMANCE,status="completed")], {"lighthouse":{"lighthouse_score":61}})
    assert scores[Pillar.PERFORMANCE].score == 61 and overall == 61


def test_possible_penalized_less_than_verified(make_finding):
    steps = [Step(id="s",title="scan",pillar=Pillar.SECURITY,status="completed")]
    one = make_finding(status="Possible", severity=Severity.HIGH)
    two = make_finding(status="Verified", severity=Severity.HIGH)
    possible = score_report([Pillar.SECURITY],[one],steps,{})[1]
    verified = score_report([Pillar.SECURITY],[two],steps,{})[1]
    assert possible > verified


def test_no_selected_pillar_assessed_overall_null():
    scores, overall, coverage, partial = score_report([Pillar.SECURITY], [], [Step(id="s",title="scan",pillar=Pillar.SECURITY,status="skipped")], {})
    assert overall is None and scores[Pillar.SECURITY].score is None
    assert partial and coverage == 0
