import json

from fastapi.testclient import TestClient

from app.core.models import CreateJob
from app.main import create_app


def test_health_and_policy(settings):
    with TestClient(create_app(settings,run_worker=False)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/policy").json()["max_users"] <= 20
        check=client.get("/api/policy/check",params={"url":"https://example.com/"}).json()
        assert not check["authorized"] and "REFUSED" in check["warning"]


def test_input_is_only_url_and_pillars(settings):
    with TestClient(create_app(settings,run_worker=False)) as client:
        assert client.post("/api/jobs",json={"source_code":"x"}).status_code == 422
        assert client.post("/api/jobs",json={"url":"http://example.com/","max_users":100}).status_code == 422
        assert client.post("/api/jobs",json={"url":"file:///etc/passwd"}).status_code == 422
        assert client.post("/api/jobs",json={"url":"http://169.254.169.254/"}).status_code == 422


def test_history_cancel_and_sse_replay(settings):
    app=create_app(settings,run_worker=False)
    job=app.state.store.create_job(CreateJob(url="http://lab.test:3000/"))
    eid=app.state.store.event(job["id"],{"type":"log","message":"retained"})
    with TestClient(app) as client:
        assert client.get("/api/jobs").json()["jobs"][0]["id"] == job["id"]
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
        replay=client.get(f"/api/jobs/{job['id']}/events?since={eid}").text
        assert '"type": "cancelled"' in replay
        assert "retained" not in replay
        assert client.get(f"/api/reports/{job['id']}").status_code == 409


def test_evidence_path_traversal_refused(settings):
    app=create_app(settings,run_worker=False)
    job=app.state.store.create_job(CreateJob(url="http://lab.test:3000/"))
    with TestClient(app) as client:
        assert client.get(f"/api/jobs/{job['id']}/evidence/%2E%2E%2Ftester.sqlite3").status_code == 404
        assert client.get("/api/jobs/not-an-id").status_code == 404
        assert client.get("/api/unknown").status_code == 404


def test_unapproved_origin_rejected_before_job_is_enqueued(settings, monkeypatch):
    from app.core.policy import Target
    settings.require_allowlist_all_scans = True
    app = create_app(settings, run_worker=False)
    async def resolve(url):
        return Target(url=url, origin="https://unapproved.test:443", hostname="unapproved.test",
                      port=443, addresses=("93.184.216.34",), authorized=False)
    monkeypatch.setattr(app.state.policy, "resolve", resolve)
    with TestClient(app) as client:
        response = client.post("/api/jobs", json={"url":"https://unapproved.test/", "pillars":["functionality"]})
        assert response.status_code == 403
        assert "allowlist" in response.json()["detail"]
        assert client.get("/api/jobs").json()["jobs"] == []
