"""Per-job egress guard; adapters must receive this proxy before sending requests."""
import asyncio
import json
import os
import socket
import ssl
import sys
from pathlib import Path

import httpx

from app.core.config import Settings
from app.core.policy import Target
from app.core.process import executable_next_to_python, spawn_kwargs, terminate


class EgressGuard:
    def __init__(self, target: Target, settings: Settings, directory: Path):
        self.target, self.settings, self.directory = target, settings, directory
        self.proc = None
        self.port = 0
        self._log_file = None
        self.ca_dir = settings.data_dir / "proxy-ca"

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def remote_url(self) -> str:
        return f"http://{self.settings.proxy_advertised_host}:{self.port}"

    @property
    def ca_file(self) -> Path:
        return self.ca_dir / "mitmproxy-ca-cert.pem"

    def client(self) -> httpx.AsyncClient:
        context = ssl.create_default_context()
        context.load_verify_locations(str(self.ca_file))
        return httpx.AsyncClient(
            proxy=self.local_url, verify=context, trust_env=False,
            timeout=self.settings.request_timeout, follow_redirects=False,
            headers={"User-Agent": self.settings.user_agent},
            limits=httpx.Limits(max_connections=4),
        )

    async def __aenter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ca_dir.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", 0))
            self.port = sock.getsockname()[1]
        config = self.directory / "guard.json"
        config.write_text(json.dumps({
            "origin": self.target.origin,
            "hostname": self.target.hostname,
            "port": self.target.port,
            "address": self.target.addresses[0],
            "max_requests": self.settings.max_requests,
            "rate": self.settings.proxy_rate,
            "body_limit": self.settings.max_body_bytes,
            "events_file": str(self.directory / "guard-events.jsonl"),
            "ready_file": str(self.directory / "guard-ready"),
        }))
        ready = self.directory / "guard-ready"
        ready.unlink(missing_ok=True)
        exe = executable_next_to_python("mitmdump")
        self._log_file = (self.directory / "guard.log").open("w")
        try:
            self.proc = await asyncio.create_subprocess_exec(
                str(exe), "--listen-host", "0.0.0.0", "--listen-port", str(self.port),
                "--set", f"confdir={self.ca_dir}", "--set", "connection_strategy=lazy",
                "--set", "ssl_insecure=false", "--set", "http2=false",
                "--set", "upstream_cert=false", "--set", "block_global=false",
                "--set", "block_private=false", "--set", "websocket=false",
                "--set", f"body_size_limit={self.settings.max_body_bytes}",
                "-q", "-s", str(self.settings.tools_dir / "proxy" / "addon.py"),
                env={**os.environ, "UWT_GUARD_CONFIG": str(config),
                     "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
                stdout=self._log_file, stderr=self._log_file, **spawn_kwargs(),
            )
            for _ in range(100):
                if ready.exists() and self.ca_file.exists():
                    return self
                if self.proc.returncode is not None:
                    raise RuntimeError("The outbound safety proxy could not start; scan refused.")
                await asyncio.sleep(0.1)
            raise RuntimeError("The outbound safety proxy timed out; scan refused.")
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *_):
        if self.proc:
            await terminate(self.proc)
        if self._log_file:
            self._log_file.close()

    def observations(self) -> dict:
        path = self.directory / "guard-events.jsonl"
        events = []
        if path.exists():
            for line in path.read_text().splitlines()[-300:]:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        return {"blocked_requests": len(events), "examples": events[:6],
                "dns_pinned_to": self.target.addresses[0], "same_origin_only": True}
