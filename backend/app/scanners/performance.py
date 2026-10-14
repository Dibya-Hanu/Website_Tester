"""Laboratory performance and a separately authorized, tightly capped load run."""
import base64
import csv
import json
import statistics
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.models import Evidence, Finding, Location, Pillar, ScanResult, Severity
from app.core.policy import PolicyError, TargetPolicy, origin, safe_read_url
from app.core.process import run_command
from app.scanners.http_checks import fetch


SLOW_PAGE_MS = 1000
LARGE_RESOURCE_BYTES = 1_000_000
HEAVY_RESOURCE_BYTES = 250_000
MAX_RESOURCES_PER_PAGE = 12


class _ResourceLinks(HTMLParser):
    """Collect same-document sub-resources (scripts, stylesheets, images) from HTML. No execution."""

    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.urls.append(a["src"])
        elif tag == "link" and "stylesheet" in (a.get("rel") or "").lower() and a.get("href"):
            self.urls.append(a["href"])
        elif tag == "img" and a.get("src"):
            self.urls.append(a["src"])


def parse_resource_links(html_text: str, base_url: str) -> list[str]:
    parser = _ResourceLinks()
    try:
        parser.feed(html_text[:500_000])
    except Exception:  # malformed markup must never crash a scan
        pass
    seen, result = set(), []
    for raw in parser.urls:
        if raw.startswith("data:"):
            continue
        absolute = urljoin(base_url, raw)
        if absolute not in seen:
            seen.add(absolute)
            result.append(absolute)
    return result


def classify_page_metrics(pages: list[dict], resources: list[dict]) -> list[Finding]:
    """Pure function: turn measurements into findings (unit-tested without any network)."""
    findings = []
    for page in pages:
        if page["samples_ms"] and min(page["samples_ms"]) > SLOW_PAGE_MS:
            findings.append(Finding(title="Slow page response", pillar=Pillar.PERFORMANCE, severity=Severity.MEDIUM, status="Verified",
                category="performance-slow-page", location=Location(url=page["url"]),
                evidence=[Evidence(kind="metric", detail=f"Complete GET times: {page['samples_ms']} ms (threshold {SLOW_PAGE_MS} ms; every sample exceeded it). Includes safety-proxy overhead.")],
                explanation="Visitors wait over a second for this page's complete response, even when the server is idle.",
                suggested_fix="Profile server-side work for this route, cache expensive results, and avoid blocking calls before the response is sent.",
                sources=["HTTP timer (per-page)"], verification_note="Repeated bounded GET measurements; lab value, not field telemetry."))
    for res in resources:
        size = res["bytes"]
        if size >= HEAVY_RESOURCE_BYTES:
            large = size >= LARGE_RESOURCE_BYTES
            findings.append(Finding(title="Oversized resource" if large else "Heavy resource", pillar=Pillar.PERFORMANCE,
                severity=Severity.MEDIUM if large else Severity.LOW, status="Verified", category="performance-resource-size",
                location=Location(url=res["url"]),
                evidence=[Evidence(kind="metric", detail=f"{res['url']} transferred {size:,} bytes in {res['ms']} ms (referenced from {res['page']}). Decoded body size; compression not credited.")],
                explanation="Large files slow first load, especially on mobile networks.",
                suggested_fix="Minify and compress (gzip/brotli), split or lazy-load rarely used code, resize images, and set long-lived cache headers.",
                sources=["HTTP resource audit"], verification_note="Measured by a direct GET through the safety proxy."))
    return findings


async def audit_pages(guard, page_urls: list[str], limit: int = 8) -> tuple[list[dict], list[dict], dict]:
    """Measure each crawled page twice plus its same-origin sub-resources. GET only, via the safety proxy."""
    page_rows, resource_rows, seen = [], [], set()
    failures = 0
    async with guard.client() as client:
        for url in page_urls[:limit]:
            samples, html_text, size, page_attempts = [], "", 0, 0
            for _ in range(2):
                page_attempts += 1
                start = time.perf_counter()
                try:
                    response = await fetch(client, url)
                except (httpx.HTTPError, PolicyError):
                    failures += 1
                    continue
                if response.status_code >= 400 or response.headers.get("X-UWT-Blocked"):
                    failures += 1
                    continue
                samples.append(round((time.perf_counter() - start) * 1000, 1))
                html_text = response.text if "html" in response.headers.get("content-type", "").lower() else ""
                size = len(response.content)
            row = {"url": url, "samples_ms": samples, "html_bytes": size, "requests": page_attempts, "resource_bytes": 0}
            for res_url in parse_resource_links(html_text, url)[:MAX_RESOURCES_PER_PAGE]:
                if origin(res_url) != origin(url) or not safe_read_url(res_url):
                    continue
                if res_url in seen:
                    continue
                seen.add(res_url)
                row["requests"] += 1
                start = time.perf_counter()
                try:
                    response = await fetch(client, res_url)
                except (httpx.HTTPError, PolicyError):
                    failures += 1
                    continue
                if response.status_code >= 400 or response.headers.get("X-UWT-Blocked"):
                    failures += 1
                    continue
                resource_rows.append({"url": res_url, "bytes": len(response.content), "ms": round((time.perf_counter() - start) * 1000, 1), "page": url})
                row["resource_bytes"] += len(response.content)
            page_rows.append(row)
    return page_rows, resource_rows, {"pages_measured": len(page_rows), "resources_measured": len(resource_rows), "failures": failures}


