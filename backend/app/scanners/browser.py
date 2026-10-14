"""Bounded Playwright crawl and non-submitting client-side form/flow checks."""
import asyncio
import base64
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.ai.client import LocalAI
from app.ai.tasks import generate_cases
from app.core.config import Settings
from app.core.guard import EgressGuard
from app.core.models import Evidence, Finding, Form, Location, PageInfo, Pillar, ScanResult, Severity, VerificationSpec
from app.core.policy import ACTION, normalized_url, origin, safe_read_url
from app.core.redact import redact, safe_url
from app.scanners.http_checks import fetch as safe_fetch

# Only DOM metadata is observed; hidden values, password values and cookies are never read.
DOM_MAP = r"""() => {
  const css = el => {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1)
      return '#' + CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.documentElement) {
      let name = el.tagName.toLowerCase();
      const siblings = el.parentElement ? [...el.parentElement.children].filter(x => x.tagName === el.tagName) : [];
      if (siblings.length > 1) name += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
      parts.unshift(name); el = el.parentElement;
    }
    return parts.join(' > ');
  };
  const label = el => (el.labels?.[0]?.innerText || el.getAttribute('aria-label') ||
    el.getAttribute('placeholder') || el.name || '').slice(0,120);
  const describe = el => ({selector:css(el), name:el.name || '', label:label(el),
    type:el.type || el.tagName.toLowerCase(), required:!!el.required,
    min_length:el.minLength >= 0 ? el.minLength : null,
    max_length:el.maxLength >= 0 ? el.maxLength : null,
    minimum:el.getAttribute('min'), maximum:el.getAttribute('max'), pattern:el.getAttribute('pattern')});
  const forms = [...document.forms].slice(0,8).map(f => ({selector:css(f),
    action:f.action || location.href, method:(f.method || 'get').toUpperCase(), virtual:false,
    text:(f.innerText || '').slice(0,450),
    fields:[...f.querySelectorAll('input:not([type=hidden]):not([type=file]),textarea,select')]
      .filter(el => !el.disabled).slice(0,12).map(describe)}));
  const orphan = [...document.querySelectorAll('input:not([type=hidden]):not([type=file]),textarea')]
    .filter(el => !el.closest('form') && !el.disabled).slice(0,10);
  if (orphan.length) forms.push({selector:'body',action:location.href,method:'NONE',virtual:true,
    text:'Controls outside a native form',fields:orphan.map(describe)});
  return {title:document.title,text:(document.body?.innerText || '').slice(0,1800),forms,
    links:[...document.querySelectorAll('a[href]')].slice(0,100).map(a=>({url:a.href,text:(a.innerText || a.getAttribute('aria-label') || '').slice(0,100)})),
    images:[...document.images].filter(i=>i.complete && i.naturalWidth===0 && i.currentSrc)
      .slice(0,12).map(i=>({url:i.currentSrc,selector:css(i)}))};
}"""


