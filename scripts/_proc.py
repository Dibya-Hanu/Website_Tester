"""Tiny cross-platform helpers for starting/stopping background processes (Linux, macOS, Windows)."""
import os
import signal
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"


def popen_background(args, *, cwd=None, env=None, log_path=None):
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)} if IS_WINDOWS \
        else {"start_new_session": True}
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    return subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs)


def stop_pid(pid: int) -> bool:
    """Stop a process tree. Returns True if a signal/command was sent."""
    try:
        if IS_WINDOWS:
            return subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True).returncode == 0
        os.killpg(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
