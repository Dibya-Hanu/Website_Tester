#!/usr/bin/env python3
"""Cross-platform setup (Linux, macOS, Windows). No system-wide installs, no admin rights needed.

  python scripts/setup_dev.py            # venv + Python deps + Chromium + scanner tools + frontend build
  python scripts/setup_dev.py --skip-node  # Python-only (crawler/functional/security/performance-timing; no Lighthouse/axe/Pa11y)

Needs: Python 3.12-3.13. Node.js 18+ is needed for Lighthouse/axe-core/Pa11y and the frontend build.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-node", action="store_true")
    ap.add_argument("--skip-browser", action="store_true")
    args = ap.parse_args()
    if not (3, 12) <= sys.version_info[:2] <= (3, 13):
        print(f"Python 3.12-3.13 required (found {sys.version.split()[0]}).", file=sys.stderr)
        return 1
    if not PY.exists():
        run([sys.executable, "-m", "venv", VENV])
    run([PY, "-m", "pip", "install", "--upgrade", "pip"])
    run([PY, "-m", "pip", "install", "-r", ROOT / "backend" / "requirements-dev.txt"])
    if not args.skip_browser:
        run([PY, "-m", "playwright", "install", "chromium"])
    npm = shutil.which("npm")
    if args.skip_node or not npm:
        print("\nNode/npm skipped: Lighthouse, axe-core, Pa11y and the web dashboard build will be unavailable"
              + (" (npm not found)." if not npm else "."))
    else:
        env = {**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"}  # we reuse Playwright's Chromium
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "tools", env=env)
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend", env=env)
        run([npm, "run", "build"], cwd=ROOT / "frontend", env=env)
    print("\nSetup complete. Next:  python scripts/run_demo.py     (activate venv first for other commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
