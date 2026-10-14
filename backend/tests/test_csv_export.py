"""CSV export tests. Fixtures are synthetic (not scan results)."""
import csv
import io

from fastapi.testclient import TestClient

from app.api.exports import CSV_COLUMNS, render_csv
from app.main import create_app


def finding(**kw):
    base = dict(id="f1", title="Broken, \"quoted\" link", pillar="functionality", severity="High", status="Verified",
                category="broken-link", location={"url": "http://x.test/a", "selector": "a#x", "header": None},
                evidence=[{"kind": "snippet", "detail": "line1\nline2, with comma", "file": None},
                          {"kind": "screenshot", "detail": "shot", "file": "p.png"}],
                explanation="Ünïcode – 日本語", suggested_fix="Fix it", sources=["crawler", "axe-core"],
                verification_note="re-tested", ai_assisted=False)
    base.update(kw)
    return base


def parse(text):
    return list(csv.DictReader(io.StringIO(text, newline="")))


def test_header_written_for_empty_report():
    rows = render_csv({"findings": []}).splitlines()
    assert rows == [",".join(CSV_COLUMNS)]


def test_commas_quotes_newlines_unicode_roundtrip():
    rows = parse(render_csv({"findings": [finding()]}))
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == 'Broken, "quoted" link'
    assert r["evidence"] == "line1\nline2, with comma\n---\nshot"
    assert r["explanation"] == "Ünïcode – 日本語"
    assert r["detection_sources"] == "crawler; axe-core"
    assert r["evidence_files"] == "p.png"
    assert r["affected_url"] == "http://x.test/a" and r["element"] == "a#x"
    assert r["confidence"] == "High" and r["verification_status"] == "Verified"


def test_possible_finding_gets_medium_confidence_and_ai_flag():
    r = parse(render_csv({"findings": [finding(status="Possible", ai_assisted=True)]}))[0]
    assert r["confidence"] == "Medium" and r["ai_assisted"] == "yes"


def test_formula_injection_neutralised():
    r = parse(render_csv({"findings": [finding(title="=HYPERLINK(\"http://evil\")", explanation="@SUM(A1)")]}))[0]
    assert r["title"].startswith("'=") and r["explanation"].startswith("'@")


def test_missing_optional_fields_do_not_crash():
    rows = parse(render_csv({"findings": [{"id": "z", "title": "t", "pillar": "security", "severity": "Low"}]}))
    assert rows[0]["finding_id"] == "z" and rows[0]["affected_url"] == ""


def test_api_csv_endpoint(settings):
    app = create_app(settings, run_worker=False)
    from app.core.models import CreateJob
    job = app.state.store.create_job(CreateJob(url="http://lab.test:3000/"))
    report = {"id": job["id"], "url": "http://lab.test:3000/", "findings": [finding()], "steps": [], "scores": {}}
    app.state.store.update(job["id"], status="completed", report=report)
    with TestClient(app) as client:
        res = client.get(f"/api/reports/{job['id']}/export/csv")
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        assert res.headers["content-disposition"].endswith('.csv"')
        assert res.text.startswith("\ufeff" + ",".join(CSV_COLUMNS))
        assert client.get(f"/api/reports/{job['id']}/export/xml").status_code == 400