class BrowserSession:
    def __init__(self, guard: EgressGuard, settings: Settings):
        self.guard, self.settings = guard, settings
        self.playwright = self.browser = self.context = None
        self.blocked = 0
        self.last_readiness: dict = {"strategy": "not_started", "stable": False, "wait_ms": 0}
        self.auth_cookies: list[dict] = []
        self.post_login_url: str | None = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            bypass_hosts = "localhost,127.0.0.1,unpkg.com,*.unpkg.com,jsdelivr.net,*.jsdelivr.net,tailwindcss.com,*.tailwindcss.com,cloudflare.com,*.cloudflare.com,cdnjs.cloudflare.com,*.cdnjs.cloudflare.com,googleapis.com,*.googleapis.com,gstatic.com,*.gstatic.com"
            self.browser = await self.playwright.chromium.launch(
                headless=True, executable_path=self.settings.chromium_path or None,
                proxy={"server": self.guard.local_url, "bypass": bypass_hosts},
                args=["--no-sandbox", "--disable-dev-shm-usage", f"--proxy-bypass-list={bypass_hosts}",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1440, "height": 1000}, ignore_https_errors=True,
                service_workers="block", accept_downloads=False, user_agent=self.settings.user_agent,
            )
            self.context.set_default_timeout(self.settings.request_timeout * 1000)
            if self.settings.auth_enabled or self.settings.auth_username or self.settings.auth_cookies or (self.settings.ROOT / "credentials.json").exists():
                try:
                    from app.core.auth import get_authenticated_session
                    self.auth_cookies, self.post_login_url = await get_authenticated_session(
                        self.guard.target.url, self.settings
                    )
                    if self.auth_cookies:
                        await self.context.add_cookies(self.auth_cookies)
                except Exception as exc:
                    pass
            await self.context.route("**/*", self._route)
            await self.context.route_web_socket("**", lambda route: route.close())
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _route(self, route):
        request = route.request
        if request.url.startswith(("data:", "blob:")):
            await route.continue_()
            return
        ALLOWED_CDNS = ("googleapis.com", "gstatic.com", "jsdelivr.net", "tailwindcss.com", "cloudflare.com", "unpkg.com")
        req_origin = origin(request.url)
        host = urlsplit(request.url).hostname or ""
        is_safe_cdn = request.method == "GET" and any(host.endswith(c) for c in ALLOWED_CDNS) and request.resource_type in {"stylesheet", "font", "image", "script"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} or (req_origin != self.guard.target.origin and not is_safe_cdn) or not safe_read_url(request.url):
            self.blocked += 1
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def __aexit__(self, *_):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def navigate(self, page, url: str):
        """Navigate with bounded adaptive readiness rather than a fixed sleep.

        Waiting for network-idle is deliberately avoided: many modern sites keep
        telemetry, polling, or WebSocket connections open. We wait briefly for
        the load event, then sample user-visible DOM structure until it stabilizes
        or the bounded readiness window expires.
        """
        timeout_ms = self.settings.request_timeout * 1000
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightError as exc:
            # If domcontentloaded timed out due to slow external assets or delayed scripts,
            # verify if the page committed and the DOM is available for testing.
            try:
                ready_state = await page.evaluate("() => document.readyState")
                if ready_state in ("interactive", "complete"):
                    response = None
                else:
                    raise exc
            except Exception:
                raise exc
        self.last_readiness = await wait_for_dom_stability(page)
        return response


async def wait_for_dom_stability(page, *, timeout_ms: int = 2200, sample_ms: int = 200,
                                 required_stable_samples: int = 2) -> dict:
    """Wait for a meaningful, stable DOM using bounded and testable observations."""
    started = time.perf_counter()
    # Load is a useful signal, but never allowed to stall a page with long-lived
    # resources. DOM-content-loaded has already completed at this point.
    try:
        await page.wait_for_load_state("load", timeout=min(1200, timeout_ms))
    except PlaywrightError:
        pass

    previous = None
    stable_samples = 0
    final_snapshot = {}
    while (time.perf_counter() - started) * 1000 < timeout_ms:
        try:
            final_snapshot = await page.evaluate("""() => {
              const body = document.body;
              return {
                ready_state: document.readyState,
                text_length: (body?.innerText || '').length,
                child_count: body?.children.length || 0,
                link_count: document.querySelectorAll('a[href]').length,
                form_count: document.forms.length,
                control_count: document.querySelectorAll('input,textarea,select,button,[role=button]').length,
                image_count: document.images.length
              };
            }""")
        except PlaywrightError:
            break
        # Require a minimum observation window to avoid treating an initial empty
        # document as ready. Stability is a heuristic, not proof all app work ended.
        elapsed_ms = (time.perf_counter() - started) * 1000
        if final_snapshot == previous and elapsed_ms >= sample_ms * (required_stable_samples + 1):
            stable_samples += 1
        else:
            stable_samples = 0
        if stable_samples >= required_stable_samples:
            return {"strategy": "load-event-plus-dom-stability", "stable": True,
                    "wait_ms": round(elapsed_ms), "stable_samples": stable_samples,
                    "snapshot": final_snapshot}
        previous = final_snapshot
        await page.wait_for_timeout(sample_ms)

    return {"strategy": "bounded-dom-stability-timeout", "stable": False,
            "wait_ms": round((time.perf_counter() - started) * 1000),
            "stable_samples": stable_samples, "snapshot": final_snapshot,
            "note": "Page content may still be updating; interpret coverage cautiously."}


