"""OWASP ZAP API passive baseline, seeded by the bounded safe crawl.

No active scan, AJAX spider, autonomous crawler, form posts or authentication.
A mandatory proxy configuration failure stops this adapter before target access.
"""
import asyncio
import re
from urllib.parse import urldefrag, urlsplit

import httpx

from app.core.models import Evidence, Finding, Location, Pillar, ScanResult, Severity, VerificationSpec
from app.core.policy import PolicyError, TargetPolicy, origin
from app.core.redact import redact, safe_url

HEADER_RULES = {
    "10038": ("content-security-policy", "header-content-security-policy"),
    "10020": ("x-frame-options", "header-framing"),
    "10021": ("x-content-type-options", "header-x-content-type-options"),
    "10035": ("strict-transport-security", "header-strict-transport-security"),
}
RISK = {"0": Severity.INFO, "1": Severity.LOW, "2": Severity.MEDIUM, "3": Severity.HIGH,
        "Informational": Severity.INFO, "Low": Severity.LOW, "Medium": Severity.MEDIUM, "High": Severity.HIGH}


def plain(value: str) -> str:
    return redact(re.sub(r"<[^>]+>", " ", value)).strip()


async def zap_scan(policy: TargetPolicy, guard, pages, settings) -> ScanResult:
    try:
        policy.require_authorized(guard.target.url, "ZAP baseline")
    except PolicyError as exc:
        return ScanResult(status="blocked", reason=str(exc))
    async with httpx.AsyncClient(base_url=settings.zap_url, timeout=15, trust_env=False) as client:
        async def api(component, kind, action, **params):
            result = await client.get(f"/JSON/{component}/{kind}/{action}/", params={"apikey": settings.zap_api_key, **params})
            result.raise_for_status()
            data = result.json()
            if data.get("code"):
                raise ValueError(f"ZAP API {component}/{action} rejected configuration.")
            return data
        try:
            version = await api("core", "view", "version")
        except (httpx.HTTPError, ValueError):
            return ScanResult(status="skipped", reason="ZAP API is unavailable. No security pass is inferred.")
        try:
            await api("core", "action", "newSession", name="", overwrite="true")
            await api("core", "action", "setMode", mode="safe")
            await api("network", "action", "setHttpProxy", host=settings.proxy_advertised_host, port=str(guard.port))
            await api("network", "action", "setHttpProxyEnabled", enabled="true")
            exclusions = await api("network", "view", "getHttpProxyExclusions")
            for item in exclusions.get("getHttpProxyExclusions", []):
                entry = item.get("exclusion", item)
                if entry.get("host"):
                    await api("network", "action", "setHttpProxyExclusionEnabled", host=entry["host"], enabled="false")
            await api("network", "action", "setConnectionTimeout", timeout=str(int(settings.request_timeout)))
            enabled = await api("network", "view", "isHttpProxyEnabled")
            configured = await api("network", "view", "getHttpProxy")
            proxy = configured.get("getHttpProxy", configured)
            if isinstance(proxy, list):
                proxy = proxy[0]
            if str(enabled.get("isHttpProxyEnabled")).lower() != "true" or proxy.get("host") != settings.proxy_advertised_host or int(proxy.get("port", 0)) != guard.port:
                raise ValueError("ZAP proxy verification failed.")
            await api("pscan", "action", "enableAllScanners")
        except (httpx.HTTPError, ValueError, TypeError):
            return ScanResult(status="failed", reason="ZAP safety/proxy configuration could not be verified; target scan REFUSED.")
        observed = [guard.target.url, *[p.url for p in pages], *[url for p in pages for url in p.observed_get_requests]]
        seeds = list(dict.fromkeys(urldefrag(url)[0] for url in observed))[:settings.max_pages]
        accessed = 0
        try:
            for url in seeds:
                await api("core", "action", "accessUrl", url=url, followRedirects="false")
                accessed += 1
            drained = False
            for _ in range(60):
                pending = await api("pscan", "view", "recordsToScan")
                if int(pending.get("recordsToScan", 0)) == 0:
                    drained = True
                    break
                await asyncio.sleep(1)
            target = urlsplit(guard.target.url)
            alerts = await api("core", "view", "alerts", baseurl=f"{target.scheme}://{target.netloc}", start="0", count="150")
        except (httpx.HTTPError, ValueError):
            return ScanResult(status="partial", reason="ZAP passive scan did not finish cleanly.", metrics={"seed_urls": accessed, "version": version.get("version", "unknown")})
    findings = []
    tool_warnings = []
    for alert in alerts.get("alerts", []):
        if origin(alert.get("url", "")) != guard.target.origin:
            continue
        plugin = str(alert.get("pluginId", ""))
        if plugin == "10116":
            tool_warnings.append("ZAP reported its own version is out of date; this is a scanner limitation, not a website defect.")
            continue
        header, category = HEADER_RULES.get(plugin, (None, f"zap-{plugin}"))
        check = None
        if header:
            check = VerificationSpec(kind="framing" if plugin == "10020" else "header-missing", data={"url": alert["url"], "header": header})
        findings.append(Finding(title=alert.get("alert", "ZAP passive finding")[:220], pillar=Pillar.SECURITY,
            severity=RISK.get(str(alert.get("riskcode", alert.get("risk", "Informational"))), Severity.INFO), category=category,
            location=Location(url=safe_url(alert["url"]), header=header, selector=alert.get("param") or None),
            evidence=[Evidence(detail=redact(f"ZAP rule {plugin}, confidence {alert.get('confidence')}\n{alert.get('evidence', '')}", 1500))],
            explanation=plain(alert.get("description", "Passive scanner signal; requires verification.")),
            suggested_fix=plain(alert.get("solution", "Review the associated ZAP rule and correct the response configuration.")),
            sources=["OWASP ZAP passive baseline"], check=check))
    return ScanResult(findings=findings, status="completed" if drained and not tool_warnings else "partial",
                      reason="Passive baseline over safe crawl seeds; active scan and autonomous spider disabled." + (" " + " ".join(tool_warnings) if tool_warnings else ""),
                      metrics={"seed_urls": accessed, "alerts": len(findings), "passive_queue_drained": drained, "warnings": tool_warnings, "version": version.get("version", "unknown")})
