#!/usr/bin/env python3
"""Rebuild derived AI coverage from measured task records, without re-running scans.

This fixes old report aggregates that counted accepted partial output as skipped.
It never creates findings, measurements, cases, task results or verification facts.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings
from app.core.models import Report
from app.core.store import Store
from app.pipeline.runner import ai_task_status
from app.pipeline.scoring import score_report

path = ROOT / "samples/juice-shop-report.json"
report = Report.model_validate_json(path.read_text())
original = {s.id: s.status for s in report.steps}
selectors = {
    "ai_map": lambda t: t['name'].startswith('Page classification') or t['name'] == 'Key user flow discovery',
    "triage": lambda t: t['name'].startswith('Security triage'),
    "vision": lambda t: t['name'].startswith('Visual review'),
}
for step in report.steps:
    if step.id not in selectors or step.status == 'blocked':
        continue
    tasks = [t for t in report.ai_tasks if selectors[step.id](t)]
    if tasks:
        corrected = ai_task_status(tasks)
        if step.status != corrected:
            step.status = corrected
            step.detail = f"Recorded {sum(t['status']=='completed' for t in tasks)} completed and {sum(t['status']=='partial' for t in tasks)} partially applied local-AI tasks. See the unchanged per-task ledger."
report.scores, report.overall_score, report.coverage, report.partial = score_report(
    report.selected_pillars, report.findings, report.steps, report.metrics)
report.partial |= any(t['status'] != 'completed' for t in report.ai_tasks)
if original != {s.id: s.status for s in report.steps}:
    note = "Derived AI-stage coverage was rebuilt from the original recorded task statuses; no scan, finding, measurement or verification result was invented."
    report.limitations.append(note)
    report.limitations = [x for x in report.limitations if not x.startswith('Local security triage: skipped.')]
    manifest = ROOT / 'samples/execution-manifest.json'
    m = json.loads(manifest.read_text())
    m['derived_coverage_rebuild'] = {'original_statuses': original, 'note': note}
    manifest.write_text(json.dumps(m, indent=2))
payload = report.model_dump(mode='json')
path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
settings = Settings()
Store(settings.db_path).update(report.id, report=payload)
job_report = settings.data_dir / 'jobs' / report.id / 'report.json'
if job_report.exists():
    job_report.write_text(json.dumps(payload, indent=2))
print(f'Preserved measured report {report.id}; derived coverage {report.coverage}% / score {report.overall_score}')