@dataclass
class CrawlOutput:
    pages: list[PageInfo] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    result: ScanResult = field(default_factory=ScanResult)


def _link_allowed(link: dict, target_origin: str) -> bool:
    try:
        return origin(normalized_url(link["url"])) == target_origin and not ACTION.search(link.get("text", ""))
    except (ValueError, KeyError):
        return False


async def reveal_navigation(page):
    """Open at most two read-only menu controls, never arbitrary action buttons."""
    candidates = page.locator("button[aria-haspopup='menu'],button[aria-label*='menu' i],button[aria-label*='account' i]")
    for index in range(min(await candidates.count(), 2)):
        button = candidates.nth(index)
        try:
            if not await button.is_visible() or await button.get_attribute("type") == "submit":
                continue
            label = ((await button.get_attribute("aria-label")) or "") + (await button.inner_text())
            if ACTION.search(label):
                continue
            await button.click(timeout=1200)
            await page.wait_for_timeout(150)
        except PlaywrightError:
            continue


async def _emit_frame(on_frame, page, action: str, url: str):
    if not on_frame:
        return
    try:
        buf = await page.screenshot(type="jpeg", quality=45, animations="disabled")
        b64 = base64.b64encode(buf).decode("ascii")
        res = on_frame(b64, action, url)
        if asyncio.iscoroutine(res):
            await res
    except Exception:
        pass


