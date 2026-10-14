"""Deterministic, bounded re-tests. AI cannot set verification status."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from playwright.async_api import Error as PlaywrightError

from app.core.models import Evidence, Finding
from app.core.policy import PolicyError
from app.core.redact import redact
from app.scanners.http_checks import SQL_ERRORS, cookie_findings, fetch, file_signature


async def verify_findings(findings: list[Finding], guard, browser=None) -> dict:
    confirmed = contradicted = attempted = 0
    cache = {}
    async with guard.client() as client:
        for finding in findings[:100]:
            spec = finding.check
            if not spec:
                continue
            key = (spec.kind, str(sorted(spec.data.items())))
            if key in cache:
                matched, note, eligible = cache[key]
            else:
                attempted += 1
                matched, note, eligible = None, "Re-test unavailable.", True
                data = spec.data
                try:
                    if spec.kind in {"header-missing", "framing", "file-signature", "cookie", "http-status", "sql-signal", "reflection"}:
                        url = data["url"]
                        if spec.kind == "reflection":
                            p = urlsplit(url)
                            pairs = dict(parse_qsl(p.query, keep_blank_values=True))
                            pairs[data["key"]] = data["payload"]
                            url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(pairs), ""))
                        response = await fetch(client, url)
                        if response.headers.get("X-UWT-Blocked"):
                            raise PolicyError("Re-test blocked by safety policy.")
                        if spec.kind == "header-missing":
                            matched = data["header"] not in response.headers
                            note = f"Independent GET: {data['header']} {'absent' if matched else 'present'}."
                        elif spec.kind == "framing":
                            matched = "x-frame-options" not in response.headers and "frame-ancestors" not in response.headers.get("content-security-policy", "").lower()
                            note = "Independent GET confirmed absent framing defenses." if matched else "Framing protection was present on re-test."
                        elif spec.kind == "file-signature":
                            matched, note = file_signature(data["path"], response)
                        elif spec.kind == "cookie":
                            matched = any(f.category == f"cookie-flags-{data['name']}" for f in cookie_findings(url, response))
                            note = "Cookie flags re-inspected; values withheld."
                        elif spec.kind == "http-status":
                            matched = response.status_code == data["status"]
                            note = f"Independent GET returned HTTP {response.status_code}."
                        elif spec.kind == "reflection":
                            matched = data["payload"] in response.text and "html" in response.headers.get("content-type", "").lower()
                            eligible = False  # Reproducing inert reflection does not prove executable XSS.
                            note = "Inert HTML reflection reproduced; exploitability remains unproven." if matched else "Inert reflection was not reproduced."
                        elif spec.kind == "sql-signal":
                            baseline = await fetch(client, data["baseline_url"])
                            matched = bool(SQL_ERRORS.search(response.text[:100000])) and not SQL_ERRORS.search(baseline.text[:100000])
                            eligible = False
                            note = "Punctuation-triggered SQL error signal reproduced; injection not proven." if matched else "SQL error signal was not reproduced."
                    elif browser and spec.kind in {"console", "image"}:
                        page = await browser.context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                        try:
                            await browser.navigate(page, data["url"])
                            if spec.kind == "console":
                                matched = any(data["needle"] in message for message in errors)
                                note = "Console error reproduced on independent navigation." if matched else "Console error was not reproduced."
                            else:
                                locator = page.locator(data["selector"]).first
                                matched = await locator.count() > 0 and await locator.evaluate("img => img.complete && img.naturalWidth === 0")
                                note = "Image decode failure reproduced." if matched else "Image failure was not reproduced."
                        finally:
                            await page.close()
                except (httpx.HTTPError, PolicyError, ValueError, RuntimeError, PlaywrightError) as exc:
                    matched = None
                    note = f"Independent re-test unavailable ({type(exc).__name__}); remains Possible."
                cache[key] = (matched, note, eligible)
            finding.verification_note = redact(note, 700)
            finding.evidence.append(Evidence(kind="observation", detail=finding.verification_note))
            if matched is True and eligible:
                finding.status = "Verified"
                confirmed += 1
            elif matched is False:
                finding.status = "Possible"
                finding.contradicted = True
                contradicted += 1
    return {"retests": attempted, "confirmed_findings": confirmed, "contradicted_findings": contradicted}
