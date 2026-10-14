"""Extra unit tests: performance parsing, form inspection, process control, missing scanners, DNS, scoring.
All fixtures here are synthetic and are NOT scan results."""
import asyncio
import os
import socket
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from app.core import policy as policy_module
from app.core.config import Settings
from app.core.models import Form, InputField, PageInfo, Pillar, Step
from app.core.policy import PolicyError, TargetPolicy, normalized_url
from app.core.process import run_command
from app.pipeline.scoring import score_report
from app.scanners.browser import _link_allowed, check_links, static_form_findings, test_forms as run_form_checks
from app.scanners.nuclei import nuclei_scan
from app.scanners.performance import classify_page_metrics, parse_resource_links


# ---------- performance metric parsing ----------
def test_parse_resource_links_resolves_dedupes_and_skips_data_uris():
    html = ('<link rel="stylesheet" href="/a.css"><script src="app.js"></script><script src="app.js"></script>'
            '<img src="data:image/png;base64,AAAA"><img src="/i.png"><link rel="icon" href="/f.ico">')
    assert parse_resource_links(html, "http://h.test/dir/page") == [
        "http://h.test/a.css", "http://h.test/dir/app.js", "http://h.test/i.png"]


def test_parse_resource_links_survives_malformed_html():
    assert isinstance(parse_resource_links("<script src=<<<>>> <img", "http://h.test/"), list)


def test_classify_page_metrics_thresholds():
    pages = [{"url": "http://h.test/slow", "samples_ms": [1500, 1700]}, {"url": "http://h.test/mixed", "samples_ms": [400, 1700]},
             {"url": "http://h.test/none", "samples_ms": []}]
    resources = [{"url": "http://h.test/big.js", "bytes": 1_500_000, "ms": 40, "page": "p"},
                 {"url": "http://h.test/mid.js", "bytes": 300_000, "ms": 10, "page": "p"},
                 {"url": "http://h.test/small.js", "bytes": 1_000, "ms": 1, "page": "p"}]
    found = {(f.title, f.severity.value) for f in classify_page_metrics(pages, resources)}
    assert found == {("Slow page response", "Medium"), ("Oversized resource", "Medium"), ("Heavy resource", "Low")}


def test_classify_page_metrics_no_findings_for_fast_small():
    assert classify_page_metrics([{"url": "u", "samples_ms": [50, 60]}], [{"url": "r", "bytes": 10, "ms": 1, "page": "u"}]) == []


# ---------- form inspection ----------
def page_with(field_name, field_type):
    f = InputField(id="f1", selector="input", name=field_name, label=field_name, type=field_type)
    return PageInfo(id="p1", url="http://h.test/c", depth=0, forms=[Form(id="x", page_id="p1", selector="form", action="", method="POST", fields=[f])])


def test_email_text_field_flagged_possible_low():
    found = static_form_findings([page_with("email", "text")])
    assert len(found) == 1 and found[0].status == "Possible" and found[0].severity.value == "Low"


@pytest.mark.parametrize("name,kind", [("email", "email"), ("username", "text"), ("phone", "tel")])
def test_correct_or_unrelated_fields_not_flagged(name, kind):
    assert static_form_findings([page_with(name, kind)]) == []


# ---------- crawl scope rules ----------
def test_cross_origin_and_action_links_not_followed():
    base = "http://h.test:8000"
    assert _link_allowed({"url": "http://h.test:8000/a", "text": "About"}, base)
    assert not _link_allowed({"url": "http://other.test:8000/a", "text": "x"}, base)
    assert not _link_allowed({"url": "http://h.test:9000/a", "text": "x"}, base)
    assert not _link_allowed({"url": "https://h.test:8000/a", "text": "x"}, base)
    assert not _link_allowed({"url": "http://h.test:8000/a", "text": "Delete account"}, base)
    assert not _link_allowed({"url": "http://h.test:8000/logout", "text": "Out"}, base)


@pytest.mark.parametrize("raw,expected", [
    ("HTTP://Example.COM:80/a", "http://example.com/a"),
    ("https://example.com:443", "https://example.com/"),
    ("http://EXAMPLE.com:8080/x?y=1#frag", "http://example.com:8080/x?y=1#frag"),
    ("http://example.com./", "http://example.com/"),
])
def test_url_normalization(raw, expected):
    assert normalized_url(raw) == expected


@pytest.mark.parametrize("bad", ["ftp://example.com/", "http://user:pw@example.com/", "http://exa mple.com/", "http://example.com\\x", "javascript:alert(1)", "http://"])
def test_url_normalization_rejects(bad):
    with pytest.raises(PolicyError):
        normalized_url(bad)


# ---------- DNS rebinding: every resolve() call is re-validated ----------
async def test_dns_rebinding_second_answer_private_is_refused(monkeypatch):
    answers = iter([[(2, 1, 6, "", ("93.184.216.34", 80))], [(2, 1, 6, "", ("10.0.0.5", 80))]])

    async def fake_getaddrinfo(self, *a, **k):
        return next(answers)

    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", fake_getaddrinfo)
    pol = TargetPolicy(Settings(allowlist="http://lab.test:3000"))
    target = await pol.resolve("http://rebind.example/")
    assert target.addresses == ("93.184.216.34",)
    with pytest.raises(PolicyError):
        await pol.resolve("http://rebind.example/")  # same name, now private -> refused


