"""XLSX export tests. Real-scan data = shipped sample reports; the minimal/hostile reports are synthetic."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api.xlsx_export import SHEETS, render_xlsx, safe
from app.core.config import Settings
from app.core.models import CreateJob
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [p for p in (ROOT / "reports" / "sample" / "practice-shop-report.json", ROOT / "samples" / "juice-shop-report.json") if p.exists()]


def open_wb(data: bytes):
    return load_workbook(io.BytesIO(data))


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_real_report_workbook_opens_and_matches_report(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    wb = open_wb(render_xlsx(report))
    assert wb.sheetnames == SHEETS
    findings = wb["All Findings"]
    assert findings.max_row - 1 == len(report["findings"])
    assert [c.value for c in findings[1]][:2] == ["Finding ID", "Title"]
    assert findings.freeze_panes == "A2" and findings.auto_filter.ref
    ids = {findings.cell(r, 1).value for r in range(2, findings.max_row + 1)}
    assert ids == {f["id"] for f in report["findings"]}
    summary = {wb["Executive Summary"].cell(r, 1).value: wb["Executive Summary"].cell(r, 2).value for r in range(2, wb["Executive Summary"].max_row + 1)}
    assert summary["Target URL"] == report["url"] and summary["Total findings"] == len(report["findings"])
    assert summary["Coverage (%)"] == report["coverage"]
    # Excel agrees with the JSON report on pillar totals (same underlying data, no recalculation)
    sec_rows = sum(1 for f in report["findings"] if f["pillar"] == "security")
    acc_rows = sum(1 for f in report["findings"] if f["pillar"] == "accessibility")
    assert wb["Accessibility and UX"].max_row - 1 >= acc_rows if acc_rows else True
    assert wb["Security"].max_row - 1 >= sec_rows


def test_empty_report_shows_not_run_never_fabricated_data():
    wb = open_wb(render_xlsx({"id": "x", "url": "http://x.test/", "findings": [], "steps": [], "pages": [], "test_cases": [], "ai_tasks": [], "scores": {}, "overall_score": None, "coverage": 0}))
    assert wb.sheetnames == SHEETS
    for name in ("Functional Tests", "Performance", "AI Model Details"):
        assert wb[name].cell(2, 1).value.startswith("Not Run"), name
    assert "Not scored" in wb["Executive Summary"]["B6"].value


def test_formula_injection_and_illegal_characters_neutralised():
    nasty = {"id": "z", "url": "http://x.test/", "findings": [{"id": "f1", "title": '=HYPERLINK("http://evil","x")', "pillar": "security", "severity": "High", "status": "Possible",
             "category": "c", "location": {"url": "+cmd", "selector": "@SUM(1)"}, "evidence": [{"detail": "-2+3\x00\x07 bell"}], "explanation": "\u65e5\u672c\u8a9e \u00dcnic\u00f6de", "suggested_fix": "x" * 40000, "sources": ["s"]}],
             "steps": [], "pages": [], "test_cases": [], "ai_tasks": [], "scores": {}}
    ws = open_wb(render_xlsx(nasty))["All Findings"]
    assert ws["B2"].value.startswith("'=") and ws["G2"].value.startswith("'+") and ws["H2"].value.startswith("'@")
    assert "\x00" not in ws["K2"].value and ws["K2"].value.startswith("'-")
    assert ws["J2"].value == "\u65e5\u672c\u8a9e \u00dcnic\u00f6de" and len(ws["L2"].value) <= 30000
    assert all(c.data_type != "f" for row in ws.iter_rows() for c in row)  # no cell is stored as a formula


def test_safe_helper_passes_numbers_through():
    assert safe(5) == 5 and safe(None) is None and safe("ok") == "ok" and safe("=1+1") == "'=1+1"


def test_api_xlsx_download_uses_stored_report(tmp_path):
    app = create_app(Settings(allowlist="http://lab.test:3000", data_dir=tmp_path), run_worker=False)
    job = app.state.store.create_job(CreateJob(url="http://lab.test:3000/"))
    report = {"id": job["id"], "url": "http://lab.test:3000/", "findings": [], "steps": [], "pages": [], "test_cases": [], "ai_tasks": [], "scores": {}, "overall_score": None, "coverage": 0}
    app.state.store.update(job["id"], status="completed", report=report)
    with TestClient(app) as client:
        res = client.get(f"/api/reports/{job['id']}/export/xlsx")
        assert res.status_code == 200 and res.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert res.headers["content-disposition"].endswith('.xlsx"')
        assert open_wb(res.content).sheetnames == SHEETS