async def response_timing(guard, page_urls: list[str] | None = None) -> ScanResult:
    samples, failures = [], 0
    async with guard.client() as client:
        for _ in range(3):
            start = time.perf_counter()
            try:
                response = await fetch(client, guard.target.url)
                if response.status_code >= 400 or response.headers.get("X-UWT-Blocked"):
                    failures += 1
                else:
                    samples.append(round((time.perf_counter() - start) * 1000, 2))
            except (httpx.HTTPError, PolicyError):
                failures += 1
    metrics = {"samples_ms": samples, "average_ms": round(statistics.mean(samples), 1) if samples else None,
               "failures": failures, "includes_proxy_overhead": True}
    findings = []
    if samples and statistics.mean(samples) > 800:
        avg = metrics["average_ms"]
        findings.append(Finding(title="Slow initial HTTP response", pillar=Pillar.PERFORMANCE,
            severity=Severity.MEDIUM, status="Verified", category="performance-http", location=Location(url=guard.target.url),
            evidence=[Evidence(kind="metric", detail=f"Mean complete response time: {avg} ms across {len(samples)} GET requests, including safety proxy overhead.")],
            explanation="The server's complete response was slow in this local laboratory test. Network and proxy overhead contribute.",
            suggested_fix="Measure server-side latency, cache appropriate responses, optimize slow queries, and repeat from a representative network.",
            sources=["HTTP timer"], verification_note="Repeated bounded GET measurements; not field/user telemetry."))
    status = "completed" if samples and not failures else "partial" if samples else "failed"
    reason = "Three sequential GET measurements through the safety proxy."
    if page_urls:
        pages_m, resources_m, summary = await audit_pages(guard, page_urls)
        findings += classify_page_metrics(pages_m, resources_m)
        metrics.update(summary)
        metrics["pages"] = [{k: p[k] for k in ("url", "samples_ms", "html_bytes", "requests", "resource_bytes")} for p in pages_m]
        metrics["largest_resources"] = sorted(resources_m, key=lambda r: -r["bytes"])[:5]
        reason += f" Plus per-page timing and sub-resource sizes for {summary['pages_measured']} pages ({summary['resources_measured']} resources)."
        if summary["failures"] and status == "completed":
            status = "partial"
        elif not samples and summary.get("pages_measured", 0) > summary.get("failures", 0):
            status = "partial"
            reason = f"Target seed URL failed initial GET (status >= 400); successfully measured {summary['pages_measured'] - summary['failures']} alternate discovered pages ({summary['resources_measured']} resources)."
    return ScanResult(status=status, reason=reason, metrics=metrics, findings=findings)


