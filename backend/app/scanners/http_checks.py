"""Small, non-destructive custom security checks on explicitly authorized origins."""
import html
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from app.core.models import Evidence, Finding, Location, Pillar, ScanResult, Severity, VerificationSpec
from app.core.policy import PolicyError, TargetPolicy, origin, safe_read_url
from app.core.redact import SECRET_KEY, redact, safe_url

SQL_ERRORS = re.compile(r"SQLITE_ERROR|SQL syntax.*?MySQL|unterminated quoted string|syntax error at or near|ORA-\d{5}|Unclosed quotation mark", re.I)
ENV_LINE = re.compile(r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=\s*[^\n]+$")


async def fetch(client: httpx.AsyncClient, url: str, method: str = "GET") -> httpx.Response:
    target_origin = origin(url)
    for _ in range(4):
        response = await client.request(method, url)
        if response.status_code not in {301, 302, 303, 307, 308} or "location" not in response.headers:
            return response
        next_url = urljoin(url, response.headers["location"])
        if origin(next_url) != target_origin or not safe_read_url(next_url):
            raise PolicyError("Unsafe redirect refused.")
        url = next_url
    raise PolicyError("Redirect limit exceeded.")


def file_signature(path: str, response: httpx.Response) -> tuple[bool, str]:
    if response.status_code != 200 or "html" in response.headers.get("content-type", "").lower():
        return False, "Not a matching exposed file."
    text = response.text[:16_000]
    if path == "/.git/HEAD":
        match = re.fullmatch(r"\s*(?:ref: refs/[\w/._-]+|[0-9a-f]{40})\s*", text)
        return bool(match), "Git HEAD reference was returned; body omitted." if match else "Not a Git HEAD reference."
    if path == "/.env":
        keys = ENV_LINE.findall(text)
        secret_keys = [k for k in keys if SECRET_KEY.search(k)]
        matched = len(keys) >= 2 and bool(secret_keys)
        return matched, f"Environment-style keys detected ({len(keys)}); sensitive key names: {', '.join(secret_keys[:5])}. All values withheld." if matched else "No sensitive environment-file signature."
    return False, "Unknown signature."


def _issue(title: str, severity: Severity, category: str, url: str, detail: str, explanation: str,
           fix: str, *, header: str | None = None, check=None, status="Possible") -> Finding:
    return Finding(title=title, pillar=Pillar.SECURITY, severity=severity, category=category,
                   location=Location(url=safe_url(url), header=header), status=status,
                   evidence=[Evidence(detail=redact(detail))], explanation=explanation,
                   suggested_fix=fix, sources=["Custom HTTP checks"], check=check)


def header_findings(url: str, response: httpx.Response) -> list[Finding]:
    headers = response.headers
    findings = []
    required = [
        ("content-security-policy", Severity.MEDIUM, "Content Security Policy is missing",
         "The browser has no site-defined policy restricting script and resource execution. This is a defense-in-depth gap, not proof of an injection vulnerability.",
         "Deploy a tested Content-Security-Policy using nonce- or hash-based script-src, object-src 'none', base-uri 'self', and explicit frame-ancestors. Start with Report-Only if needed."),
        ("x-content-type-options", Severity.LOW, "Content type sniffing protection is missing",
         "The browser may guess a resource's content type instead of respecting the declared type.",
         "Return X-Content-Type-Options: nosniff and correct Content-Type headers for every response."),
        ("referrer-policy", Severity.LOW, "Referrer Policy is missing",
         "The site relies on browser defaults for information sent in the Referer header.",
         "Set Referrer-Policy: strict-origin-when-cross-origin, or a stricter policy appropriate for sensitive pages."),
    ]
    if urlsplit(url).scheme == "https":
        required.append(("strict-transport-security", Severity.MEDIUM, "HTTPS enforcement header is missing",
                         "Returning HTTPS alone does not tell browsers to avoid future insecure HTTP connections.",
                         "After ensuring all relevant hosts support HTTPS, set Strict-Transport-Security: max-age=31536000; includeSubDomains."))
    for header, severity, title, explanation, fix in required:
        if header not in headers:
            findings.append(_issue(title, severity, f"header-{header}", url, f"HTTP {response.status_code}\n{header}: absent", explanation, fix,
                header=header, check=VerificationSpec(kind="header-missing", data={"url": url, "header": header})))
    csp = headers.get("content-security-policy", "")
    if "x-frame-options" not in headers and "frame-ancestors" not in csp.lower():
        findings.append(_issue("Framing protection is missing", Severity.MEDIUM, "header-framing", url,
            "Neither X-Frame-Options nor CSP frame-ancestors is present.",
            "Other sites may embed this page in a frame. Actual clickjacking impact depends on sensitive controls and other defenses.",
            "Set CSP frame-ancestors 'none' or an explicit trusted origin list; use X-Frame-Options: DENY/SAMEORIGIN for older browsers.",
            header="x-frame-options", check=VerificationSpec(kind="framing", data={"url": url})))
    script_src = re.search(r"(?:^|;)\s*script-src\s+([^;]+)", csp, re.I)
    if script_src and "'unsafe-inline'" in script_src.group(1) and not re.search(r"'nonce-|sha(?:256|384|512)-", script_src.group(1)):
        findings.append(_issue("Content Security Policy permits inline scripts", Severity.LOW, "csp-unsafe-inline", url,
            "script-src includes 'unsafe-inline' without a nonce or hash.",
            "Allowing arbitrary inline scripts weakens the protection a CSP can provide against injected markup.",
            "Replace unsafe-inline with per-response nonces or hashes and move inline handlers to vetted script files.", header="content-security-policy"))
    return findings


def cookie_findings(url: str, response: httpx.Response) -> list[Finding]:
    findings = []
    for raw in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            continue
        for name, morsel in cookie.items():
            session_like = bool(re.search(r"sess|sid|auth|token|jwt|connect", name, re.I))
            missing = []
            if session_like and not morsel["httponly"]:
                missing.append("HttpOnly")
            if session_like and urlsplit(url).scheme == "https" and not morsel["secure"]:
                missing.append("Secure")
            if morsel["samesite"].lower() == "none" and not morsel["secure"]:
                missing.append("Secure (required with SameSite=None)")
            if missing:
                findings.append(_issue(f"Cookie '{name}' is missing protective flags", Severity.MEDIUM,
                    f"cookie-flags-{name}", url, f"Set-Cookie: {name}=[REDACTED]; missing: {', '.join(missing)}",
                    "A session-like cookie lacks browser protections, increasing exposure if other weaknesses are present.",
                    "For authentication/session cookies use Secure; HttpOnly; SameSite=Lax or Strict as appropriate. Keep intentionally script-readable preference cookies separate.",
                    header="set-cookie", check=VerificationSpec(kind="cookie", data={"url": url, "name": name, "missing": missing})))
    return findings


async def custom_security(
    policy: TargetPolicy, guard, pages, priority_page_ids: list[str] | None = None,
) -> ScanResult:
    try:
        policy.require_authorized(guard.target.url, "Security checks")
    except PolicyError as exc:
        return ScanResult(status="blocked", reason=str(exc))
    url = guard.target.url
    base = urlsplit(url)
    root = urlunsplit((base.scheme, base.netloc, "/", "", ""))
    findings, metrics = [], {"requests": 0, "robots_txt": False, "probe_parameters": 0, "page_results": []}
    errors = 0
    priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    ordered_pages = sorted(pages, key=lambda page: priority.get(page.id, 10_000))
    async with guard.client() as client:
        try:
            response = await fetch(client, url)
            metrics["requests"] += 1
            if response.headers.get("X-UWT-Blocked"):
                return ScanResult(status="partial", reason="Target response was blocked by the safety policy.", metrics=metrics)
            findings.extend(header_findings(url, response))
            findings.extend(cookie_findings(url, response))
            metrics["page_results"].append({"url": url, "status": "completed"})
        except (httpx.HTTPError, PolicyError):
            return ScanResult(status="failed", reason="Target HTTP response could not be inspected.",
                              metrics={**metrics, "page_results": [{"url": url, "status": "failed"}]})
        # Always inspect the submitted URL. Up to two additional observed pages
        # selected by AI may receive header/cookie review; AI never supplies URLs.
        prioritized_urls = []
        seen_security_urls = {url}
        for page in ordered_pages:
            candidate = page.url
            if (page.id in priority and candidate not in seen_security_urls
                    and origin(candidate) == guard.target.origin and safe_read_url(candidate)):
                seen_security_urls.add(candidate)
                prioritized_urls.append(candidate)
            if len(prioritized_urls) >= 2:
                break
        for page_url in prioritized_urls:
            try:
                page_response = await fetch(client, page_url)
                metrics["requests"] += 1
                if page_response.headers.get("X-UWT-Blocked"):
                    metrics["page_results"].append({"url": page_url, "status": "blocked"})
                    errors += 1
                    continue
                findings.extend(header_findings(page_url, page_response))
                findings.extend(cookie_findings(page_url, page_response))
                metrics["page_results"].append({"url": page_url, "status": "completed"})
            except (httpx.HTTPError, PolicyError, ValueError):
                metrics["page_results"].append({"url": page_url, "status": "failed"})
                errors += 1
        metrics["security_pages_reviewed"] = sum(item["status"] == "completed" for item in metrics["page_results"])
        for path in ["/.git/HEAD", "/.env", "/robots.txt"]:
            file_url = urljoin(root, path)
            try:
                response = await fetch(client, file_url)
                metrics["requests"] += 1
                if path == "/robots.txt":
                    metrics["robots_txt"] = response.status_code == 200 and "html" not in response.headers.get("content-type", "")
                    metrics["robots_disallow_count"] = len(re.findall(r"(?im)^disallow:", response.text[:16000])) if metrics["robots_txt"] else 0
                    continue  # robots.txt is expected public metadata, not a vulnerability by itself.
                matched, detail = file_signature(path, response)
                if matched:
                    findings.append(_issue("Git repository metadata is publicly exposed" if path.startswith("/.git") else "Sensitive environment file is publicly exposed",
                        Severity.HIGH, "exposed-git" if path.startswith("/.git") else "exposed-env", file_url,
                        f"GET {file_url}\nHTTP 200\n{detail}",
                        "A deployment file that should not be public can be read without authentication. Values are not stored by this tester.",
                        "Deny access to dotfiles at the web server, remove them from the public directory, and rotate any exposed credentials after an owner-led review.",
                        check=VerificationSpec(kind="file-signature", data={"url": file_url, "path": path})))
            except (httpx.HTTPError, PolicyError):
                errors += 1
        candidates = []
        for page in ordered_pages:
            for observed_url in [page.url, *page.observed_get_requests]:
                pairs = parse_qsl(urlsplit(observed_url).query, keep_blank_values=True)
                for key, _ in pairs:
                    if key.lower() in {"q", "query", "search", "s", "term", "keyword", "id"} and not SECRET_KEY.search(key):
                        candidates.append((observed_url, key))
        # Discover GET search parameters from forms, but do not guess API endpoints or submit data.
        for page in pages:
            for form in page.forms:
                if form.method == "GET" and origin(form.action) == guard.target.origin:
                    for control in form.fields:
                        if control.name.lower() in {"q", "query", "search", "s", "term", "keyword"}:
                            candidates.append((form.action, control.name))
        for probe_url, key in list(dict.fromkeys(candidates))[:2]:
            try:
                p = urlsplit(probe_url)
                pairs = dict(parse_qsl(p.query, keep_blank_values=True))
                baseline = await fetch(client, probe_url)
                marker = "uwt-" + uuid4().hex[:10]
                payload = f'<uwt-probe data-id="{marker}">{marker}</uwt-probe>'
                pairs[key] = payload
                reflection_url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(pairs), ""))
                reflected = await fetch(client, reflection_url)
                metrics["requests"] += 2
                metrics["probe_parameters"] += 1
                if "html" in reflected.headers.get("content-type", "").lower() and payload in reflected.text and html.escape(payload) not in reflected.text:
                    findings.append(_issue("Unescaped input reflection may permit HTML injection", Severity.MEDIUM, "inert-reflection", probe_url,
                        f"Parameter: {key}\nAn inert <uwt-probe> tag was returned literally in HTML. No executable script was sent.",
                        "A harmless HTML marker was reflected without escaping. Context and browser defenses determine whether this could become exploitable XSS; exploitation was not attempted.",
                        "Use context-aware output encoding, avoid unsafe innerHTML, validate input, and apply a restrictive CSP.",
                        check=VerificationSpec(kind="reflection", data={"url": probe_url, "key": key, "payload": payload})))
                pairs[key] = "uwt_probe'"
                sql_url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(pairs), ""))
                sql_response = await fetch(client, sql_url)
                metrics["requests"] += 1
                signal = SQL_ERRORS.search(sql_response.text[:100_000])
                if signal and not SQL_ERRORS.search(baseline.text[:100_000]):
                    findings.append(_issue("Database error signal after a punctuation probe", Severity.MEDIUM, "sqli-signal", probe_url,
                        f"Parameter: {key}; punctuation-only probe\nHTTP {sql_response.status_code}\nSignal: {signal.group(0)[:150]}",
                        "A single quotation mark produced a database-style error absent from the normal response. This is a possible SQL injection or error-handling issue, not a confirmed exploit.",
                        "Use parameterized queries, validate types, and return generic public errors while keeping detailed database errors in private logs.",
                        check=VerificationSpec(kind="sql-signal", data={"url": sql_url, "baseline_url": probe_url})))
            except (httpx.HTTPError, PolicyError, ValueError):
                errors += 1
    return ScanResult(findings=findings, metrics=metrics, status="partial" if errors else "completed",
                      reason=f"Read-only headers, cookies, file signatures; probed {metrics['probe_parameters']} observed GET parameters with inert payloads. {errors} request failures.")
