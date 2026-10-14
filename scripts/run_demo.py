#!/usr/bin/env python3
"""One command, whole demo (Linux, macOS, Windows): practice app + backend + URL-only scan + all exports.

  python scripts/run_demo.py                  # scan the bundled practice app, write reports/sample/
  python scripts/run_demo.py --keep-running   # leave the dashboard up at http://127.0.0.1:8080

Only the practice app on loopback is allowlisted. Nothing here weakens the tester's safety checks.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _proc import popen_background, stop_pid  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def wait_for(url: str, seconds: int = 40) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--practice-port", type=int, default=8765)
    ap.add_argument("--app-port", type=int, default=8080)
    ap.add_argument("--output", type=Path, default=ROOT / "reports" / "sample")
    ap.add_argument("--keep-running", action="store_true")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--timeout", type=int, default=1500)
    args = ap.parse_args()

    target = f"http://127.0.0.1:{args.practice_port}/"
    run_dir = ROOT / "data" / "demo-run"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    ollama_up = wait_for(args.ollama_url + "/api/tags", 2)
    nuclei = shutil.which("nuclei") or str(ROOT / "bin" / ("nuclei.exe" if os.name == "nt" else "nuclei"))
    env = {**os.environ, "UWT_ALLOWLIST": target.rstrip("/"), "UWT_DATA_DIR": str(run_dir), "PYTHONUNBUFFERED": "1",
           "UWT_OLLAMA_URL": args.ollama_url, "UWT_AI_ENABLED": "true" if ollama_up else "false",
           "UWT_NUCLEI_BIN": nuclei, "UWT_PROXY_ADVERTISED_HOST": "127.0.0.1"}
    env.setdefault("UWT_ZAP_URL", "http://127.0.0.1:1")  # ZAP is optional; unreachable => honestly reported as skipped
    print(f"Local AI (Ollama) reachable: {ollama_up}  -> AI features {'ON' if ollama_up else 'OFF (deterministic fallbacks, reported as such)'}")
    procs = []
    try:
        procs.append(popen_background([sys.executable, str(ROOT / "practice_app" / "practice_shop.py"), "--port", str(args.practice_port)],
                                      log_path=run_dir / "practice.log"))
        if not wait_for(target + "health"):
            print("Practice app did not start.", file=sys.stderr)
            return 1
        procs.append(popen_background([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.app_port)],
                                      cwd=ROOT / "backend", env=env, log_path=run_dir / "backend.log"))
        base = f"http://127.0.0.1:{args.app_port}"
        if not wait_for(base + "/api/health"):
            print("Backend did not start; see data/demo-run/backend.log", file=sys.stderr)
            return 1
        print(f"Dashboard: {base}   Practice app: {target}")
        with httpx.Client(base_url=base, timeout=60) as client:
            job = client.post("/api/jobs", json={"url": target})
            job.raise_for_status()
            jid = job.json()["id"]
            print("Submitted URL-only job", jid)
            last, deadline = None, time.time() + args.timeout
            while time.time() < deadline:
                data = client.get(f"/api/jobs/{jid}").json()
                steps = data.get("progress", {}).get("steps", [])
                running = next((s["title"] for s in steps if s["status"] == "running"), "")
                line = (data["status"], data.get("progress", {}).get("percent"), running)
                if line != last:
                    print(f"  {data['status']:9} {line[1]}%  {running}")
                    last = line
                if data["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            else:
                print("Timed out waiting for the scan.", file=sys.stderr)
                return 1
            if data["status"] != "completed":
                print(f"Scan {data['status']}: {data.get('error')}", file=sys.stderr)
                return 1
            args.output.mkdir(parents=True, exist_ok=True)
            report = client.get(f"/api/reports/{jid}").json()
            (args.output / "practice-shop-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            for fmt in ("html", "pdf", "csv"):
                res = client.get(f"/api/reports/{jid}/export/{fmt}")
                res.raise_for_status()
                (args.output / f"practice-shop-report.{fmt}").write_bytes(res.content)
            evidence = args.output / "evidence"
            evidence.mkdir(exist_ok=True)
            names = {i["file"] for f in report["findings"] for i in f["evidence"] if i.get("file")}
            names |= {n for p in report["pages"] for n in p["screenshots"].values()}
            for name in names:
                res = client.get(f"/api/jobs/{jid}/evidence/{name}")
                if res.status_code == 200:
                    (evidence / name).write_bytes(res.content)
            print(f"\nOverall {report['overall_score']}/100, coverage {report['coverage']}%, {len(report['findings'])} findings, partial={report['partial']}")
            for key, s in report["scores"].items():
                print(f"  {key:14} score={s['score']} status={s['status']} coverage={s['coverage']}% issues={s['issues']}")
            print(f"Reports written to {args.output}")
        if args.keep_running:
            print(f"\nStill running. Open {base}  (Ctrl+C to stop)")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        for p in procs:
            stop_pid(p.pid)


if __name__ == "__main__":
    raise SystemExit(main())
