"""End-to-end pipeline. Every adapter failure is visible and never treated as a pass."""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from app.ai.client import LocalAI
from app.ai.tasks import classify, plan_diagnostics, synthesize, triage, vision
from app.core.config import Settings
from app.core.guard import EgressGuard
from app.core.models import Pillar, Report, ScanResult, Step, now
from app.core.policy import TargetPolicy, normalized_url, origin
from app.core.redact import redact
from app.core.store import Store
from app.pipeline.scoring import apply_ai_merges, deduplicate, rank, score_report
from app.pipeline.verification import verify_findings
from app.scanners.accessibility import axe_scan, pa11y_scan
from app.scanners.browser import BrowserSession, CrawlOutput, check_links, crawl, test_forms, test_navigation_flows
from app.scanners.http_checks import custom_security
from app.scanners.nuclei import nuclei_scan
from app.scanners.performance import lighthouse_scan, load_scan, response_timing
from app.scanners.zap import zap_scan

def ai_task_status(tasks: list[dict]) -> str:
    """Partial accepted output is real work, not a skipped inference."""
    if tasks and all(t["status"] == "completed" for t in tasks):
        return "completed"
    if any(t["status"] in {"completed", "partial"} for t in tasks):
        return "partial"
    return "failed" if any(t["status"] == "failed" for t in tasks) else "skipped"


def serialize_finding(f) -> dict:
    loc_url = ""
    loc_selector = None
    if getattr(f, "location", None):
        loc_url = getattr(f.location, "url", "") or ""
        loc_selector = getattr(f.location, "selector", None)
    pillar_val = f.pillar.value if hasattr(f.pillar, "value") else str(f.pillar)
    sev_val = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
    return {
        "id": f.id,
        "title": f.title,
        "pillar": pillar_val,
        "severity": sev_val,
        "status": f.status,
        "category": f.category or "",
        "url": loc_url,
        "selector": loc_selector,
        "sources": f.sources or [],
        "explanation": f.explanation[:350] if f.explanation else "",
        "suggested_fix": f.suggested_fix[:350] if f.suggested_fix else "",
    }


logger = logging.getLogger(__name__)
PLAN = [
    ("policy", "Authorization & network safety", None),
    ("crawl", "Crawl & map the website", Pillar.FUNCTIONALITY),
    ("ai_map", "AI page classification & flows", None),
    ("ai_plan", "AI adaptive diagnostic plan", None),
    ("ai_tests", "AI cases & safe form validation", Pillar.FUNCTIONALITY),
    ("links", "Internal links & browser errors", Pillar.FUNCTIONALITY),
    ("custom_security", "Headers, cookies & inert probes", Pillar.SECURITY),
    ("zap", "OWASP ZAP passive baseline", Pillar.SECURITY),
    ("nuclei", "Nuclei read-only templates", Pillar.SECURITY),
    ("http_timing", "HTTP response measurements", Pillar.PERFORMANCE),
    ("lighthouse", "Lighthouse performance audit", Pillar.PERFORMANCE),
    ("load", "Capped Locust concurrency test", Pillar.PERFORMANCE),
    ("axe", "axe-core accessibility audit", Pillar.ACCESSIBILITY),
    ("pa11y", "Pa11y independent WCAG checks", Pillar.ACCESSIBILITY),
    ("vision", "AI desktop & mobile visual review", Pillar.ACCESSIBILITY),
    ("verify", "Re-test & deterministic deduplication", None),
    ("triage", "AI security finding triage", Pillar.SECURITY),
    ("synthesis", "AI final report & suggested fixes", None),
]


class Progress:
    def __init__(self, store: Store, jid: str, selected: list[Pillar] | None = None):
        self.store, self.jid = store, jid
        self.selected = set(selected or list(Pillar))
        self.steps = [Step(id=i, title=t, pillar=p) for i, t, p in PLAN]

    def emit(self, event_type: str, **payload):
        """Persist replayable, structured events for the live diagnostic UI."""
        self.store.event(self.jid, {"type": event_type, "timestamp": now(), **payload})

    def log(self, message: str):
        self.emit("log", message=redact(message, 1500))

    def publish_ai_tasks(self, tasks: list[dict]):
        """Republish post-validation task status as well as live model-call status."""
        for task in tasks:
            self.emit("ai_task_update", task={key: task.get(key) for key in (
                "name", "model", "status", "detail", "started_at", "finished_at"
            )})

    def _publish_pillar_activity(self):
        activity = {}
        terminal = {"completed", "partial", "skipped", "blocked", "failed"}
        for pillar in Pillar:
            own = [step for step in self.steps if step.pillar == pillar]
            counts = {status: sum(step.status == status for step in own)
                      for status in ("pending", "running", "completed", "partial", "skipped", "blocked", "failed")}
            finished = sum(counts[key] for key in terminal)
            activity[pillar.value] = {
                "selected": pillar in self.selected,
                "status": "not_selected" if pillar not in self.selected else
                          "running" if counts["running"] or counts["pending"] else
                          "complete" if counts["completed"] == len(own) else "partial",
                "completed_steps": counts["completed"],
                "total_steps": len(own),
                "finished_steps": finished,
                "running_steps": counts["running"],
                "unavailable_steps": counts["skipped"] + counts["blocked"] + counts["failed"],
                "partial_steps": counts["partial"],
                "pipeline_coverage_percent": round(100 * (counts["completed"] + .5 * counts["partial"]) / max(1, len(own))),
            }
        self.emit("pillar_activity", pillars=activity)

    def step(self, sid: str, status: str, detail: str = "", metrics: dict | None = None):
        step = next(s for s in self.steps if s.id == sid)
        step.status = status
        step.detail = redact(detail, 1500)
        if metrics is not None:
            step.metrics = metrics
        if status == "running":
            step.started_at = now()
        else:
            step.finished_at = now()
        finished = sum(s.status not in {"pending", "running"} for s in self.steps)
        state = {"steps": [s.model_dump(mode="json") for s in self.steps], "percent": round(finished / len(self.steps) * 100)}
        self.store.update(self.jid, progress=state)
        self.emit("progress", **state)
        self._publish_pillar_activity()
        self.log(f"{step.title}: {status}{' — ' + detail if detail else ''}")


