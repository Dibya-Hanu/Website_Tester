#!/usr/bin/env python3
"""Generate a REAL sample via the same public URL-only API, then download exports.

No synthetic findings. Requires a running app and an approved reachable lab origin.
The app automatically handles every tool/model task after URL submission.
"""
import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--app", default="http://127.0.0.1:8080")
parser.add_argument("--url", default="http://juice-shop:3000/")
parser.add_argument("--job", help="Export an already completed real scan instead of submitting again.")
parser.add_argument("--output", type=Path, default=Path("samples"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with httpx.Client(base_url=args.app, timeout=120) as client:
    if args.job:
        jid = args.job
    else:
        response = client.post("/api/jobs", json={"url": args.url})
        response.raise_for_status()
        jid = response.json()["id"]
        print("Submitted URL-only job", jid, flush=True)
    deadline = time.monotonic() + 3600
    previous = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{jid}")
        response.raise_for_status()
        job = response.json()
        progress = job.get("progress", {}).get("percent", 0)
        if (job["status"], progress) != previous:
            print(job["status"], f"{progress}%", flush=True)
            previous = (job["status"], progress)
        if job["status"] == "completed":
            break
        if job["status"] in {"failed", "cancelled"}:
            raise SystemExit(f"No fabricated report produced: {job.get('error') or job['status']}")
        time.sleep(2)
    else:
        raise SystemExit("Waiting for sample exceeded 60 minutes; check app progress.")
    response = client.get(f"/api/reports/{jid}")
    response.raise_for_status()
    report = response.json()
    report["sample"] = True
    (args.output/"juice-shop-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for format in ["html", "pdf"]:
        result = client.get(f"/api/reports/{jid}/export/{format}")
        result.raise_for_status()
        (args.output/f"juice-shop-report.{format}").write_bytes(result.content)
    evidence = args.output/"evidence"
    evidence.mkdir(exist_ok=True)
    # Keep screenshots in JSON portable and include form-case evidence too.
    filenames = {item["file"] for f in report["findings"] for item in f["evidence"] if item.get("file")}
    filenames.update(filename for p in report["pages"] for filename in p["screenshots"].values())
    filenames.update(t["screenshot"] for t in report["test_cases"] if t.get("screenshot"))
    for filename in sorted(filenames):
        result = client.get(f"/api/jobs/{jid}/evidence/{filename}")
        result.raise_for_status()
        (evidence/filename).write_bytes(result.content)
    manifest = {
        "kind":"actual measured run, not a fixture of invented findings", "report_id":jid,
        "target":report["url"], "finished_at":report["finished_at"], "partial":report["partial"],
        "overall_score":report["overall_score"], "coverage_percent":report["coverage"],
        "findings":len(report["findings"]), "verified":sum(f["status"] == "Verified" for f in report["findings"]),
        "steps":{s["id"]:{"status":s["status"],"detail":s["detail"]} for s in report["steps"]},
        "tool_versions":report["tool_versions"],
        "ai_tasks":report["ai_tasks"],
        "regenerate":"docker compose --profile labs up --build -d && python scripts/generate_sample.py --url http://juice-shop:3000/",
    }
    (args.output/"execution-manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Actual sample exported to {args.output}", flush=True)
