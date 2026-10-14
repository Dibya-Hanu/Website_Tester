"""Nuclei runs only the reviewed read-only templates committed to this project."""
import json
import shutil
from pathlib import Path

from app.core.models import Evidence, Finding, Location, Pillar, ScanResult, Severity, VerificationSpec
from app.core.policy import PolicyError, TargetPolicy, origin
from app.core.process import run_command
from app.core.redact import safe_url

RULES = {
    "uwt-missing-csp": ("header-content-security-policy", "content-security-policy", "header-missing", Severity.MEDIUM),
    "uwt-exposed-git-head": ("exposed-git", None, "file-signature", Severity.HIGH),
    "uwt-exposed-env": ("exposed-env", None, "file-signature", Severity.HIGH),
}


async def nuclei_scan(policy: TargetPolicy, guard, settings, directory: Path) -> ScanResult:
    try:
        policy.require_authorized(guard.target.url, "Nuclei scan")
    except PolicyError as exc:
        return ScanResult(status="blocked", reason=str(exc))
    executable = shutil.which(settings.nuclei_bin)
    if not executable:
        return ScanResult(status="skipped", reason="Nuclei executable is unavailable.")
    output_file = directory / "nuclei.jsonl"
    # A per-job output file must never reuse stale scanner results.
    output_file.unlink(missing_ok=True)
    try:
        command = await run_command([
            executable, "-u", guard.target.url, "-t", str(settings.tools_dir / "nuclei"),
            "-proxy", guard.local_url, "-jsonl", "-o", str(output_file), "-silent",
            "-omit-raw", "-no-interactsh", "-disable-redirects", "-disable-update-check",
            "-no-stdin", "-rate-limit", "2", "-concurrency", "2", "-timeout", "8", "-retries", "0",
        ], timeout=90, env={"SSL_CERT_FILE": str(guard.ca_file), "HTTP_PROXY": guard.local_url, "HTTPS_PROXY": guard.local_url, "NO_PROXY": ""})
    except (OSError, TimeoutError):
        return ScanResult(status="failed", reason="Nuclei command did not finish within its bound.")
    if command.returncode:
        return ScanResult(status="failed", reason="Nuclei failed; no pass is inferred.", metrics={"exit_code": command.returncode})
    if not output_file.is_file():
        return ScanResult(status="failed", reason="Nuclei exited successfully but did not produce a result file; no pass is inferred.",
                          metrics={"exit_code": 0, "output_file_present": False, "templates": len(RULES)})
    try:
        lines = output_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ScanResult(status="failed", reason="Nuclei result file could not be read; no pass is inferred.",
                          metrics={"exit_code": 0, "output_file_present": True, "templates": len(RULES)})
    findings = []
    malformed_rows = ignored_rows = parsed_rows = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            malformed_rows += 1
            continue
        if not isinstance(row, dict):
            malformed_rows += 1
            continue
        template_id = row.get("template-id")
        rule = RULES.get(template_id) if isinstance(template_id, str) else None
        if not rule:
            ignored_rows += 1
            continue
        matched_at = row.get("matched-at", guard.target.url)
        try:
            same_origin = isinstance(matched_at, str) and origin(matched_at) == guard.target.origin
        except (ValueError, TypeError):
            same_origin = False
        if not same_origin:
            ignored_rows += 1
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        category, header, kind, severity = rule
        url = matched_at
        data = {"url": url, "header": header}
        if kind == "file-signature":
            data["path"] = "/.git/HEAD" if category == "exposed-git" else "/.env"
        title = info.get("name")
        if not isinstance(title, str) or not title.strip():
            title = template_id
        findings.append(Finding(title=title[:220],
            pillar=Pillar.SECURITY, severity=severity, category=category,
            location=Location(url=safe_url(url), header=header),
            evidence=[Evidence(detail=f"Nuclei read-only template: {template_id}\nMatcher confirmed at {safe_url(url)}. Raw response intentionally omitted.")],
            explanation="A reviewed read-only Nuclei template matched this response; it will be independently re-tested.",
            suggested_fix="Remove exposed deployment files or configure the missing response defense identified by this template.",
            sources=["Nuclei (curated read-only templates)"], check=VerificationSpec(kind=kind, data=data)))
        parsed_rows += 1
    metrics = {"templates": len(RULES), "matches": len(findings), "output_lines": len(lines),
               "parsed_rows": parsed_rows, "ignored_rows": ignored_rows, "malformed_rows": malformed_rows,
               "output_file_present": True}
    status = "partial" if malformed_rows or ignored_rows else "completed"
    return ScanResult(findings=findings, status=status,
                      reason="Only 3 committed GET-only templates; no fuzzing, OAST or template downloads." +
                      (f" {malformed_rows} malformed and {ignored_rows} unsupported/out-of-origin result rows were not interpreted." if malformed_rows or ignored_rows else ""),
                      metrics=metrics)
