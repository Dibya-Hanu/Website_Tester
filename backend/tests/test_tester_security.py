"""Security regression tests for the tester itself (not the scanned site)."""
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.models import CreateJob
from app.main import create_app


def make(tmp_path, findings=None):
    app = create_app(Settings(allowlist="http://lab.test:3000", data_dir=tmp_path), run_worker=False)
    job = app.state.store.create_job(CreateJob(url="http://lab.test:3000/"))
    report = {"id": job["id"], "url": "http://lab.test:3000/", "findings": findings or [], "steps": [], "pages": [], "test_cases": [], "ai_tasks": [], "scores": {}, "overall_score": None, "coverage": 0,
              "created_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:01:00+00:00", "duration_seconds": 60, "selected_pillars": [], "authorized": False, "partial": True, "summary": "", "priorities": [],
              "limitations": [], "tool_versions": {}, "flows": [], "metrics": {}, "suppressed_findings": [], "schema_version": "1.0", "sample": False}
    app.state.store.update(job["id"], status="completed", report=report)
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    return app, job["id"]


def test_evidence_path_traversal_blocked(tmp_path):
    app, jid = make(tmp_path)
    with TestClient(app) as c:
        for bad in ("..%2f..%2fsecret.txt", "%2e%2e%2f%2e%2e%2fsecret.txt", "..\\..\\secret.txt", "/etc/passwd", "....//....//secret.txt"):
            r = c.get(f"/api/jobs/{jid}/evidence/{bad}")
            assert r.status_code in (400, 404, 422) and "TOP-SECRET" not in r.text, bad


def test_job_id_traversal_blocked(tmp_path):
    app, _ = make(tmp_path)
    with TestClient(app) as c:
        for bad in ("..", "..%2f..", "%2e%2e", "x/../../etc"):
            assert c.get(f"/api/jobs/{bad}/evidence/a.png").status_code in (400, 404, 422)
            assert c.get(f"/api/reports/{bad}/export/json").status_code in (400, 404, 422)


def test_hostile_finding_text_is_escaped_in_html_report(tmp_path):
    f = {"id": "x1", "title": "<script>alert('xss')</script>", "pillar": "security", "severity": "High", "status": "Possible", "category": "c", "location": {"url": "http://lab.test:3000/<img src=x onerror=alert(1)>"},
         "evidence": [{"kind": "snippet", "detail": "<script>alert(2)</script>"}], "explanation": "<b onmouseover=alert(3)>", "suggested_fix": "f", "sources": ["s"], "verification_note": "n"}
    app, jid = make(tmp_path, [f])
    with TestClient(app) as c:
        html = c.get(f"/api/reports/{jid}/export/html").text
    assert "<script>alert" not in html and "<img src=x" not in html and "<b onmouseover" not in html


def test_no_permissive_cors_and_security_headers(tmp_path):
    app, jid = make(tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/health", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


def test_unsupported_scheme_and_private_targets_rejected_at_submission(tmp_path):
    app, _ = make(tmp_path)
    with TestClient(app) as c:
        for url in ("file:///etc/passwd", "ftp://example.com/", "http://169.254.169.254/latest/meta-data/", "http://[::1]:8080/", "http://10.0.0.5/", "javascript:alert(1)", "http://127.0.0.1:22/"):
            r = c.post("/api/jobs", json={"url": url})
            assert r.status_code in (400, 403, 422), (url, r.status_code)
            assert r.status_code != 202


def test_oversized_and_unknown_request_fields_rejected(tmp_path):
    app, _ = make(tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/jobs", json={"url": "http://lab.test:3000/", "source_code": "x"}).status_code == 422
        assert c.post("/api/jobs", json={"url": "http://lab.test:3000/" + "a" * 5000}).status_code in (400, 413, 422)