class Pipeline:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self.policy = TargetPolicy(settings)

    async def run(self, job: dict) -> Report:
        start = time.perf_counter()
        jid, selected = job["id"], [Pillar(p) for p in job["pillars"]]
        directory = self.settings.data_dir / "jobs" / jid
        progress = Progress(self.store, jid, selected)
        ai = LocalAI(self.settings, on_task_update=lambda task: progress.emit("ai_task_update", task=task))
        findings, pages, flows, test_cases, suppressed, diagnostic_plan = [], [], [], [], [], []
        metrics = {}
        limitations = [
            "URL-only black-box snapshot, not a comprehensive penetration test or WCAG certification.",
            "No account creation, credential attempts, payment, upload, mutation method or destructive action is submitted. Server-side login/checkout coverage is intentionally limited.",
            "Only same-origin resources are loaded. Third-party scripts/fonts/images are blocked; rendering and performance may differ from a normal browser.",
            "Laboratory LCP/CLS and TBT are measured. Field Core Web Vitals percentiles and INP are not invented.",
        ]
        progress.step("policy", "running")
        # Enforce the strict competition policy before DNS resolution. The public
        # API checks this too, but the worker repeats it to protect queued/manual jobs.
        if (self.settings.require_allowlist_all_scans or selected == [Pillar.SECURITY]) and not self.policy.is_authorized(job["url"]):
            refused_url = normalized_url(job["url"])
            progress.step("policy", "blocked", "REFUSED: this exact origin is not on the deployment-approved allowlist. No DNS lookup or target requests sent.")
            limitations.append("The entire scan was refused because this exact origin is not deployment-approved. No DNS lookup, scanner, browser, model, or target HTTP requests ran.")
            for step in progress.steps:
                if step.id == "policy":
                    continue
                if step.pillar is not None and step.pillar not in selected:
                    progress.step(step.id, "skipped", "Pillar not selected.")
                else:
                    progress.step(step.id, "blocked", "Target authorization failed. No DNS lookup, target traffic, or AI diagnosis was started.")
            scores, overall, coverage, partial = score_report(selected, [], progress.steps, {})
            progress.emit("diagnostic_plan", status="blocked", detail="Scan refused by the deployment allowlist; no AI inference or target requests ran.",
                          model=self.settings.text_model, inference_confirmed=False, recommendations=[], accepted_count=0,
                          page_count=0, selected_pillars=[pillar.value for pillar in selected])
            progress.emit("verification_summary", phase="final_report", verified=0, possible=0, unresolved=0, total=0)
            directory.mkdir(parents=True, exist_ok=True)
            report = Report(id=jid, url=refused_url, created_at=job["created_at"], finished_at=now(),
                duration_seconds=round(time.perf_counter()-start, 2), selected_pillars=selected,
                authorized=False, overall_score=None, coverage=coverage, partial=True,
                summary="Scan refused: this exact origin is not on the deployment-approved allowlist. No DNS lookup occurred. No scanner, browser, or AI diagnosis ran.",
                scores=scores, findings=[], steps=progress.steps, pages=[], limitations=limitations)
            (directory / "report.json").write_text(report.model_dump_json(indent=2))
            return report

        target = await self.policy.resolve(job["url"])
        progress.step("policy", "completed", "Exact origin approved for the scan." if target.authorized else "Non-allowlisted passive checks enabled by explicit deployment configuration; security and load remain refused.")
        if not target.authorized:
            limitations.append("Security scans and concurrent load were REFUSED because the exact target origin is not allowlisted.")

        if selected == [Pillar.SECURITY] and not target.authorized:
            # No network tools are launched when every selected activity is refused.
            for step in progress.steps:
                if step.id != "policy":
                    progress.step(step.id, "blocked" if step.pillar == Pillar.SECURITY else "skipped", "No authorized selected checks. No target requests sent.")
            scores, overall, coverage, partial = score_report(selected, [], progress.steps, {})
            progress.emit("diagnostic_plan", status="blocked", detail="Security diagnosis refused because the target is not on the approved allowlist.",
                          model=self.settings.text_model, inference_confirmed=False, recommendations=[], accepted_count=0,
                          page_count=0, selected_pillars=[pillar.value for pillar in selected])
            progress.emit("verification_summary", phase="final_report", verified=0, possible=0, unresolved=0, total=0)
            directory.mkdir(parents=True, exist_ok=True)
            report = Report(id=jid, url=target.url, created_at=job["created_at"], finished_at=now(),
                duration_seconds=round(time.perf_counter()-start, 2), selected_pillars=selected,
                authorized=False, overall_score=None, coverage=coverage, partial=True,
                summary="Security testing REFUSED: this exact origin is not on the organizer-approved allowlist. No scanner or target HTTP requests ran.",
                scores=scores, findings=[], steps=progress.steps, pages=[], limitations=limitations)
            (directory / "report.json").write_text(report.model_dump_json(indent=2))
            return report

        async def update_recommendations_for_step(sid: str, status: str, detail: str):
            for recommendation in diagnostic_plan:
                if recommendation.get("execution_step") != sid:
                    continue
                recommendation["execution_status"] = status
                recommendation["execution_detail"] = redact(detail, 350)
                progress.emit("recommendation_update", recommendation=recommendation)

        async def run_scan(sid, factory, *, allowed=True):
            step = next(s for s in progress.steps if s.id == sid)
            if step.pillar and step.pillar not in selected:
                progress.step(sid, "skipped", "Pillar not selected.")
                await update_recommendations_for_step(sid, "skipped", "Pillar not selected.")
                return ScanResult(status="skipped", reason="Pillar not selected.")
            if not allowed:
                progress.step(sid, "blocked", "REFUSED: exact origin is not allowlisted.")
                await update_recommendations_for_step(sid, "skipped", "Blocked by the target-authorization policy.")
                return ScanResult(status="blocked", reason="REFUSED: target is not on the allowlist.")
            progress.step(sid, "running")
            await update_recommendations_for_step(sid, "running", f"{step.title} adapter is running; page-specific execution is not confirmed yet.")
            try:
                result = await factory()
            except Exception as exc:
                logger.exception("Scanner %s failed", sid)
                result = ScanResult(status="failed", reason=f"Adapter failed ({type(exc).__name__}); no pass inferred.")
            findings.extend(result.findings)
            if result.findings:
                pillar_name = step.pillar.value if step.pillar else "general"
                progress.emit("live_findings", step_id=sid, pillar=pillar_name,
                              findings=[serialize_finding(f) for f in result.findings[:12]],
                              total_count=len(findings))
            metrics[sid] = result.metrics
            progress.step(sid, result.status, result.reason, result.metrics)
            interim = "adapter_finished_pending_page_confirmation" if result.status in {"completed", "partial"} else result.status
            await update_recommendations_for_step(sid, interim, result.reason or f"Adapter status: {result.status}; page-level status will be finalized after evidence is collected.")
            return result

        async with EgressGuard(target, self.settings, directory) as guard:
            browser = None
            crawl_output = CrawlOutput()
            chromium = self.settings.chromium_path
            if not chromium:
                async with async_playwright() as pw:
                    chromium = pw.chromium.executable_path
            progress.step("crawl", "running")

            def on_crawl_event(event_type: str, data: dict):
                if event_type == "crawling":
                    progress.emit("crawler_activity", status="crawling", url=data.get("url"), depth=data.get("depth", 0))
                elif event_type == "discovered":
                    progress.emit("crawler_page", page=data)

            def on_frame_event(image: str, action: str, url: str):
                progress.emit("browser_frame", image=image, action=action, url=url)

            try:
                browser = await BrowserSession(guard, self.settings).__aenter__()
                crawl_output = await crawl(browser, directory, progress.log, Pillar.FUNCTIONALITY in selected, on_page=on_crawl_event, on_frame=on_frame_event)
                pages = crawl_output.pages
                findings.extend(crawl_output.findings)
                if crawl_output.findings:
                    progress.emit("live_findings", step_id="crawl", pillar="functionality",
                                  findings=[serialize_finding(f) for f in crawl_output.findings[:12]],
                                  total_count=len(findings))
                metrics["crawl"] = crawl_output.result.metrics
                progress.step("crawl", crawl_output.result.status, crawl_output.result.reason, crawl_output.result.metrics)
                progress.emit("site_map", status=crawl_output.result.status, pages_mapped=len(pages),
                    forms_mapped=sum(len(page.forms) for page in pages),
                    links_mapped=sum(len(page.links) for page in pages),
                    pages=[{"id": page.id, "url": page.url, "title": page.title,
                            "forms": len(page.forms), "links": len(page.links),
                            "classification": page.classification, "readiness": page.readiness}
                           for page in pages[:30]])
            except Exception as exc:
                logger.exception("Browser crawl failed")
                progress.step("crawl", "failed", f"Browser crawl unavailable ({type(exc).__name__}).")
                if browser:
                    await browser.__aexit__(None, None, None)
                    browser = None
            form_priority_page_ids: list[str] = []
            vision_priority_page_ids: list[str] = []
            navigation_priority_page_ids: list[str] = []
            link_priority_page_ids: list[str] = []
            accessibility_priority_page_ids: list[str] = []
            security_priority_page_ids: list[str] = []
            performance_priority_page_ids: list[str] = []
            try:
                progress.step("ai_map", "running")
                flows = await classify(ai, pages)
                progress.publish_ai_tasks(ai.tasks)
                map_tasks = [t for t in ai.tasks if t["name"].startswith("Page classification") or t["name"] == "Key user flow discovery"]
                successful = sum(t["status"] == "completed" for t in map_tasks)
                map_status = ai_task_status(map_tasks)
                progress.step("ai_map", map_status, f"Local classification/flow inference completed {successful}/{len(map_tasks)} bounded tasks. {len(flows)} known-page flows proposed.")
                progress.emit("site_map", phase="classified", status=crawl_output.result.status, pages_mapped=len(pages),
                    forms_mapped=sum(len(page.forms) for page in pages), links_mapped=sum(len(page.links) for page in pages),
                    flows_proposed=len(flows), pages=[{"id": page.id, "url": page.url, "title": page.title,
                        "forms": len(page.forms), "links": len(page.links), "classification": page.classification,
                        "readiness": page.readiness} for page in pages[:30]])

                progress.step("ai_plan", "running")
                planner_error: str | None = None
                try:
                    diagnostic_plan = await plan_diagnostics(ai, pages, selected)
                    progress.publish_ai_tasks(ai.tasks)
                except Exception as exc:
                    logger.exception("Adaptive AI diagnostic planning failed")
                    diagnostic_plan = []
                    planner_error = type(exc).__name__
                plan_tasks = [t for t in ai.tasks if t["name"] == "Adaptive diagnostic plan"]
                plan_status = (ai_task_status(plan_tasks) if plan_tasks else
                               "skipped" if not pages or not self.settings.ai_enabled else
                               "failed" if not diagnostic_plan else "completed")
                # Valid JSON with zero applicable recommendations is not the same
                # as a useful completed plan. Baseline checks still run, but UI and
                # coverage must disclose that adaptive planning contributed nothing.
                if plan_status == "completed" and pages and not diagnostic_plan:
                    plan_status = "partial"
                form_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "form_validation"
                ))
                vision_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "visual_review"
                ))
                navigation_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "navigation_flow"
                ))
                link_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "link_health"
                ))
                accessibility_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "accessibility_review"
                ))
                security_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "security_review"
                ))
                performance_priority_page_ids = list(dict.fromkeys(
                    item["page_id"] for item in diagnostic_plan if item["test_type"] == "performance_review"
                ))
                if planner_error:
                    plan_detail = f"Diagnostic planning failed ({planner_error}); baseline checks continue without AI prioritization."
                elif plan_status == "skipped":
                    plan_detail = "AI planning was unavailable, disabled, or had no observed pages; baseline checks continue without AI prioritization."
                elif plan_status == "failed":
                    plan_detail = "The AI planner did not return a valid applicable plan; baseline checks continue without AI prioritization."
                elif plan_status == "partial":
                    plan_detail = f"AI planning was partial ({len(diagnostic_plan)} recommendations accepted); baseline checks continue and recommendations only prioritize supported adapters."
                else:
                    plan_detail = f"Local AI proposed {len(diagnostic_plan)} safe, page-aware recommendations; supported checks remain in control of execution."
                progress.step("ai_plan", "failed" if planner_error else plan_status, plan_detail,
                    {"recommendations": len(diagnostic_plan), "by_type": {
                        kind: sum(item["test_type"] == kind for item in diagnostic_plan)
                        for kind in sorted({item["test_type"] for item in diagnostic_plan})
                    }})
                plan_task = plan_tasks[-1] if plan_tasks else {}
                progress.emit("diagnostic_plan", status="failed" if planner_error else plan_status,
                    detail=plan_detail, model=plan_task.get("model", self.settings.text_model),
                    inference_confirmed=plan_task.get("status") in {"completed", "partial"},
                    recommendations=diagnostic_plan, accepted_count=len(diagnostic_plan),
                    page_count=len(pages), selected_pillars=[pillar.value for pillar in selected])

                if Pillar.FUNCTIONALITY in selected and browser:
                    async def forms_adapter():
                        nonlocal test_cases
                        result, test_cases = await test_forms(browser, ai, pages, directory, progress.log, form_priority_page_ids, on_frame=on_frame_event)
                        if any("fallback" in c["source"].lower() for c in test_cases):
                            result.status = "partial"
                            result.reason += " Some cases used deterministic fallback, not AI generation."
                        return result
                    await run_scan("ai_tests", forms_adapter)
                    # Test-case sanitization may downgrade an AI task to partial;
                    # publish that post-validation state before later scanners run.
                    progress.publish_ai_tasks(ai.tasks)
                else:
                    progress.step("ai_tests", "skipped", "Pillar not selected or browser unavailable.")
                async def links_adapter():
                    result = await check_links(guard, pages, link_priority_page_ids)
                    if browser and flows:
                        replay = await test_navigation_flows(browser, flows, pages, navigation_priority_page_ids, on_frame=on_frame_event)
                        result.findings.extend(replay.findings)
                        result.metrics.update(replay.metrics)
                        result.reason += " " + replay.reason
                        if result.status in {"skipped", "blocked"} and replay.status in {"completed", "partial"}:
                            result.status = replay.status
                        elif result.status == "completed" and replay.status in {"partial", "failed"}:
                            result.status = "partial"
                        elif result.status == "skipped" and replay.status == "failed":
                            result.status = "failed"
                    return result
                await run_scan("links", links_adapter)
                if pages:
                    on_frame_event("", "[SECURITY AUDIT] Inspecting HTTP security headers & CSRF cookie flags", pages[0].url)
                await run_scan("custom_security", lambda: custom_security(self.policy, guard, pages, security_priority_page_ids), allowed=target.authorized)
                if pages:
                    on_frame_event("", "[OWASP ZAP ACTIVE] Scanning passive vulnerability baseline & exposure", pages[0].url)
                await run_scan("zap", lambda: zap_scan(self.policy, guard, pages, self.settings), allowed=target.authorized)
                if pages:
                    on_frame_event("", "[NUCLEI SCANNER] Testing curated CVE misconfigurations & endpoints", pages[0].url)
                await run_scan("nuclei", lambda: nuclei_scan(self.policy, guard, self.settings, directory), allowed=target.authorized)
                prioritized_performance_urls = [p.url for page_id in performance_priority_page_ids for p in pages if p.id == page_id]
                remaining_performance_urls = [p.url for p in pages if p.id not in performance_priority_page_ids]
                performance_urls = list(dict.fromkeys(prioritized_performance_urls + remaining_performance_urls))
                if performance_urls:
                    on_frame_event("", "[PERFORMANCE] Measuring TTFB, DNS lookup & socket latency", performance_urls[0])
                await run_scan("http_timing", lambda: response_timing(guard, performance_urls))
                # Select a healthy HTTP 200 page for Lighthouse if the first page returned an error status (like a 404)
                healthy_pages = [p.url for p in pages if p.status_code == 200 and origin(p.url) == guard.target.origin]
                if performance_urls and any(p.url == performance_urls[0] and p.status_code == 200 for p in pages):
                    lighthouse_url = performance_urls[0]
                elif healthy_pages:
                    lighthouse_url = healthy_pages[0]
                else:
                    lighthouse_url = performance_urls[0] if performance_urls else guard.target.url
                on_frame_event("", "[LIGHTHOUSE LAB] Auditing Core Web Vitals (FCP, LCP, TBT, CLS)", lighthouse_url)
                await run_scan("lighthouse", lambda: lighthouse_scan(self.settings, guard, directory, chromium, lighthouse_url))
                if target.authorized and pages:
                    on_frame_event("", "[LOCUST LOAD] Running bounded concurrency & latency stability test", pages[0].url)
                await run_scan("load", lambda: load_scan(self.policy, guard, self.settings, directory, pages), allowed=target.authorized)
                if browser:
                    await run_scan("axe", lambda: axe_scan(browser, pages, directory, accessibility_priority_page_ids, on_frame=on_frame_event))
                else:
                    progress.step("axe", "skipped", "Playwright browser unavailable.")
                await run_scan("pa11y", lambda: pa11y_scan(self.settings, guard, pages, directory, chromium, accessibility_priority_page_ids))
                if Pillar.ACCESSIBILITY in selected:
                    progress.step("vision", "running")
                    vision_findings = await vision(ai, pages, directory, vision_priority_page_ids)
                    findings.extend(vision_findings)
                    if vision_findings:
                        progress.emit("live_findings", step_id="vision", pillar="accessibility",
                                      findings=[serialize_finding(f) for f in vision_findings[:12]],
                                      total_count=len(findings))
                    progress.publish_ai_tasks(ai.tasks)
                    tasks = [t for t in ai.tasks if t["name"].startswith("Visual review")]
                    if tasks and all(t["status"] == "completed" for t in tasks):
                        status = "completed"
                    elif any(t["status"] == "completed" for t in tasks):
                        status = "partial"
                    elif any(t["status"] == "failed" for t in tasks):
                        status = "failed"
                    else:
                        status = "skipped"
                    vision_detail = f"Local vision review completed {sum(t['status']=='completed' for t in tasks)}/{len(tasks)} screenshot tasks; visual findings stay Possible."
                    progress.step("vision", status, vision_detail)
                    await update_recommendations_for_step("vision", "adapter_finished_pending_page_confirmation" if status in {"completed", "partial"} else status, vision_detail)
                else:
                    progress.step("vision", "skipped", "Pillar not selected.")
                progress.step("verify", "running")
                verification = await verify_findings(findings, guard, browser)
                findings = deduplicate(findings)
                metrics["verification"] = verification
                progress.step("verify", "completed", "Deterministic re-tests applied; matching root causes merged with provenance retained.", verification)
                findings = deduplicate(findings)
                progress.emit("verification_summary", phase="independent_retest", verified=sum(f.status == "Verified" for f in findings),
                    possible=sum(f.status == "Possible" for f in findings), unresolved=sum(f.status == "Possible" for f in findings),
                    total=len(findings), details=verification)
            finally:
                if browser:
                    await browser.__aexit__(None, None, None)
            if Pillar.SECURITY in selected and target.authorized:
                progress.step("triage", "running")
                security_findings_before_triage = any(f.pillar == Pillar.SECURITY for f in findings)
                suppressed = await triage(ai, findings)
                progress.publish_ai_tasks(ai.tasks)
                findings = [f for f in findings if f not in suppressed]
                tasks = [t for t in ai.tasks if t["name"].startswith("Security triage")]
                successful = sum(t["status"] == "completed" for t in tasks)
                # No findings means triage was not applicable, not that security
                # testing failed. Do not mistake findings suppressed after a real
                # triage pass for a run that never required triage.
                if not security_findings_before_triage:
                    status = "completed"
                    detail = "No security findings to triage; no AI triage inference was required."
                else:
                    status = ai_task_status(tasks)
                    detail = (f"Local triage fully completed {successful}/{len(tasks)} batches; "
                              f"{sum(t['status']=='partial' for t in tasks)} batches applied partial known-ID output. "
                              "Verified facts cannot be suppressed by AI alone." if tasks else
                              "Security findings existed but no triage task was recorded; AI coverage is incomplete.")
                    if not tasks:
                        status = "skipped"
                progress.step("triage", status, detail)
            else:
                progress.step("triage", "blocked" if Pillar.SECURITY in selected else "skipped", "Security pillar not selected or not authorized.")
            metrics["network_safety"] = guard.observations()
        findings = rank(findings)
        progress.step("synthesis", "running")
        scores, overall, coverage, partial = score_report(selected, findings, progress.steps, metrics)
        synthesis = await synthesize(ai, findings, metrics, {p.value: s.model_dump() for p, s in scores.items()})
        progress.publish_ai_tasks(ai.tasks)
        priorities = [f.suggested_fix for f in findings[:3]]
        if synthesis:
            lookup = {f.id: f for f in findings}
            for item in synthesis.improvements:
                if item.id in lookup:
                    finding = lookup[item.id]
                    finding.explanation = redact(item.explanation, 2000)
                    finding.suggested_fix = redact(item.suggested_fix, 2000)
                    finding.ai_assisted = True
            findings = rank(apply_ai_merges(findings, synthesis.duplicate_groups))
            summary = redact(synthesis.summary, 2000)
            priorities = [redact(x, 700) for x in synthesis.priorities[:5]]
            progress.step("synthesis", "completed", "Local AI synthesis applied; evidence, verification and scores remain deterministic.")
        else:
            summary = f"Tested {len(pages)} pages and found {len(findings)} deduplicated issues ({sum(f.status=='Verified' for f in findings)} verified). Scores reflect observed checks only. This run has incomplete tool/AI coverage; consult the coverage log before drawing conclusions."
            progress.step("synthesis", "skipped", "Local synthesis unavailable; honest measured-results summary used.")
        scores, overall, coverage, partial = score_report(selected, findings, progress.steps, metrics)
        summary = f"Mapped {len(pages)} pages; {len(findings)} deduplicated findings ({sum(f.status == 'Verified' for f in findings)} verified by re-test). " + summary
        if any(t["status"] != "completed" for t in ai.tasks):
            limitations.append("Some local AI tasks were unavailable or failed; no external/closed-model fallback was used.")
            partial = True
        for step in progress.steps:
            if step.status in {"skipped", "failed", "partial", "blocked"} and (step.pillar is None or step.pillar in selected):
                limitations.append(f"{step.title}: {step.status}. {step.detail}")
        step_statuses = {step.id: step.status for step in progress.steps}
        vision_tasks_by_page = {}
        for task in ai.tasks:
            name = task.get("name", "")
            if name.startswith("Visual review: "):
                page_id = name.split(": ", 1)[1].split(" / ", 1)[0]
                vision_tasks_by_page.setdefault(page_id, []).append(task)
        recommendation_detail_overrides = {}
        for recommendation in diagnostic_plan:
            page_id = recommendation["page_id"]
            test_type = recommendation["test_type"]
            step_id = recommendation.get("execution_step", "")
            step_status = step_statuses.get(step_id, "skipped")
            if test_type == "form_validation":
                page_cases = [case for case in test_cases if case.get("url") == recommendation["page_url"]]
                if any(case.get("status") == "executed" for case in page_cases):
                    execution_status = "executed"
                elif page_cases:
                    execution_status = "partially_executed" if any(case.get("status") == "failed" for case in page_cases) else "not_executed"
                else:
                    execution_status = "skipped" if step_status in {"skipped", "blocked"} else "not_executed_budget_or_no_usable_case"
            elif test_type == "security_review":
                page_results = metrics.get("custom_security", {}).get("page_results", [])
                page_result = next((entry for entry in page_results if entry.get("url") == recommendation["page_url"]), None)
                if page_result and page_result.get("status") == "completed":
                    execution_status = "executed"
                elif page_result:
                    execution_status = "failed"
                else:
                    execution_status = "skipped" if step_status in {"skipped", "blocked"} else "not_executed_or_outside_page_budget"
            elif test_type == "performance_review":
                lighthouse_metrics = metrics.get("lighthouse", {})
                if step_status == "completed" and lighthouse_metrics.get("url") == recommendation["page_url"]:
                    execution_status = "executed"
                else:
                    execution_status = "skipped" if step_status in {"skipped", "blocked"} else "not_confirmed_or_different_priority_page"
            elif test_type == "visual_review":
                task_statuses = [task.get("status") for task in vision_tasks_by_page.get(page_id, [])]
                if any(status == "completed" for status in task_statuses):
                    execution_status = "executed"
                elif any(status == "failed" for status in task_statuses):
                    execution_status = "failed"
                elif task_statuses:
                    execution_status = "skipped"
                else:
                    execution_status = "skipped" if step_status in {"skipped", "blocked"} else "not_executed"
            elif test_type == "navigation_flow":
                page_observations = [observation for flow in flows if page_id in flow.get("page_ids", [])
                                     for observation in flow.get("observations", []) if observation.get("page_id") == page_id]
                execution_status = "observed" if page_observations else ("skipped" if step_status in {"skipped", "blocked"} else "not_covered_by_replayed_flow")
            elif test_type == "accessibility_review":
                axe_result = next((entry for entry in metrics.get("axe", {}).get("page_results", [])
                                   if entry.get("url") == recommendation["page_url"]), None)
                pa11y_result = next((entry for entry in metrics.get("pa11y", {}).get("page_results", [])
                                     if entry.get("url") == recommendation["page_url"]), None)
                if axe_result and axe_result.get("status") == "completed":
                    execution_status = "executed"
                    recommendation_detail_overrides[(page_id, test_type)] = "Accessibility rules actually executed on this page with axe-core."
                elif pa11y_result and pa11y_result.get("status") == "completed":
                    execution_status = "executed"
                    recommendation_detail_overrides[(page_id, test_type)] = "Accessibility rules actually executed on this page with Pa11y; axe-core may have been unavailable."
                elif ((axe_result and axe_result.get("status") == "failed")
                      or (pa11y_result and pa11y_result.get("status") == "failed")):
                    execution_status = "failed"
                    recommendation_detail_overrides[(page_id, test_type)] = "At least one accessibility adapter failed on this page, and no successful page-level audit was found."
                elif all(progress_step.status in {"skipped", "blocked"} for progress_step in progress.steps if progress_step.id in {"axe", "pa11y"}):
                    execution_status = "skipped"
                    recommendation_detail_overrides[(page_id, test_type)] = "Accessibility adapters were skipped or blocked; no rule check is claimed."
                else:
                    execution_status = "not_executed_or_outside_page_budget"
                    recommendation_detail_overrides[(page_id, test_type)] = "This specific page was not confirmed in the accessibility adapter results."
            elif test_type == "link_health":
                link_metrics = metrics.get("links", {})
                execution_status = "executed_sitewide" if link_metrics.get("links_checked", 0) > 0 else ("partial" if step_status == "partial" else "not_confirmed")
            else:
                execution_status = "not_confirmed"
            recommendation["execution_status"] = execution_status
            recommendation["execution_detail"] = recommendation_detail_overrides.get(
                (page_id, test_type), next((step.detail for step in progress.steps if step.id == step_id), ""))
            progress.emit("recommendation_update", recommendation=recommendation)
        versions = {"Playwright": "1.52.0", "axe-core": "4.10.3", "Pa11y": "8.0.0", "Locust": "2.37.14", "Nuclei": "3.4.10 (image default)",
                    "Lighthouse": str(metrics.get("lighthouse", {}).get("version", "unavailable")),
                    "ZAP": str(metrics.get("zap", {}).get("version", "unavailable")),
                    "Ollama text model": self.settings.text_model, "Ollama vision model": self.settings.vision_model}
        report = Report(id=jid, url=target.url, created_at=job["created_at"], finished_at=now(),
            duration_seconds=round(time.perf_counter()-start, 2), selected_pillars=selected, authorized=target.authorized,
            overall_score=overall, coverage=coverage, partial=partial, summary=summary, priorities=priorities,
            scores=scores, findings=findings, suppressed_findings=suppressed, steps=progress.steps,
            pages=pages, flows=flows, diagnostic_plan=diagnostic_plan, test_cases=test_cases, ai_tasks=ai.tasks, metrics=metrics,
            limitations=limitations, tool_versions=versions)
        progress.emit("verification_summary", phase="final_report", verified=sum(f.status == "Verified" for f in report.findings),
            possible=sum(f.status == "Possible" for f in report.findings), unresolved=sum(f.status == "Possible" for f in report.findings),
            total=len(report.findings), suppressed=len(report.suppressed_findings))
        progress.emit("report_summary", overall_score=report.overall_score, coverage=report.coverage, partial=report.partial,
            findings=len(report.findings), verified=sum(f.status == "Verified" for f in report.findings),
            selected_pillars=[pillar.value for pillar in report.selected_pillars],
            pillar_scores={pillar.value: score.model_dump(mode="json") for pillar, score in report.scores.items()})
        progress.emit("ai_run_summary", tasks=ai.tasks,
            completed=sum(task.get("status") == "completed" for task in ai.tasks),
            running=sum(task.get("status") == "running" for task in ai.tasks),
            failed=sum(task.get("status") == "failed" for task in ai.tasks),
            skipped=sum(task.get("status") == "skipped" for task in ai.tasks))
        (directory / "report.json").write_text(report.model_dump_json(indent=2))
        return report


