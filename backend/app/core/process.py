"""No shell execution. Timeouts/cancellation terminate the complete process tree (Linux, macOS, Windows)."""
import asyncio
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def spawn_kwargs() -> dict:
    """Start children in their own process group/session so the whole tree can be stopped."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def executable_next_to_python(name: str) -> str:
    """Locate a console script installed beside the interpreter (Scripts\\name.exe on Windows)."""
    base = Path(sys.executable).parent
    for candidate in (base / name, base / f"{name}.exe", base / "Scripts" / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name) or str(base / name)


async def _kill_tree(proc: asyncio.subprocess.Process, force: bool) -> None:
    if IS_WINDOWS:
        # taskkill /T stops child processes too; /F is the forceful variant.
        args = ["taskkill", "/PID", str(proc.pid), "/T"] + (["/F"] if force else [])
        killer = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)


async def terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        await _kill_tree(proc, force=False)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        try:
            await _kill_tree(proc, force=True)
        except ProcessLookupError:
            pass
        await proc.wait()


async def run_command(args: list[str], *, timeout: float = 60, env: dict | None = None,
                      cwd: Path | None = None) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **(env or {})}, cwd=cwd, **spawn_kwargs(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
        return CommandResult(proc.returncode, out.decode(errors="replace")[-250_000:], err.decode(errors="replace")[-12_000:])
    except BaseException:
        await terminate(proc)
        raise