async def lighthouse_scan(settings, guard, directory: Path, chromium: str, target_url: str | None = None) -> ScanResult:
    target_url = target_url or guard.target.url
    if origin(target_url) != guard.target.origin or not safe_read_url(target_url):
        return ScanResult(status="blocked", reason="Lighthouse target was not an observed safe URL on the approved origin.")
    if not (settings.tools_dir / "node_modules" / "lighthouse").is_dir():
        return ScanResult(status="skipped", reason="Lighthouse package is unavailable.")
    config = directory / "lighthouse-config.json"
    config.write_text(json.dumps({"url": target_url, "proxy": guard.local_url, "chromium": chromium}))
    try:
        command = await run_command([settings.node_bin, str(settings.tools_dir / "runner.mjs"), "lighthouse", str(config)], timeout=100, cwd=settings.tools_dir)
        if command.returncode:
            return ScanResult(status="failed", reason="Lighthouse could not complete this navigation.", metrics={"exit_code": command.returncode})
        result = json.loads(command.stdout)
        if not isinstance(result, dict):
            return ScanResult(status="failed", reason="Lighthouse returned an unexpected output shape.")
        if result.get("runtimeError"):
            return ScanResult(status="failed", reason="Lighthouse returned a navigation/runtime error.", metrics={"runtime_error": result["runtimeError"]})
        if not isinstance(result.get("audits"), dict) or not isinstance(result.get("score"), (int, float)):
            return ScanResult(status="failed", reason="Lighthouse output was missing a valid score or audit details.")
    except (OSError, ValueError, TimeoutError):
        return ScanResult(status="failed", reason="Lighthouse exceeded its bound or returned invalid output.")
    audits = result["audits"]
    metrics = {"url": target_url, "lighthouse_score": result["score"], "version": result.get("version"),
               "lcp_ms": audits.get("largest-contentful-paint", {}).get("numericValue"),
               "cls": audits.get("cumulative-layout-shift", {}).get("numericValue"),
               "tbt_ms": audits.get("total-blocking-time", {}).get("numericValue"),
               "fcp_ms": audits.get("first-contentful-paint", {}).get("numericValue"),
               "inp_ms": None, "inp_note": "INP requires real interactions/field telemetry; TBT is a lab responsiveness proxy, not INP.",
               "lab_only": True, "warnings": result.get("warnings", [])}
    screenshot = None
    if isinstance(result.get("screenshot"), str) and result["screenshot"].startswith("data:image/"):
        try:
            screenshot = "lighthouse-mobile.jpg"
            (directory / screenshot).write_bytes(base64.b64decode(result["screenshot"].split(",", 1)[1]))
        except ValueError:
            screenshot = None
    findings = []
    checks = [
        ("largest-contentful-paint", "Largest Contentful Paint is slow", 2500, 4000, "performance-lcp",
         "Optimize the main content image, preload critical resources, cache the first response, and reduce render-blocking resources."),
        ("cumulative-layout-shift", "Visible content shifts while loading", .1, .25, "performance-cls",
         "Reserve dimensions for images/embeds, avoid inserting content above existing elements, and use stable font loading."),
        ("total-blocking-time", "JavaScript blocks the main thread", 200, 600, "performance-tbt",
         "Split long JavaScript tasks, defer nonessential scripts, reduce unused code, and move heavy work to Web Workers."),
        ("first-contentful-paint", "First visible content appears slowly", 1800, 3000, "performance-fcp",
         "Reduce blocking CSS, improve server response time, and deliver critical above-the-fold assets earlier."),
    ]
    for audit_id, title, threshold, high, category, fix in checks:
        audit = audits.get(audit_id) or {}
        value = audit.get("numericValue")
        if value is None or value <= threshold:
            continue
        evidence = [Evidence(kind="metric", detail=f"{audit.get('title', title)}: {audit.get('displayValue', round(value,2))}; good threshold <= {threshold}. Lighthouse laboratory mobile run.")]
        if screenshot:
            evidence.append(Evidence(kind="screenshot", file=screenshot, detail="Lighthouse mobile final screenshot."))
        findings.append(Finding(title=title, pillar=Pillar.PERFORMANCE, severity=Severity.HIGH if value > high else Severity.MEDIUM,
            status="Verified", category=category, location=Location(url=guard.target.url), evidence=evidence,
            explanation="This Lighthouse laboratory measurement is outside the recommended range. It is not a real-user percentile and may be affected by blocked third-party assets and container resources.",
            suggested_fix=fix, sources=["Lighthouse"], verification_note="Observed by Lighthouse; repeat under representative conditions before making production claims."))
    return ScanResult(status="partial" if any("incomplete" in str(w).lower() for w in result.get("warnings", [])) else "completed", findings=findings, metrics=metrics, reason="Mobile laboratory Lighthouse. LCP/CLS/TBT/FCP measured; field INP not fabricated.")


