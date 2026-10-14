"""Transparent, deterministic, coverage-aware scoring — never an AI invented score."""
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

from app.core.models import Finding, Pillar, PillarScore, Severity, Step

PENALTIES = {Severity.CRITICAL: 24, Severity.HIGH: 12, Severity.MEDIUM: 6, Severity.LOW: 2, Severity.INFO: 0}
ASSESSED = {"completed", "partial"}
FINISHED = {"completed", "partial", "skipped", "blocked", "failed"}


def fingerprint(finding: Finding) -> tuple:
    loc = finding.location
    parts = urlsplit(loc.url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment))
    # A header's root cause doesn't change because a scanner gave it a 'param' selector.
    selector = "" if loc.header else (loc.selector or "")
    return (finding.pillar, finding.category, url, (loc.header or "").lower(), selector)


def merge_into(target: Finding, source: Finding):
    target.sources = list(dict.fromkeys(target.sources + source.sources))
    seen = {(e.kind, e.detail, e.file) for e in target.evidence}
    target.evidence += [e for e in source.evidence if (e.kind, e.detail, e.file) not in seen]
    if source.status == "Verified":
        target.status = "Verified"
        target.verification_note = source.verification_note
    if PENALTIES[source.severity] > PENALTIES[target.severity]:
        target.severity = source.severity
    target.ai_assisted = target.ai_assisted or source.ai_assisted


def deduplicate(findings: list[Finding]) -> list[Finding]:
    result = {}
    for finding in findings:
        key = fingerprint(finding)
        if key in result:
            merge_into(result[key], finding)
        else:
            result[key] = finding
    return list(result.values())


def apply_ai_merges(findings: list[Finding], groups) -> list[Finding]:
    lookup = {f.id: f for f in findings}
    removed = set()
    for group in groups:
        candidates = [lookup[x] for x in group.ids if x in lookup and x not in removed]
        if len(candidates) < 2:
            continue
        first = candidates[0]
        # Same scope/category/element must be corroborated. A model cannot merge unrelated defects.
        if any(fingerprint(c) != fingerprint(first) for c in candidates[1:]):
            continue
        for duplicate in candidates[1:]:
            merge_into(first, duplicate)
            removed.add(duplicate.id)
    return [f for f in findings if f.id not in removed]


def pillar_penalty(findings: list[Finding]) -> float:
    groups = defaultdict(list)
    for finding in findings:
        groups[finding.category].append(finding)
    total = 0.0
    for items in groups.values():
        largest = max(PENALTIES[f.severity] * (1 if f.status == "Verified" else .5) for f in items)
        spread = min(len({fingerprint(f) for f in items}) - 1, 4)
        # Cap repeated instances of the same root cause rather than punishing tool duplicates.
        total += largest * (1 + .15 * spread)
    return total


def score_report(selected: list[Pillar], findings: list[Finding], steps: list[Step], metrics: dict):
    scores = {}
    for pillar in Pillar:
        own_steps = [s for s in steps if s.pillar == pillar]
        issues = [f for f in findings if f.pillar == pillar]
        assessed = [s for s in own_steps if s.status in ASSESSED]
        complete = sum(s.status == "completed" for s in own_steps)
        coverage = round(sum(1 if s.status == "completed" else .5 if s.status == "partial" else 0 for s in own_steps) / max(1, len(own_steps)) * 100)
        if pillar not in selected:
            scores[pillar] = PillarScore(score=None, status="not_selected", coverage=0, completed_checks=0, total_checks=0, issues=0)
        elif not assessed:
            status = "blocked" if any(s.status == "blocked" for s in own_steps) else "unassessed"
            scores[pillar] = PillarScore(score=None, status=status, coverage=0, completed_checks=0, total_checks=len(own_steps), issues=len(issues))
        else:
            score = max(0, min(100, round(100 - pillar_penalty(issues))))
            lighthouse = metrics.get("lighthouse", {}).get("lighthouse_score")
            if pillar == Pillar.PERFORMANCE and isinstance(lighthouse, (int, float)):
                score = min(score, round(lighthouse))
            scores[pillar] = PillarScore(score=score, status="complete" if complete == len(own_steps) else "partial",
                                        coverage=coverage, completed_checks=complete, total_checks=len(own_steps), issues=len(issues))
    assessed_scores = [s.score for p, s in scores.items() if p in selected and s.score is not None]
    overall = round(sum(assessed_scores) / len(assessed_scores)) if assessed_scores else None
    selected_steps = [s for s in steps if s.pillar is None or s.pillar in selected]
    coverage = round(sum(1 if s.status == "completed" else .5 if s.status == "partial" else 0 for s in selected_steps) / max(1, len(selected_steps)) * 100)
    partial = any(s.status != "completed" for s in selected_steps)
    return scores, overall, coverage, partial


def rank(findings: list[Finding]) -> list[Finding]:
    order = {s: i for i, s in enumerate([Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO])}
    return sorted(findings, key=lambda f: (order[f.severity], f.status != "Verified", f.pillar, f.location.url, f.title))
