#!/usr/bin/env python3
"""Capture REAL screenshots of the running dashboard (after run_demo.py has produced data/demo-run).
  python scripts/capture_screenshots.py   -> screenshots/actual/*.png
"""
import os
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots" / "actual"
PORT = 8091
sys.path.insert(0, str(Path(__file__).parent))
from _proc import popen_background, stop_pid  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
env = {**os.environ, "UWT_DATA_DIR": str(ROOT / "data" / "demo-run"), "UWT_AI_ENABLED": "false", "UWT_ALLOWLIST": "http://127.0.0.1:8765"}
proc = popen_background([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT / "backend", env=env)
try:
    for _ in range(60):
        try:
            jobs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/jobs", timeout=2))["jobs"]
            break
        except OSError:
            time.sleep(0.5)
    jid = next(j["id"] for j in jobs if j["status"] == "completed")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1366, "height": 900})
        for name, path in [("home", "/"), ("report", f"/reports/{jid}"), ("history", "/history")]:
            pg.goto(f"http://127.0.0.1:{PORT}{path}")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(OUT / f"actual-{name}.png"), full_page=(name == "report"))
            print("captured", name)
        pg.goto("http://127.0.0.1:8765/") if False else None
        b.close()
finally:
    stop_pid(proc.pid)
