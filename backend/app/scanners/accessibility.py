"""axe-core in Playwright, independently complemented by Pa11y/HTML_CodeSniffer."""
import json
from pathlib import Path

from app.core.config import Settings
from app.core.models import Evidence, Finding, Location, Pillar, ScanResult, Severity
from app.core.process import run_command
from app.core.redact import redact, safe_url
from app.scanners.browser import BrowserSession

IMPACT = {"critical": Severity.HIGH, "serious": Severity.HIGH, "moderate": Severity.MEDIUM, "minor": Severity.LOW}


async def axe_scan(session: BrowserSession, pages, directory: Path, priority_page_ids: list[str] | None = None, on_frame = None) -> ScanResult:
    if not pages:
        return ScanResult(status="skipped", reason="No pages were discovered; axe-core did not run.",
                          metrics={"pages_audited": 0, "violations": 0, "page_errors": 0, "page_results": []})
    script = session.settings.tools_dir / "node_modules" / "axe-core" / "axe.min.js"
    if not script.is_file():
        return ScanResult(status="skipped", reason="axe-core package is not installed.")
    findings, scanned, errors = [], 0, 0
    page_results = []
    priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    ordered_pages = sorted(pages, key=lambda page: priority.get(page.id, 10_000))
    for info in ordered_pages[:session.settings.max_pages]:
        page = await session.context.new_page()
        try:
            await session.navigate(page, info.url)
            if on_frame:
                try:
                    from app.scanners.browser import _emit_frame
                    await _emit_frame(on_frame, page, f"[ACCESSIBILITY] axe-core WCAG 2.1 inspecting: {safe_url(info.url)}", safe_url(info.url))
                except Exception:
                    pass
            await page.add_script_tag(path=str(script))
            result = await page.evaluate("""async () => {
                const r = await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}});
                return {violations:r.violations.map(v=>({id:v.id,help:v.help,impact:v.impact,description:v.description,helpUrl:v.helpUrl,
                  nodes:v.nodes.slice(0,6).map(n=>({target:n.target,html:n.html.slice(0,500),summary:n.failureSummary}))})),passes:r.passes.length,incomplete:r.incomplete.length};
            }""")
            scanned += 1
            page_results.append({"url": info.url, "status": "completed"})
            for violation in result["violations"]:
                for node in violation["nodes"]:
                    evidence = [Evidence(detail=redact(node.get("summary") or violation["description"], 1600)), Evidence(detail=redact(node["html"], 500))]
                    if info.screenshots.get("desktop"):
                        evidence.append(Evidence(kind="screenshot", file=info.screenshots["desktop"], detail="Page screenshot; selector identifies the affected element."))
                    findings.append(Finding(title=violation["help"], pillar=Pillar.ACCESSIBILITY,
                        severity=IMPACT.get(violation["impact"], Severity.LOW), status="Verified",
                        category=f"a11y-{violation['id']}", location=Location(url=info.url, selector=" / ".join(str(t) for t in node["target"])),
                        evidence=evidence, explanation=violation["description"],
                        suggested_fix=f"Correct the affected element according to the {violation['id']} rule, then re-run axe-core. Guidance: {violation['helpUrl']}",
                        sources=["axe-core"], verification_note="Observed by axe-core's DOM accessibility rule. Manual WCAG assessment is still needed."))
        except Exception as exc:
            errors += 1
            page_results.append({"url": info.url, "status": "failed", "reason": type(exc).__name__})
        finally:
            await page.close()
    return ScanResult(findings=findings, metrics={"pages_audited": scanned, "violations": len(findings), "page_errors": errors,
                                                 "page_results": page_results},
                      status="completed" if scanned and not errors else "partial" if scanned else "failed",
                      reason=f"axe-core audited {scanned} pages; {errors} pages could not be audited.")


def _pa11y_category(issue: dict) -> str:
    message = issue.get("message", "").lower()
    if "contrast" in message:
        return "a11y-color-contrast"
    if "alternative text" in message or "alt attribute" in message:
        return "a11y-image-alt"
    if "label" in message and "input" in message:
        return "a11y-label"
    return "pa11y-" + issue.get("code", "unknown")


async def pa11y_scan(settings: Settings, guard, pages, directory: Path, chromium: str,
                    priority_page_ids: list[str] | None = None) -> ScanResult:
    if not (settings.tools_dir / "node_modules" / "pa11y").is_dir():
        return ScanResult(status="skipped", reason="Pa11y is not installed.")
    findings, audited, errors = [], 0, 0
    page_results = []
    priority = {page_id: index for index, page_id in enumerate(priority_page_ids or [])}
    ordered_pages = sorted(pages, key=lambda page: priority.get(page.id, 10_000))
    for info in ordered_pages[:3]:
        config = directory / "pa11y-config.json"
        config.write_text(json.dumps({"url": info.url, "proxy": guard.local_url, "chromium": chromium,
                                      "timeout": int(settings.request_timeout * 1000) + 10000}))
        try:
            output = await run_command([settings.node_bin, str(settings.tools_dir / "runner.mjs"), "pa11y", str(config)], timeout=50, cwd=settings.tools_dir)
            if output.returncode:
                errors += 1
                page_results.append({"url": info.url, "status": "failed", "reason": "Pa11y exited unsuccessfully."})
                continue
            result = json.loads(output.stdout)
            if not isinstance(result, dict) or not isinstance(result.get("issues", []), list):
                errors += 1
                page_results.append({"url": info.url, "status": "failed", "reason": "Invalid Pa11y output shape."})
                continue
            audited += 1
            page_results.append({"url": info.url, "status": "completed", "issues": len(result.get("issues", []))})
            for issue in result.get("issues", [])[:40]:
                if not isinstance(issue, dict):
                    continue
                findings.append(Finding(title=str(issue.get("message", "Accessibility concern"))[:220], pillar=Pillar.ACCESSIBILITY,
                    severity=Severity.MEDIUM if issue.get("type") == "error" else Severity.LOW,
                    status="Verified" if issue.get("type") == "error" else "Possible", category=_pa11y_category(issue), location=Location(url=info.url, selector=str(issue.get("selector") or "") or None),
                    evidence=[Evidence(detail=redact(f"{issue.get('code')}\n{issue.get('context', '')}", 1200))],
                    explanation=redact(issue.get("message", "An accessibility rule failed."), 2000),
                    suggested_fix="Correct the semantic markup or style described by this WCAG rule and verify with Pa11y plus keyboard testing.",
                    sources=["Pa11y / HTML_CodeSniffer"], verification_note="Independently observed by Pa11y's WCAG2AA rule engine."))
        except (ValueError, OSError, TimeoutError):
            errors += 1
            page_results.append({"url": info.url, "status": "failed", "reason": "Pa11y process or output failed."})
    if not pages:
        status = "skipped"
    elif audited and not errors:
        status = "completed"
    elif audited:
        status = "partial"
    else:
        status = "failed"
    return ScanResult(findings=findings, status=status,
                      reason=f"Pa11y audited {audited} pages; {errors} failures.",
                      metrics={"pages_audited": audited, "violations": len(findings), "page_errors": errors,
                               "page_results": page_results})
