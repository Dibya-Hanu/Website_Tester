#!/usr/bin/env python3
"""Start, stop or check the bundled practice app in the background (Linux, macOS, Windows).

  python scripts/practice_ctl.py start [--port 8765]
  python scripts/practice_ctl.py status
  python scripts/practice_ctl.py stop
"""
import argparse
import sys
import time
from pathlib import Path

import urllib.request

sys.path.insert(0, str(Path(__file__).parent))
from _proc import pid_alive, popen_background, stop_pid  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PIDFILE = ROOT / "data" / "practice_app.pid"


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "stop", "status"])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    PIDFILE.parent.mkdir(exist_ok=True)
    pid = int(PIDFILE.read_text().split(",")[0]) if PIDFILE.exists() else None
    if args.action == "status":
        up = healthy(args.port)
        print(f"practice app on 127.0.0.1:{args.port}: {'RUNNING' if up else 'not running'}")
        return 0 if up else 1
    if args.action == "stop":
        if pid and stop_pid(pid):
            PIDFILE.unlink(missing_ok=True)
            print("Practice app stopped.")
            return 0
        PIDFILE.unlink(missing_ok=True)
        print("No running practice app found (nothing to stop).")
        return 0
    if healthy(args.port):
        print(f"Already running at http://127.0.0.1:{args.port}/")
        return 0
    proc = popen_background([sys.executable, str(ROOT / "practice_app" / "practice_shop.py"), "--port", str(args.port)],
                            log_path=ROOT / "data" / "practice_app.log")
    for _ in range(50):
        if healthy(args.port):
            PIDFILE.write_text(f"{proc.pid},{args.port}")
            print(f"Practice app running at http://127.0.0.1:{args.port}/  (stop: python scripts/practice_ctl.py stop)")
            return 0
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    print("Practice app failed to start; see data/practice_app.log", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
