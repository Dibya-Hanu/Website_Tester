import httpx

from app.core.models import VerificationSpec
from app.core.redact import redact
from app.pipeline.verification import verify_findings
from app.scanners.http_checks import cookie_findings, file_signature, header_findings


def response(body="", headers=None, status=200):
    return httpx.Response(status, text=body, headers=headers or {}, request=httpx.Request("GET","http://lab.test:3000/"))


def test_spa_fallback_is_not_an_exposed_env():
    hit, _ = file_signature("/.env", response("<html>SECRET=not_a_file</html>", {"Content-Type":"text/html"}))
    assert not hit


def test_env_evidence_redacts_values():
    hit, evidence = file_signature("/.env", response("DB_PASSWORD=super-sensitive\nAPP_PORT=3000\n", {"Content-Type":"text/plain"}))
    assert hit and "DB_PASSWORD" in evidence and "super-sensitive" not in evidence


def test_git_signature_not_any_200():
    assert file_signature("/.git/HEAD", response("ref: refs/heads/main\n", {"Content-Type":"text/plain"}))[0]
    assert not file_signature("/.git/HEAD", response("404 not found", {"Content-Type":"text/plain"}))[0]


def test_csp_frame_ancestors_satisfies_framing():
    found = header_findings("https://example.com/", response(headers={"Content-Security-Policy":"default-src 'self'; frame-ancestors 'none'"}))
    assert not any(f.category == "header-framing" for f in found)


def test_preferences_do_not_need_httponly():
    assert not cookie_findings("https://example.com/", response(headers={"Set-Cookie":"theme=dark; SameSite=Lax"}))
    found = cookie_findings("https://example.com/", response(headers={"Set-Cookie":"session=topsecret; SameSite=Lax"}))
    assert len(found) == 1
    assert "topsecret" not in found[0].model_dump_json()


def test_redacts_bearer_cookie_values():
    value=redact("Set-Cookie: session=secret\nAuthorization: Bearer private\nAPI_KEY=hello")
    assert "private" not in value and "hello" not in value and "session=secret" not in value


class FakeGuard:
    def __init__(self, handler):
        self.handler = handler
    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def test_header_independently_verified(make_finding):
    finding = make_finding(check=VerificationSpec(kind="header-missing", data={"url":"http://lab.test:3000/","header":"content-security-policy"}))
    result = await verify_findings([finding], FakeGuard(lambda _: response()))
    assert finding.status == "Verified" and result["confirmed_findings"] == 1


async def test_inert_reflection_never_upgraded_to_xss(make_finding):
    payload="<uwt-probe>marker</uwt-probe>"
    finding = make_finding(check=VerificationSpec(kind="reflection", data={"url":"http://lab.test:3000/?q=x","key":"q","payload":payload}))
    await verify_findings([finding], FakeGuard(lambda _: response(payload,{"content-type":"text/html"})))
    assert finding.status == "Possible"
    assert "exploitability remains unproven" in finding.verification_note


async def test_contradicted_observation_remains_possible(make_finding):
    finding = make_finding(check=VerificationSpec(kind="header-missing", data={"url":"http://lab.test:3000/","header":"content-security-policy"}))
    await verify_findings([finding], FakeGuard(lambda _: response(headers={"Content-Security-Policy":"default-src 'self'"})))
    assert finding.contradicted and finding.status == "Possible"


async def test_ai_prioritized_security_pages_are_reviewed_within_bound(tmp_path):
    from types import SimpleNamespace
    from app.core.config import Settings
    from app.core.policy import TargetPolicy
    from app.core.models import PageInfo
    from app.scanners.http_checks import custom_security

    seen = []
    def handler(request):
        seen.append(str(request.url))
        status = 404 if request.url.path in {"/.git/HEAD", "/.env", "/robots.txt"} else 200
        return response("<html>ok</html>", {"Content-Type": "text/html"}, status)

    class Guard(FakeGuard):
        target = SimpleNamespace(url="http://lab.test:3000/", origin="http://lab.test:3000")

    guard = Guard(handler)
    policy = TargetPolicy(Settings(data_dir=tmp_path, allowlist="http://lab.test:3000"))
    pages = [
        PageInfo(id="home", url="http://lab.test:3000/", title="Home", depth=0),
        PageInfo(id="login", url="http://lab.test:3000/login", title="Login", depth=1),
        PageInfo(id="help", url="http://lab.test:3000/help", title="Help", depth=1),
    ]
    result = await custom_security(policy, guard, pages, ["login", "help"])
    assert result.metrics["security_pages_reviewed"] == 3
    assert [item["url"] for item in result.metrics["page_results"]] == [
        "http://lab.test:3000/", "http://lab.test:3000/login", "http://lab.test:3000/help"
    ]
    # Root + two AI-prioritized pages are bounded; other checks remain root-based.
    assert seen.count("http://lab.test:3000/login") == 1
    assert seen.count("http://lab.test:3000/help") == 1


async def test_lighthouse_refuses_ai_supplied_off_origin_url(tmp_path):
    from types import SimpleNamespace
    from app.core.config import Settings
    from app.scanners.performance import lighthouse_scan

    class Guard:
        target = SimpleNamespace(url="http://lab.test:3000/", origin="http://lab.test:3000")
        local_url = "http://127.0.0.1:9999"

    result = await lighthouse_scan(Settings(data_dir=tmp_path, tools_dir=tmp_path), Guard(), tmp_path,
                                   "chromium", "http://evil.test/")
    assert result.status == "blocked"
    assert "not an observed safe URL" in result.reason