class JobWorker:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self.task = None
        self.active: dict[str, asyncio.Task] = {}
        self.shutting_down = False
        self.wake = asyncio.Event()

    async def start(self):
        self.store.recover()
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self.shutting_down = True
        if self.task:
            self.task.cancel()
        for task in self.active.values():
            task.cancel()
        await asyncio.gather(*self.active.values(), return_exceptions=True)
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)

    async def cancel(self, jid: str):
        job = self.store.get_job(jid)
        if not job or job["status"] not in {"queued", "running"}:
            return
        self.store.update(jid, status="cancelled", finished_at=now())
        self.store.event(jid, {"type": "cancelled", "message": "Test cancelled. Scanner processes are being stopped."})
        if jid in self.active:
            self.active[jid].cancel()

    async def _watch_persisted_cancellation(self, jid: str, task: asyncio.Task) -> None:
        """Observe API-side cancellation when API and worker run in different processes."""
        while not task.done():
            await asyncio.sleep(0.4)
            current = self.store.get_job(jid)
            if current is None or current["status"] == "cancelled":
                if not task.done():
                    task.cancel()
                return

    async def _loop(self):
        while True:
            job = self.store.claim()
            if not job:
                self.wake.clear()
                try:
                    # In external-worker mode the API cannot wake this process's
                    # asyncio.Event, so queue polling is intentionally bounded to 1s.
                    await asyncio.wait_for(self.wake.wait(), 1)
                except asyncio.TimeoutError:
                    pass
                continue
            task = asyncio.create_task(Pipeline(self.settings, self.store).run(job))
            self.active[job["id"]] = task
            cancellation_watcher = asyncio.create_task(self._watch_persisted_cancellation(job["id"], task))
            try:
                report = await asyncio.wait_for(task, self.settings.job_timeout)
                current = self.store.get_job(job["id"])
                if current and current["status"] != "cancelled":
                    self.store.update(job["id"], status="completed", finished_at=now(), report=report.model_dump(mode="json"))
                    self.store.event(job["id"], {"type": "completed", "report_id": report.id, "message": "Evidence-based report ready."})
            except asyncio.CancelledError:
                if self.shutting_down:
                    raise  # Leave interrupted job recoverable on the next startup.
                # Otherwise the job was cancelled through the shared durable store.
            except Exception as exc:
                logger.exception("Job failed")
                current = self.store.get_job(job["id"])
                if current and current["status"] == "cancelled":
                    continue
                error = "Scan exceeded the maximum job duration; all processes stopped." if isinstance(exc, TimeoutError) else f"Scan stopped safely: {type(exc).__name__}: {redact(str(exc),500)}"
                self.store.update(job["id"], status="failed", finished_at=now(), error=error)
                self.store.event(job["id"], {"type": "failed", "message": error})
            finally:
                cancellation_watcher.cancel()
                await asyncio.gather(cancellation_watcher, return_exceptions=True)
                self.active.pop(job["id"], None)