async def test_unresolvable_host_gives_clear_error(monkeypatch):
    async def boom(self, *a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", boom)
    with pytest.raises(PolicyError, match="could not be resolved"):
        await TargetPolicy(Settings(allowlist="http://lab.test:3000")).resolve("http://nowhere.invalid/")


def test_redirect_to_other_origin_is_policy_error():
    from app.scanners.http_checks import fetch

    class Client:
        async def request(self, method, url):
            return SimpleNamespace(status_code=302, headers={"location": "http://169.254.169.254/latest"})
    with pytest.raises(PolicyError, match="Unsafe redirect"):
        asyncio.run(fetch(Client(), "http://site.test/"))


# ---------- process control: timeouts, cancellation, missing binaries, failures ----------
async def test_timeout_kills_process_promptly():
    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await run_command([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
    assert time.monotonic() - start < 15


async def test_cancellation_stops_child_process(tmp_path):
    pidfile = tmp_path / "pid.txt"
    code = f"import os,time; open(r'{pidfile}','w').write(str(os.getpid())); time.sleep(60)"
    task = asyncio.create_task(run_command([sys.executable, "-c", code], timeout=60))
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text():
            break
        await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pid = int(pidfile.read_text())
    await asyncio.sleep(0.5)
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


async def test_missing_binary_raises_oserror_not_hang():
    with pytest.raises(OSError):
        await run_command(["definitely-not-a-real-binary-xyz"], timeout=5)


def fake_guard(url):
    return SimpleNamespace(target=SimpleNamespace(url=url, origin=url.rstrip("/")), local_url="http://127.0.0.1:1", ca_file="x")


async def test_nuclei_missing_binary_is_skipped_not_passed(tmp_path):
    s = Settings(allowlist="http://lab.test:3000", nuclei_bin="no-such-nuclei-binary", data_dir=tmp_path)
    r = await nuclei_scan(TargetPolicy(s), fake_guard("http://lab.test:3000/"), s, tmp_path)
    assert r.status == "skipped" and r.findings == []


async def test_nuclei_process_failure_is_failed_not_passed(tmp_path):
    s = Settings(allowlist="http://lab.test:3000", nuclei_bin=sys.executable, data_dir=tmp_path)  # python rejects nuclei's flags
    r = await nuclei_scan(TargetPolicy(s), fake_guard("http://lab.test:3000/"), s, tmp_path)
    assert r.status == "failed" and r.findings == [] and "no pass" in r.reason.lower()


async def test_nuclei_refused_for_unapproved_origin(tmp_path):
    s = Settings(allowlist="http://lab.test:3000", data_dir=tmp_path)
    r = await nuclei_scan(TargetPolicy(s), fake_guard("http://evil.example/"), s, tmp_path)
    assert r.status == "blocked"


async def test_nuclei_zero_exit_without_result_file_is_failed_not_passed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.scanners.nuclei as module

    settings = Settings(allowlist="http://lab.test:3000", data_dir=tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _binary: "/usr/bin/nuclei")
    async def fake_command(*_args, **_kwargs):
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module, "run_command", fake_command)
    result = await nuclei_scan(TargetPolicy(settings), fake_guard("http://lab.test:3000/"), settings, tmp_path)
    assert result.status == "failed"
    assert result.findings == []
    assert result.metrics["output_file_present"] is False
    assert "no pass" in result.reason.lower()


async def test_nuclei_malformed_result_rows_are_partial_not_passed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.scanners.nuclei as module

    settings = Settings(allowlist="http://lab.test:3000", data_dir=tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _binary: "/usr/bin/nuclei")
    async def fake_command(command, **_kwargs):
        output = Path(command[command.index("-o") + 1])
        output.write_text("not-json\n[]\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module, "run_command", fake_command)
    result = await nuclei_scan(TargetPolicy(settings), fake_guard("http://lab.test:3000/"), settings, tmp_path)
    assert result.status == "partial"
    assert result.findings == []
    assert result.metrics["malformed_rows"] == 2


async def test_ollama_malformed_model_catalogue_is_reported_unavailable(tmp_path, monkeypatch):
    import httpx
    from app.ai.client import LocalAI

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return None  # Valid JSON, invalid API response shape.
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def get(self, *_args, **_kwargs): return Response()
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ai = LocalAI(Settings(data_dir=tmp_path, ai_enabled=True))
    assert await ai.available_models() == set()
    assert "unavailable" in (ai._unavailable or "").lower()


# ---------- scoring with incomplete coverage ----------
def steps(*pairs):
    return [Step(id=f"s{i}", title=f"s{i}", pillar=p, status=st) for i, (p, st) in enumerate(pairs)]


def test_all_checks_failed_means_no_score_not_100():
    scores, overall, coverage, partial = score_report(list(Pillar), [], steps((Pillar.PERFORMANCE, "failed"), (Pillar.SECURITY, "skipped")), {})
    assert scores[Pillar.PERFORMANCE].score is None and scores[Pillar.SECURITY].score is None
    assert overall is None and partial


def test_partial_coverage_is_labelled_partial():
    scores, overall, coverage, partial = score_report([Pillar.PERFORMANCE], [], steps((Pillar.PERFORMANCE, "completed"), (Pillar.PERFORMANCE, "failed")), {})
    assert scores[Pillar.PERFORMANCE].status == "partial" and scores[Pillar.PERFORMANCE].coverage == 50 and partial


# ---------- report exports ----------
def test_pdf_has_signature_and_survives_hostile_text(tmp_path):
    from app.api.exports import render_pdf
    report = {"url": "http://x.test/<b>", "overall_score": None, "coverage": 0, "partial": True, "finished_at": "now", "duration_seconds": 0,
              "pages": [], "scores": {}, "summary": "<para>&unclosed", "priorities": [], "steps": [], "ai_tasks": [], "limitations": [],
              "authorized": False, "test_cases": [], "suppressed_findings": [],
              "findings": [{"id": "1", "title": "<i>t</i> 日本語", "pillar": "security", "severity": "High", "status": "Possible", "category": "c",
                            "location": {"url": "http://x.test/"}, "evidence": [{"kind": "snippet", "detail": "<x>"}], "explanation": "e",
                            "suggested_fix": "f", "sources": ["s"], "verification_note": "n"}]}
    pdf = render_pdf(report, tmp_path)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000


def test_shipped_sample_json_validates_against_report_schema():
    import json
    from pathlib import Path
    from app.core.models import Report
    sample = Path(__file__).resolve().parents[2] / "samples" / "juice-shop-report.json"
    report = Report.model_validate(json.loads(sample.read_text()))
    assert report.findings and report.schema_version == "1.0"


async def test_empty_link_inventory_is_skipped_not_reported_as_pass():
    page = PageInfo(id="p1", url="http://h.test/", depth=0, links=[])
    result = await check_links(None, [page])
    assert result.status == "skipped"
    assert result.metrics["links_checked"] == 0
    assert "not assessed" in result.reason


async def test_no_forms_is_skipped_not_reported_as_completed(tmp_path):
    result, records = await run_form_checks(None, None, [], tmp_path, lambda _: None)
    assert result.status == "skipped"
    assert records == []
    assert result.metrics["cases_executed"] == 0
    assert result.metrics["mutation_submissions"] == 0


async def test_link_checker_reports_discovered_vs_budgeted_links():
    class FakeResponse:
        status_code = 200
        headers = {}

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def request(self, _method, _url):
            return FakeResponse()

    class FakeGuard:
        def client(self):
            return FakeClient()

    page = PageInfo(id="p1", url="http://h.test/", depth=0,
                    links=[{"url": f"http://h.test/p{i}", "text": f"page {i}"} for i in range(24)])
    result = await check_links(FakeGuard(), [page])
    assert result.status == "completed"
    assert result.metrics["links_discovered"] == 24
    assert result.metrics["links_budgeted"] == 20
    assert result.metrics["links_checked"] == 20


async def test_axe_empty_site_is_skipped_with_explicit_coverage(tmp_path):
    from app.scanners.accessibility import axe_scan
    fake_session = SimpleNamespace(settings=SimpleNamespace(tools_dir=tmp_path))
    result = await axe_scan(fake_session, [], tmp_path)
    assert result.status == "skipped"
    assert result.metrics["pages_audited"] == 0
    assert "No pages" in result.reason


async def test_performance_resource_request_metrics_exclude_globally_deduped_requests(monkeypatch):
    from app.scanners import performance as perf

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b"x" * 100
        text = '<html><head><script src="/shared.js"></script></head><body>ok</body></html>'

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None

    class FakeGuard:
        def client(self):
            return FakeClient()

    calls = []
    async def fake_fetch(_client, url):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(perf, "fetch", fake_fetch)
    page_rows, resource_rows, summary = await perf.audit_pages(FakeGuard(), ["http://h.test/a", "http://h.test/b"])
    assert len(page_rows) == 2
    assert len(resource_rows) == 1
    assert page_rows[0]["requests"] == 3  # two page samples plus the one shared resource request
    assert page_rows[1]["requests"] == 2  # the deduplicated resource caused no request for page two
    assert summary["resources_measured"] == 1


async def test_locust_zero_request_output_is_failed_not_passed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.scanners.performance as module

    settings = Settings(allowlist="http://lab.test:3000", data_dir=tmp_path, load_enabled=True)
    async def fake_command(command, **_kwargs):
        prefix = Path(command[command.index("--csv") + 1])
        stats = Path(f"{prefix}_stats.csv")
        stats.write_text("Name,Request Count,Failure Count,Average Response Time,50%,95%,Requests/s\nAggregated,0,0,0,0,0,0\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module, "run_command", fake_command)
    result = await module.load_scan(TargetPolicy(settings), fake_guard("http://lab.test:3000/"), settings, tmp_path, [])
    assert result.status == "failed"
    assert result.metrics["requests"] == 0
    assert "no performance pass" in result.reason.lower()
