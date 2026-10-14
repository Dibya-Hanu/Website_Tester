#!/usr/bin/env python3
"""Report which components are installed, honestly. Exit code 0 if the core is usable."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def has(mod):
    return importlib.util.find_spec(mod) is not None


def node_pkg(name):
    return (ROOT / "tools" / "node_modules" / name).is_dir()


def chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


checks = [
    ("Python 3.12-3.13", (3, 12) <= sys.version_info[:2] <= (3, 13), True),
    ("fastapi/uvicorn/pydantic/httpx/jinja2/reportlab", all(has(m) for m in ("fastapi", "uvicorn", "pydantic", "httpx", "jinja2", "reportlab")), True),
    ("playwright package", has("playwright"), True),
    ("Playwright Chromium browser", chromium(), True),
    ("mitmproxy (safety guard)", has("mitmproxy"), True),
    ("locust (capped load test)", has("locust"), False),
    ("Node.js", bool(shutil.which("node")), False),
    ("axe-core (tools/node_modules)", node_pkg("axe-core"), False),
    ("Pa11y", node_pkg("pa11y"), False),
    ("Lighthouse", node_pkg("lighthouse"), False),
    ("Frontend build (frontend/dist)", (ROOT / "frontend" / "dist" / "index.html").exists(), False),
    ("Nuclei binary", bool(shutil.which("nuclei") or (ROOT / "bin" / "nuclei").exists() or (ROOT / "bin" / "nuclei.exe").exists()), False),
    ("Ollama on PATH (local AI, optional)", bool(shutil.which("ollama")), False),
    ("OWASP ZAP (optional; needs Java/Docker)", bool(shutil.which("zap.sh") or shutil.which("zap.bat")), False),
]
core_ok = True
for name, ok, required in checks:
    print(f"[{'OK' if ok else ('MISSING' if required else 'optional - missing')}] {name}")
    core_ok &= ok or not required
print("\nCore usable." if core_ok else "\nCore components missing: run python scripts/setup_dev.py")
sys.exit(0 if core_ok else 1)