async def crawl(session: BrowserSession, directory: Path, log, collect_functional: bool, on_page = None, on_frame = None) -> CrawlOutput:
    settings = session.settings
    start_url = session.guard.target.url
    pending = deque([(start_url, 0)])
    if getattr(session, "post_login_url", None) and session.post_login_url != start_url:
        log(f"Authenticated session redirected to dashboard: {safe_url(session.post_login_url)}")
        pending.appendleft((session.post_login_url, 0))
    seen = set()
    output = CrawlOutput()
    failed_pages = 0
    while pending and len(output.pages) < settings.max_pages:
        url, depth = pending.popleft()
        if url in seen:
            continue
        seen.add(url)
        pid = f"page-{len(output.pages)+1}"
        log(f"Mapping {safe_url(url)} (depth {depth})")
        if on_page:
            try:
                on_page("crawling", {"url": safe_url(url), "depth": depth})
            except Exception:
                pass
        page = await session.context.new_page()
        errors, bad_responses, observed_get = [], [], []
        page.on("pageerror", lambda error: errors.append(redact(str(error), 600)))
        page.on("console", lambda message: errors.append(redact(message.text, 600)) if message.type == "error" and "ERR_BLOCKED_BY_CLIENT" not in message.text and "451" not in message.text else None)

        async def response_event(response):
            # Browser-internal or malformed response URLs must not destabilize the
            # crawl. Only normalized same-origin HTTP responses are recorded.
            try:
                response_origin = origin(response.url)
                observed_safe_url = safe_read_url(response.url)
            except (ValueError, TypeError):
                return
            if response_origin != session.guard.target.origin:
                return
            if response.request.method == "GET" and observed_safe_url and urlsplit(response.url).query:
                if len(observed_get) < 30 and response.url not in observed_get:
                    observed_get.append(safe_url(response.url))
            if response.status >= 400:
                try:
                    headers = await response.all_headers()
                except PlaywrightError:
                    headers = {}
                if "x-uwt-blocked" not in headers:
                    bad_responses.append((safe_url(response.url), response.status))
        page.on("response", response_event)
        try:
            response = await session.navigate(page, url)
            if response and (await response.all_headers()).get("x-uwt-blocked"):
                log("Navigation intentionally blocked by safety policy; not counted as a website failure.")
                continue
            # An origin-changing redirect is blocked before the browser can fetch it.
            if origin(page.url) != session.guard.target.origin:
                raise PlaywrightError("Navigation left the allowed origin.")
            data = await page.evaluate(DOM_MAP)
            current = normalized_url(page.url)
            seen.add(current)
            await _emit_frame(on_frame, page, f"Navigating & mapping: {safe_url(current)}", safe_url(current))
            forms = []
            for i, raw in enumerate(data["forms"]):
                fid = f"{pid}-form-{i+1}"
                for j, field_data in enumerate(raw["fields"]):
                    field_data["id"] = f"{fid}-field-{j+1}"
                forms.append(Form(id=fid, page_id=pid, **raw))
            info = PageInfo(id=pid, url=safe_url(current), depth=depth, title=redact(data["title"], 300),
                            text=redact(data["text"], 1800), status_code=response.status if response else 200,
                            forms=forms, readiness=dict(session.last_readiness))
            # Screenshots are taken before menu exploration to avoid recording transient menus.
            if len(output.pages) < 3:
                for viewport, size in [("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})]:
                    await page.set_viewport_size(size)
                    await page.wait_for_timeout(100)
                    name = f"{pid}-{viewport}.png"
                    await page.screenshot(path=str(directory / name), full_page=False, animations="disabled")
                    info.screenshots[viewport] = name
                    action_tag = "[RESPONSIVE] Mobile layout audit (390×844)" if viewport == "mobile" else "[DESKTOP] Viewport audit (1440×1000)"
                    await _emit_frame(on_frame, page, action_tag, safe_url(current))
                await page.set_viewport_size({"width": 1440, "height": 1000})
            try:
                # Dynamic progressive viewport sweep to trigger lazy loading and inspect full DOM height
                scroll_height = await page.evaluate("document.body.scrollHeight || document.documentElement.scrollHeight || 1000")
                steps = min(4, max(2, int(scroll_height // 600)))
                for step in range(1, steps + 1):
                    target_y = int((scroll_height / steps) * step)
                    await page.evaluate(f"window.scrollTo({{ top: {target_y}, behavior: 'smooth' }})")
                    await page.wait_for_timeout(120)
                    progress_pct = int((step / steps) * 100)
                    await _emit_frame(on_frame, page, f"[SCROLLING {progress_pct}%] Inspecting fields, widgets & lazy DOM", safe_url(current))
                await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
                await page.wait_for_timeout(100)
            except Exception:
                pass
            await reveal_navigation(page)
            navigation = await page.evaluate("() => [...document.querySelectorAll('a[href]')].slice(0,120).map(a=>({url:a.href,text:(a.innerText||a.getAttribute('aria-label')||'').slice(0,100)}))")
            links = {x["url"]: x for x in data["links"] + navigation if _link_allowed(x, session.guard.target.origin)}
            info.links = list(links.values())[:60]
            info.observed_get_requests = observed_get[:]
            output.pages.append(info)
            if on_page:
                try:
                    on_page("discovered", {
                        "id": info.id,
                        "url": info.url,
                        "title": info.title,
                        "depth": depth,
                        "forms": len(info.forms),
                        "links": len(info.links),
                        "status_code": info.status_code,
                        "readiness": info.readiness,
                    })
                except Exception:
                    pass
            if depth < settings.max_depth:
                for link in info.links:
                    candidate = normalized_url(link["url"])
                    parts = urlsplit(candidate)
                    if re.search(r"\.(?:pdf|zip|tar|gz|mp4|mp3|png|jpg|svg|woff2?|css|js)$", parts.path, re.I):
                        continue
                    # Canonicalize trailing slashes on non-fragment/non-query URLs to avoid redundant redirect loops
                    canonical = candidate.rstrip("/") if not parts.query and not parts.fragment else candidate
                    seen_canonical = {s.rstrip("/") for s in seen}
                    pending_canonical = {p[0].rstrip("/") for p in pending}
                    if canonical not in seen_canonical and canonical not in pending_canonical and len(pending) < settings.max_pages * 3:
                        pending.append((candidate, depth + 1))
            if collect_functional:
                for error in list(dict.fromkeys(errors))[:5]:
                    output.findings.append(Finding(title="Browser console or script error", pillar=Pillar.FUNCTIONALITY,
                        severity=Severity.MEDIUM, category="console-error", location=Location(url=current),
                        evidence=[Evidence(detail=error)], explanation="The browser reported a script error during page loading. It may prevent part of the page from working; blocked third-party resources can also contribute.",
                        suggested_fix="Reproduce in the browser console, fix the failing script or request, and verify after clearing errors.", sources=["Playwright"],
                        verification_note="Observed in browser; not yet independently reproduced.",
                        check=VerificationSpec(kind="console", data={"url": current, "needle": error[:80]})))
                for response_url, status in list(dict.fromkeys(bad_responses))[:10]:
                    output.findings.append(Finding(title=f"Resource returns HTTP {status}", pillar=Pillar.FUNCTIONALITY,
                        severity=Severity.HIGH if status >= 500 else Severity.MEDIUM, category="http-error", location=Location(url=response_url),
                        evidence=[Evidence(detail=f"GET {response_url}\nHTTP {status}")], explanation="A same-origin request failed while the page was loading.",
                        suggested_fix="Repair the endpoint or asset path and ensure the request returns the intended response.", sources=["Playwright"],
                        check=VerificationSpec(kind="http-status", data={"url": response_url, "status": status})))
                for image in data["images"]:
                    if origin(image["url"]) != session.guard.target.origin:
                        continue
                    output.findings.append(Finding(title="Broken image", pillar=Pillar.FUNCTIONALITY, severity=Severity.LOW,
                        category="broken-image", location=Location(url=current, selector=image["selector"]),
                        evidence=[Evidence(detail=f"Image could not decode: {safe_url(image['url'])}")],
                        explanation="This image did not load or could not be decoded by the browser.",
                        suggested_fix="Fix the image URL, serve a valid image format, and add meaningful alternate text.", sources=["Playwright"],
                        check=VerificationSpec(kind="image", data={"url": current, "selector": image["selector"]})))
        except (PlaywrightError, ValueError) as exc:
            failed_pages += 1
            log(f"Page could not be mapped: {type(exc).__name__}")
            if collect_functional:
                output.findings.append(Finding(title="Page could not load within the time limit", pillar=Pillar.FUNCTIONALITY,
                    severity=Severity.MEDIUM, category="navigation-failure", location=Location(url=url),
                    evidence=[Evidence(detail=redact(str(exc), 700))], explanation="The page did not finish basic navigation within the bounded test window. A slow or restricted environment can cause this too.",
                    suggested_fix="Check server availability and navigation timing; reproduce before treating this as a site defect.", sources=["Playwright"]))
        finally:
            try:
                await page.close()
            except PlaywrightError:
                # A browser shutdown during close should not discard pages already
                # mapped or prevent the remaining pages from being attempted.
                pass
        await asyncio.sleep(0.15)
    readiness = [p.readiness for p in output.pages if p.readiness]
    if not output.pages:
        crawl_status = "failed" if failed_pages else "skipped"
    elif failed_pages or any(not x.get("stable", False) for x in readiness):
        crawl_status = "partial"
    else:
        crawl_status = "completed"
    output.result = ScanResult(status=crawl_status,
        reason=f"Mapped {len(output.pages)} pages. {failed_pages} page failures. Same-origin links only; no mutation submissions." if output.pages else
                f"No pages were successfully mapped; {failed_pages} navigation failures. No positive coverage is inferred.",
        metrics={"pages": len(output.pages), "forms": sum(len(p.forms) for p in output.pages),
                 "failed_pages": failed_pages, "browser_blocked_requests": session.blocked,
                 "readiness": {"pages_observed": len(readiness),
                               "stable_pages": sum(bool(x.get("stable")) for x in readiness),
                               "average_wait_ms": round(sum(x.get("wait_ms", 0) for x in readiness) / max(1, len(readiness))),
                               "strategy": "load-event-plus-dom-stability"}})
    return output


async def check_links(guard: EgressGuard, pages: list[PageInfo], priority_page_ids: list[str] | None = None) -> ScanResult:
    if not pages:
        return ScanResult(status="skipped", reason="No mapped pages; internal links were not assessed.",
                          metrics={"links_discovered": 0, "links_budgeted": 0, "links_checked": 0, "request_failures": 0, "blocked": 0})
    page_priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    ordered_pages = sorted(pages, key=lambda page: page_priority.get(page.id, 10_000))
    # AI can decide which observed pages deserve early attention under the link
    # budget. It cannot introduce links: every URL below came from the crawler.
    discovered_links = list(dict.fromkeys(l["url"] for p in ordered_pages for l in p.links))
    # Keep the request budget explicit: report all observed candidates separately
    # from the subset actually tested so users do not mistake a capped scan for full coverage.
    links = discovered_links[:20]
    if not links:
        return ScanResult(status="skipped", reason="No eligible same-origin links were discovered; link health was not assessed.",
                          metrics={"links_discovered": 0, "links_budgeted": 0, "links_checked": 0, "request_failures": 0, "blocked": 0})
    findings, checked, failures, blocked = [], 0, 0, 0
    async with guard.client() as client:
        for url in links:
            parts = urlsplit(url)
            request_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
            try:
                # Follow only safe same-origin redirects. Raw HEAD/GET calls do not
                # follow redirects by default, which can hide a redirect-to-404 defect.
                response = await safe_fetch(client, request_url, "HEAD")
                if response.status_code == 405:
                    response = await safe_fetch(client, request_url, "GET")
                if response.headers.get("X-UWT-Blocked"):
                    blocked += 1
                    continue
                checked += 1
                broken_redirect = response.status_code in {301, 302, 303, 307, 308} and not response.headers.get("location")
                if response.status_code >= 400 or broken_redirect:
                    status_detail = f"HTTP {response.status_code}" + (" (redirect has no Location header)" if broken_redirect else "")
                    findings.append(Finding(title=f"Broken internal link ({status_detail})", pillar=Pillar.FUNCTIONALITY,
                        severity=Severity.MEDIUM, category="http-error", location=Location(url=url),
                        evidence=[Evidence(detail=f"Safe HEAD/GET {safe_url(url)}\n{status_detail}")],
                        explanation="Following this internal link leads to an error response or an invalid redirect.",
                        suggested_fix="Update or remove the link, repair the redirect destination, or restore the destination page.", sources=["HTTP link checker"],
                        check=VerificationSpec(kind="http-status", data={"url": request_url, "status": response.status_code})))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Network ambiguity is a coverage note, not an invented broken link.
                failures += 1
    status = ("completed" if checked == len(links) and not failures and not blocked else
              "partial" if checked else "blocked" if blocked and not failures else "failed")
    return ScanResult(findings=findings,
                      metrics={"links_discovered": len(discovered_links), "links_budgeted": len(links),
                               "links_checked": checked, "request_failures": failures, "blocked": blocked},
                      status=status,
                      reason=f"Checked {checked}/{len(links)} internal links; {failures} request failures and {blocked} policy blocks. SPA fragments require browser coverage.")


async def test_forms(session: BrowserSession, ai: LocalAI, pages: list[PageInfo], directory: Path, log,
                     priority_page_ids: list[str] | None = None, on_frame = None):
    findings, records = [], []
    candidates = [f for p in pages for f in p.forms]
    if not candidates:
        return ScanResult(status="skipped", reason="No forms or fillable controls were discovered; no form cases executed.",
                          metrics={"forms": 0, "cases_executed": 0, "cases_generated": 0,
                                   "mutation_submissions": 0, "duration_ms": 0}), records
    # AI can prioritize observed pages, but cannot remove baseline coverage. The
    # bounded max_forms budget is spent on recommended pages first, then forms
    # that look high-value by field type.
    page_priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    candidates.sort(key=lambda f: (page_priority.get(f.page_id, 10_000),
                                  not any(x.type == "password" for x in f.fields), f.virtual))
    unique = {}
    for form in candidates:
        unique.setdefault((form.action, tuple(x.selector for x in form.fields)), form)
    forms = list(unique.values())[:session.settings.max_forms]
    lookup = {p.id: p for p in pages}
    for form in forms:
        cases, source = await generate_cases(ai, form, session.settings.max_tests_per_form)
        page_info = lookup[form.page_id]
        field_lookup = {f.id: f for f in form.fields}
        for index, case in enumerate(cases):
            case_started = time.perf_counter()
            case_source = "Ollama-generated" if case.provenance == "Ollama" else "Deterministic fallback (AI unavailable, incomplete or invalid output)"
            log(f"Validation case: {case.name} ({case_source})")
            record = {**case.model_dump(), "source": case_source, "url": page_info.url, "status": "skipped", "observations": [], "submitted": False}
            page = None
            try:
                page = await session.context.new_page()
                await session.navigate(page, page_info.url)
                # Native validation is deliberately offline after the page loads.
                # Prevent even on-input GET callbacks from transmitting test values
                # or triggering a badly designed server-side account action.
                async def no_form_network(route):
                    await route.abort("blockedbyclient")
                await page.route("**/*", no_form_network)
                for field_id, value in case.inputs.items():
                    descriptor = field_lookup[field_id]
                    locator = page.locator(descriptor.selector).first
                    if not await locator.count() or not await locator.is_visible():
                        continue
                    if descriptor.type == "select-one":
                        continue
                    try:
                        await locator.fill(value[:256])
                    except PlaywrightError:
                        # Number/date inputs may sanitize invalid text to empty; use the DOM setter,
                        # still text-only and without submitting or executing generated code.
                        await locator.evaluate("(el, value) => {el.value = value; el.dispatchEvent(new Event('input', {bubbles:true}));}", value[:256])
                    observation = await locator.evaluate("el => ({valid:el.checkValidity(),message:el.validationMessage||'',actual_length:el.value.length,required:el.required,type:el.type})")
                    record["observations"].append({"field_id": field_id, "selector": descriptor.selector, **observation})
                    if case.expected == "reject" and observation["valid"]:
                        findings.append(Finding(title="Expected invalid input is not rejected by native validation",
                            pillar=Pillar.FUNCTIONALITY, severity=Severity.LOW, category="form-validation",
                            location=Location(url=page_info.url, selector=descriptor.selector),
                            evidence=[Evidence(kind="observation", detail=f"Case: {case.name}. Native checkValidity() returned true. No form request was sent.")],
                            explanation="The generated case expected a client-side rejection, but native browser validation accepted it. JavaScript or server validation may still reject it, so this is not a proven server-side defect.",
                            suggested_fix="Confirm the field's intended rules, provide accessible inline feedback, and enforce the same rules on the server.", sources=["Playwright", case_source],
                            verification_note="Client-side observation only; no mutation submission performed."))
                record["status"] = "executed" if record["observations"] else "skipped"
                if record["observations"]:
                    filename = f"{form.id}-case-{index+1}.png"
                    await page.screenshot(path=str(directory / filename), animations="disabled")
                    record["screenshot"] = filename
                    await _emit_frame(on_frame, page, f"[FORM AUDIT] Validating case: {case.name}", page_info.url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A broken selector or an isolated browser error should fail this case,
                # not abort every remaining form case in the pillar.
                record.update(status="failed", error=redact(f"{type(exc).__name__}: {exc}", 400))
            finally:
                record["duration_ms"] = round((time.perf_counter() - case_started) * 1000, 2)
                if page is not None:
                    try:
                        await page.close()
                    except PlaywrightError:
                        pass
            records.append(record)
    findings.extend(static_form_findings(pages))
    executed = sum(r["status"] == "executed" for r in records)
    failed = sum(r["status"] == "failed" for r in records)
    skipped = sum(r["status"] == "skipped" for r in records)
    if not records or executed == 0 and failed == 0:
        status = "skipped"
    elif executed == len(records):
        status = "completed"
    elif executed:
        status = "partial"
    else:
        status = "failed"
    durations = [r.get("duration_ms", 0) for r in records]
    return ScanResult(findings=findings, status=status,
                      reason=f"Executed {executed}/{len(records)} client-side cases; {failed} failed and {skipped} were skipped. No credentials or state-changing submissions; server-side login/checkout behavior remains untested.",
                      metrics={"forms": len(forms), "cases_executed": executed, "cases_generated": len(records),
                               "cases_failed": failed, "cases_skipped": skipped,
                               "duration_ms": round(sum(durations), 2),
                               "average_case_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
                               "mutation_submissions": 0}), records


_EMAIL_NAME = re.compile(r"e-?mail", re.I)


def static_form_findings(pages: list[PageInfo]) -> list[Finding]:
    """Deterministic, low-noise form inspection from the observed DOM (nothing is submitted).

    Flags only: an input whose name/label says "email" but is not type=email, which disables the browser's
    built-in format check. Reported as Possible/Low because server-side validation may still exist.
    """
    findings, seen = [], set()
    for page in pages:
        for form in page.forms:
            for field_ in form.fields:
                label = f"{field_.name} {field_.label}"
                if _EMAIL_NAME.search(label) and field_.type in {"text", "search", ""} and (page.url, field_.id) not in seen:
                    seen.add((page.url, field_.id))
                    findings.append(Finding(title="Email field does not use type=\"email\"", pillar=Pillar.FUNCTIONALITY,
                        severity=Severity.LOW, status="Possible", category="form-email-type",
                        location=Location(url=safe_url(page.url), selector=field_.selector),
                        evidence=[Evidence(kind="observation", detail=f"Field '{field_.name or field_.label}' has input type '{field_.type or 'text'}'. Observed in the page DOM; no request was sent.")],
                        explanation="Without type=email the browser accepts any text, so obviously invalid addresses are only caught (if at all) after submission.",
                        suggested_fix="Use <input type=\"email\" required> and keep server-side validation as the authoritative check.",
                        sources=["DOM form inspection"], verification_note="Static DOM observation. Server-side validation was not tested, so this stays Possible."))
    return findings


async def test_navigation_flows(session: BrowserSession, flows: list[dict], pages: list[PageInfo],
                                priority_page_ids: list[str] | None = None, on_frame = None) -> ScanResult:
    """Replay AI-selected known page sequences; transactional steps are never sent.

    Recommendations can prioritize flows that include an observed page, but the
    test runner still visits only known page IDs and does not submit forms.
    """
    lookup = {p.id: p for p in pages}
    page_priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    def flow_priority(flow):
        positions = [page_priority[pid] for pid in flow.get("page_ids", []) if pid in page_priority]
        return min(positions) if positions else 10_000
    ordered_flows = sorted(flows, key=flow_priority)[:3]
    if not ordered_flows:
        return ScanResult(status="skipped", reason="No AI-proposed known-page flows are available to replay; navigation behavior was not assessed.",
                          metrics={"flows_proposed": len(flows), "flows_replayed": 0, "flows_complete": 0, "mutations_submitted": 0})
    findings, executed, completed = [], 0, 0
    for flow in ordered_flows:
        results = []
        for pid in flow.get("page_ids", [])[:4]:
            if pid not in lookup:
                continue
            info = lookup[pid]
            page = await session.context.new_page()
            try:
                response = await session.navigate(page, info.url)
                await _emit_frame(on_frame, page, f"[USER FLOW] Replaying step: {flow.get('name', 'Flow')} ({safe_url(info.url)})", info.url)
                status = response.status if response else None
                blocked = response and (await response.all_headers()).get("x-uwt-blocked")
                results.append({"page_id": pid, "url": info.url, "http_status": status,
                                "result": "blocked" if blocked else "observed", "submitted": False})
                if status and status >= 400 and not blocked:
                    findings.append(Finding(title=f"Flow '{flow['name']}' reaches an HTTP error", pillar=Pillar.FUNCTIONALITY,
                        severity=Severity.MEDIUM, category="http-error", location=Location(url=info.url),
                        evidence=[Evidence(detail=f"AI-selected navigation-only sequence reached HTTP {status}. No forms submitted.")],
                        explanation="A known page in the suggested user flow returned an error during safe navigation.",
                        suggested_fix="Repair the destination page or update the flow's link, then re-test navigation.", sources=["Playwright flow replay", "Ollama"],
                        check=VerificationSpec(kind="http-status", data={"url": info.url, "status": status})))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                results.append({"page_id": pid, "url": info.url, "result": "unavailable", "reason": type(exc).__name__, "submitted": False})
            finally:
                try:
                    await page.close()
                except PlaywrightError:
                    pass
        flow["observations"] = results
        flow["coverage"] = "Navigation only; authentication, account changes and transactions not submitted."
        flow["status"] = "navigation_observed" if results and all(r["result"] == "observed" for r in results) else "partial"
        executed += bool(results)
        completed += flow["status"] == "navigation_observed"
    replay_status = "completed" if completed == len(ordered_flows) else "partial" if executed else "failed"
    return ScanResult(status=replay_status, findings=findings,
                      metrics={"flows_proposed": len(flows), "flows_replayed": executed, "flows_complete": completed, "mutations_submitted": 0},
                      reason=f"Replayed {executed}/{len(ordered_flows)} AI-selected known-page flows through read-only navigation; {completed} completed all observations.")
