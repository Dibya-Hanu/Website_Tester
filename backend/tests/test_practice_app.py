"""Integration tests against the bundled practice app (real HTTP server, real Chromium, real safety proxy)."""
import re
import shutil
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.core.guard import EgressGuard
from app.core.models import CreateJob, Pillar
from app.core.policy import TargetPolicy
from app.core.store import Store
from app.pipeline.runner import Pipeline
from app.scanners.browser import BrowserSession, check_links, crawl

ROOT = Path(__file__).resolve().parents[2]


def chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not chromium_available(), reason="Playwright Chromium is not installed")


# ---------- plain HTTP behaviour of the practice app (no browser needed) ----------
def test_practice_app_refuses_non_loopback_bind():
    import sys
    sys.path.insert(0, str(ROOT / "practice_app"))
    try:
        import practice_shop as practice
        with pytest.raises(SystemExit):
            practice.make_server("0.0.0.0", 0)
    finally:
        sys.path.remove(str(ROOT / "practice_app"))
        sys.modules.pop("practice_shop", None)


def test_intentional_flaws_present_over_http(practice_url):
    with httpx.Client(base_url=practice_url) as c:
        home = c.get("/")
        assert home.status_code == 200
        for header in ("content-security-policy", "x-content-type-options", "referrer-policy", "x-frame-options"):
            assert header not in home.headers
        cookie = home.headers["set-cookie"].lower()
        assert "session_id=" in cookie and "httponly" not in cookie and "samesite" not in cookie
        assert c.get("/missing-page").status_code == 404
        assert b"not-a-real-secret" in c.get("/.env").content
        assert c.get("/.git/HEAD").text.startswith("ref: refs/heads/")
        assert len(c.get("/assets/big.js").content) > 1_000_000
        assert c.get("/health").json()["app"] == "practice-shop"


def test_reflection_is_inert_never_executable(practice_url):
    with httpx.Client(base_url=practice_url) as c:
        body = c.get("/search", params={"q": '<script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">'}).text
    lowered = body.lower()
    assert "<script" not in lowered.split("results for:")[1]
    assert "onerror=" not in lowered and "javascript:" not in lowered
    assert "<uwt-probe" in c_reflect(practice_url)


def c_reflect(url):
    return httpx.get(url + "search", params={"q": "<uwt-probe>x</uwt-probe>"}).text


# ---------- crawler against the practice app ----------
async def run_crawl(url, tmp_path, **limits):
    settings = Settings(allowlist=url, data_dir=tmp_path, **limits)
    target = await TargetPolicy(settings).resolve(url)
    async with EgressGuard(target, settings, tmp_path / "guard") as guard:
        async with BrowserSession(guard, settings) as session:
            out = await crawl(session, tmp_path, lambda m: None, True)
            links = await check_links(guard, out.pages)
    return out, links


@needs_browser
async def test_crawler_discovers_pages_and_expected_functional_issues(practice_url, tmp_path):
    out, links = await run_crawl(practice_url, tmp_path, max_pages=8, max_depth=2)
    paths = {re.sub(r"^https?://[^/]+", "", p.url) for p in out.pages}
    assert {"/", "/about", "/contact", "/products", "/search"} <= paths
    titles = " | ".join(f.title for f in out.findings + links.findings)
    urls = " ".join(f.location.url for f in out.findings + links.findings)
    assert "/missing-page" in urls                      # broken internal link
    assert "/assets/missing-banner.png" in urls          # broken image
    assert any("console" in f.title.lower() and f.location.url.endswith("/about") for f in out.findings)  # JS error
    assert all(p.url.startswith(practice_url.rstrip("/")) for p in out.pages), titles   # never leaves origin


@needs_browser
async def test_crawl_page_limit_is_enforced(practice_url, tmp_path):
    out, _ = await run_crawl(practice_url, tmp_path, max_pages=2, max_depth=2)
    assert len(out.pages) <= 2


@needs_browser
async def test_crawl_depth_zero_maps_only_start_page(practice_url, tmp_path):
    out, _ = await run_crawl(practice_url, tmp_path, max_pages=8, max_depth=0)
    assert [p.depth for p in out.pages] == [0]


# ---------- full pipeline ----------
def make_job(settings, url, pillars=None):
    store = Store(settings.db_path)
    job = store.create_job(CreateJob(url=url, **({"pillars": pillars} if pillars else {})))
    return store, store.claim() or job


@needs_browser
async def test_pipeline_survives_missing_browser_binary(practice_url, tmp_path):
    """Browser path is wrong: crawl fails visibly, the scan still completes, and functionality is NOT scored 100."""
    s = Settings(allowlist=practice_url, data_dir=tmp_path, ai_enabled=False, chromium_path=str(tmp_path / "no-chrome"),
                 nuclei_bin="no-such-nuclei", zap_url="http://127.0.0.1:1")
    s.prepare()
    store, job = make_job(s, practice_url, ["functionality", "security"])
    report = await Pipeline(s, store).run(job)
    by_id = {st.id: st.status for st in report.steps}
    assert by_id["crawl"] == "failed"
    assert by_id["nuclei"] == "skipped" and by_id["zap"] == "skipped"
    assert report.scores[Pillar.FUNCTIONALITY].score != 100 or report.scores[Pillar.FUNCTIONALITY].score is None
    assert report.overall_score != 100 and report.partial


@pytest.mark.slow
@needs_browser
async def test_full_pipeline_detects_expected_practice_app_issues(practice_url, tmp_path):
    tools = ROOT / "tools" / "node_modules"
    if not (tools / "axe-core").is_dir():
        pytest.skip("Node scanner packages not installed (cd tools && npm ci)")
    s = Settings(allowlist=practice_url, data_dir=tmp_path, ai_enabled=False, zap_url="http://127.0.0.1:1",
                 nuclei_bin=shutil.which("nuclei") or "nuclei", max_pages=8, load_seconds=3, max_users=2)
    s.prepare()
    store, job = make_job(s, practice_url)
    report = await Pipeline(s, store).run(job)
    categories = {f.category for f in report.findings}
    titles = " ".join(f.title.lower() for f in report.findings)
    # security
    assert {"header-content-security-policy", "exposed-env", "exposed-git"} <= categories
    assert any(c.startswith("cookie-flags") for c in categories) and "inert-reflection" in categories
    # accessibility (axe)
    assert "images must have alternative text" in titles and "color contrast" in titles
    assert any("heading" in f.title.lower() for f in report.findings)
    # functionality
    assert any("404" in f.title for f in report.findings) and any("console" in f.title.lower() for f in report.findings)
    # performance
    assert "performance-slow-page" in categories and "performance-resource-size" in categories
    # honesty: AI was disabled, so nothing may claim AI authorship, and ZAP must not be marked as passed
    assert not any(f.ai_assisted for f in report.findings)
    assert {st.id: st.status for st in report.steps}["zap"] in {"skipped", "failed"}
    assert report.partial and report.overall_score is not None and report.overall_score < 100