async def load_scan(policy: TargetPolicy, guard, settings, directory: Path, pages) -> ScanResult:
    try:
        policy.require_authorized(guard.target.url, "Concurrent load test")
    except PolicyError as exc:
        return ScanResult(status="blocked", reason=str(exc))
    if not settings.load_enabled:
        return ScanResult(status="skipped", reason="Load testing disabled by deployment configuration.")
    users, seconds = min(settings.max_users, 20), min(settings.load_seconds, 30)
    p = urlsplit(guard.target.url)
    host = f"{p.scheme}://{p.netloc}"
    paths = []
    for url in [guard.target.url, *[x.url for x in pages[:2]]]:
        parts = urlsplit(url)
        if origin(url) == guard.target.origin and safe_read_url(url):
            paths.append(urlunsplit(("", "", parts.path or "/", parts.query, "")))
    if not paths:
        return ScanResult(status="blocked", reason="No safe GET paths for load test.")
    config = directory / "load-config.json"
    result_file = directory / "load-summary.json"
    result_file.unlink(missing_ok=True)
    config.write_text(json.dumps({"authorized": True, "users": users, "seconds": seconds,
        "proxy": guard.local_url, "ca_file": str(guard.ca_file), "paths": list(dict.fromkeys(paths)),
        "result_file": str(result_file), "user_agent": settings.user_agent}))
    prefix = directory / "load"
    try:
        command = await run_command([
            sys.executable, "-m", "locust", "-f", str(settings.tools_dir / "locustfile.py"),
            "--headless", "--host", host, "--users", str(users), "--spawn-rate", str(min(users, 4)),
            "--run-time", f"{seconds}s", "--stop-timeout", "0", "--csv", str(prefix),
            "--only-summary", "--skip-log-setup", "--exit-code-on-error", "0",
        ], timeout=seconds + 20, env={"UWT_LOAD_CONFIG": str(config), "LOCUST_CLOUD": "false"})
    except (OSError, TimeoutError):
        return ScanResult(status="failed", reason="Bounded Locust run could not finish; process group terminated.")
    stats_file = directory / "load_stats.csv"
    if command.returncode or not stats_file.exists():
        return ScanResult(status="failed", reason="Locust did not produce valid statistics.", metrics={"exit_code": command.returncode})
    with stats_file.open() as source:
        rows = list(csv.DictReader(source))
    row = next((r for r in rows if r.get("Name") == "Aggregated"), rows[-1] if rows else {})
    def number(key):
        try:
            return float(row.get(key, 0) or 0)
        except ValueError:
            return 0.0
    metrics = {
        "users": users, "seconds": seconds, "requests": int(number("Request Count")),
        "failures": int(number("Failure Count")), "average_ms": round(number("Average Response Time"), 2),
        "p50_ms": number("50%"), "p95_ms": number("95%"), "requests_per_second": number("Requests/s"),
        "global_rate_cap": settings.proxy_rate,
    }
    if result_file.exists():
        try:
            extra_metrics = json.loads(result_file.read_text(encoding="utf-8"))
            if isinstance(extra_metrics, dict):
                metrics.update(extra_metrics)
            else:
                return ScanResult(status="failed", reason="Locust summary file had an invalid shape; no pass is inferred.", metrics=metrics)
        except (OSError, ValueError, TypeError):
            return ScanResult(status="failed", reason="Locust summary file could not be read; no pass is inferred.", metrics=metrics)
    if metrics["requests"] < 1:
        return ScanResult(status="failed", reason="Locust output contained no measured requests; no performance pass is inferred.", metrics=metrics)
    findings = []
    if metrics["failures"] or metrics.get("circuit_breaker"):
        findings.append(Finding(title="Errors observed during capped light load", pillar=Pillar.PERFORMANCE,
            severity=Severity.MEDIUM, status="Verified", category="performance-load-errors", location=Location(url=guard.target.url),
            evidence=[Evidence(kind="metric", detail=json.dumps(metrics))],
            explanation="The site returned failures during a short, low-concurrency read-only run. The test stops early on backoff responses or repeated errors.",
            suggested_fix="Inspect application logs and resource saturation, fix failing requests, and re-test cautiously with owner-approved limits.", sources=["Locust"],
            verification_note="Measured within the hard load caps; not a stress or capacity certification."))
    if metrics["p95_ms"] > 1500:
        findings.append(Finding(title="Slow responses under light concurrency", pillar=Pillar.PERFORMANCE,
            severity=Severity.MEDIUM, status="Verified", category="performance-load-latency", location=Location(url=guard.target.url),
            evidence=[Evidence(kind="metric", detail=f"95th percentile: {metrics['p95_ms']} ms; users: {users}; maximum duration: {seconds}s")],
            explanation="Some requests became slow in the capped laboratory run, including proxy overhead.",
            suggested_fix="Profile request queues, database latency and cache misses. Repeat from a representative machine before setting production targets.", sources=["Locust"], verification_note="Observed Locust percentile; small sample and lab-only."))
    return ScanResult(status="partial" if metrics.get("circuit_breaker") else "completed", findings=findings, metrics=metrics,
                      reason=metrics.get("circuit_breaker") or f"GET-only load: {users} users / {seconds}s, capped at 20 / 30 with early-stop protection.")
