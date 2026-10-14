"""No target traffic on early security refusal; AI flow scope is server-owned."""
import pytest
import app.pipeline.runner as runner
from app.core.config import Settings
from app.core.models import CreateJob, PageInfo
from app.core.store import Store
from app.scanners.browser import test_navigation_flows as replay_flows


async def test_security_only_unapproved_origin_launches_no_network_tools(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,ai_enabled=False)
    store=Store(settings.db_path)
    job=store.create_job(CreateJob(url="https://example.test/",pillars=["security"]))
    class ResolvedPolicy:
        def is_authorized(self, url):
            return False
        async def resolve(self,url):
            raise AssertionError("Strict allowlist refusal must happen before DNS resolution")
    class NeverGuard:
        def __init__(self,*args,**kwargs):
            raise AssertionError("Guard/scanners must not launch for a refused-only job")
    pipeline=runner.Pipeline(settings,store)
    pipeline.policy=ResolvedPolicy()
    monkeypatch.setattr(runner,"EgressGuard",NeverGuard)
    report=await pipeline.run(job)
    assert report.overall_score is None and report.pages == []
    assert report.scores["security"].score is None
    assert all(s.status=="blocked" for s in report.steps if s.pillar=="security")
    assert "No scanner" in report.summary


async def test_flow_replay_uses_only_known_pages_and_never_submits():
    visits=[]
    class Page:
        async def close(self): pass
    class Context:
        async def new_page(self):return Page()
    class Response:
        status=200
        async def all_headers(self):return {}
    class Session:
        context=Context()
        async def navigate(self,page,url):
            visits.append(url)
            return Response()
    pages=[PageInfo(id="p1",url="http://approved.test/",title="Home",depth=0),PageInfo(id="p2",url="http://approved.test/login",title="Login",depth=1)]
    flows=[{"name":"Proposed login","page_ids":["p1","external-unobserved","p2"],"rationale":"A hypothesis"}]
    result=await replay_flows(Session(),flows,pages)
    assert visits==[pages[0].url,pages[1].url]
    assert result.metrics["mutations_submitted"]==0
    assert all(o["submitted"] is False for o in flows[0]["observations"])
    assert "Navigation only" in flows[0]["coverage"]


@pytest.mark.parametrize("statuses,expected", [([],"skipped"),(["skipped"],"skipped"),(["failed"],"failed"),(["partial","partial"],"partial"),(["completed","completed"],"completed")])
def test_partial_ai_work_is_not_reported_as_skipped(statuses,expected):
    from app.pipeline.runner import ai_task_status
    assert ai_task_status([{"status":s} for s in statuses]) == expected


async def test_strict_allowlist_blocks_every_pillar_before_guard(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, ai_enabled=True, require_allowlist_all_scans=True)
    store = Store(settings.db_path)
    job = store.create_job(CreateJob(url="https://not-approved.test/", pillars=["functionality", "security", "accessibility"]))
    class ResolvedPolicy:
        def is_authorized(self, url):
            return False
        async def resolve(self, url):
            raise AssertionError("Strict allowlist refusal must happen before DNS resolution")
    class NeverGuard:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No network guard or scanner may start for a refused target")
    pipeline = runner.Pipeline(settings, store)
    pipeline.policy = ResolvedPolicy()
    monkeypatch.setattr(runner, "EgressGuard", NeverGuard)
    report = await pipeline.run(job)
    assert report.overall_score is None
    assert report.pages == [] and report.findings == []
    assert all(step.status == "blocked" for step in report.steps if step.id != "policy" and (step.pillar is None or step.pillar in {"functionality", "security", "accessibility"}))
    assert "No scanner" in report.summary
    assert report.ai_tasks == []
