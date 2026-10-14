#!/usr/bin/env python3
"""Start, stop or check OWASP ZAP daemon in the background (portable, cross-platform).

  python scripts/zap_ctl.py start [--port 8090] [--api-key local-zap-change-me]
  python scripts/zap_ctl.py status
  python scripts/zap_ctl.py stop
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path
import urllib.request
import json

sys.path.insert(0, str(Path(__file__).parent))
from _proc import pid_alive, popen_background, stop_pid  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PIDFILE = ROOT / "data" / "zap.pid"
ZAP_DIR = ROOT / "tools" / "zap"
ZAP_HOME = ZAP_DIR / "zap_home"


def find_java() -> Path | None:
    exe_name = "java.exe" if sys.platform == "win32" else "java"
    # 1. Bundled portable JRE
    for candidate in ZAP_DIR.glob(f"jdk*jre/bin/{exe_name}"):
        if candidate.is_file():
            return candidate
    for candidate in ZAP_DIR.glob(f"jre*/bin/{exe_name}"):
        if candidate.is_file():
            return candidate
    # 2. System java
    which_java = shutil.which(exe_name)
    if which_java:
        return Path(which_java)
    return None


def find_zap_jar() -> Path | None:
    for candidate in ZAP_DIR.glob("ZAP*/zap-*.jar"):
        if candidate.is_file():
            return candidate
    return None


def healthy(port: int, api_key: str) -> bool:
    try:
        url = f"http://127.0.0.1:{port}/JSON/core/view/version/?apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "UWT-HealthCheck"})
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read().decode())
            return "version" in data
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "stop", "status"])
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--api-key", default="local-zap-change-me")
    args = ap.parse_args()

    PIDFILE.parent.mkdir(exist_ok=True)
    ZAP_HOME.mkdir(parents=True, exist_ok=True)

    pid = int(PIDFILE.read_text().split(",")[0]) if PIDFILE.exists() else None

    if args.action == "status":
        up = healthy(args.port, args.api_key)
        print(f"OWASP ZAP on 127.0.0.1:{args.port}: {'RUNNING' if up else 'not running'}")
        return 0 if up else 1

    if args.action == "stop":
        if pid and stop_pid(pid):
            PIDFILE.unlink(missing_ok=True)
            print("OWASP ZAP stopped.")
            return 0
        PIDFILE.unlink(missing_ok=True)
        print("No running OWASP ZAP found (nothing to stop).")
        return 0

    if healthy(args.port, args.api_key):
        print(f"OWASP ZAP is already running at http://127.0.0.1:{args.port}/")
        return 0

    java_bin = find_java()
    if not java_bin:
        print("Error: Java 17+ runtime not found. Please check tools/zap JRE.", file=sys.stderr)
        return 1

    zap_jar = find_zap_jar()
    if not zap_jar:
        print("Error: ZAP jar not found in tools/zap/.", file=sys.stderr)
        return 1

    cmd = [
        str(java_bin),
        "-Xmx512m",
        "-jar", str(zap_jar),
        "-daemon",
        "-host", "127.0.0.1",
        "-port", str(args.port),
        "-config", f"api.key={args.api_key}",
        "-config", "api.addrs.addr.name=.*",
        "-config", "api.addrs.addr.regex=true",
        "-config", "callhome.tel.enabled=false",
        "-config", "autoupdate.checkOnStart=false",
        "-config", "autoupdate.downloadNewRelease=false",
        "-config", "autoupdate.installAddonUpdates=false",
        "-dir", str(ZAP_HOME),
    ]

    log_file = ROOT / "data" / "zap.log"
    print(f"Starting OWASP ZAP daemon on port {args.port}...")
    proc = popen_background(cmd, cwd=zap_jar.parent, log_path=log_file)

    for i in range(40):
        time.sleep(1)
        if healthy(args.port, args.api_key):
            PIDFILE.write_text(f"{proc.pid},{args.port}")
            print(f"OWASP ZAP is ready at http://127.0.0.1:{args.port}/ (PID: {proc.pid})")
            return 0
        if proc.poll() is not None:
            print("ZAP process terminated unexpectedly. Check data/zap.log", file=sys.stderr)
            return 1

    print("Timed out waiting for ZAP to respond on API port.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
