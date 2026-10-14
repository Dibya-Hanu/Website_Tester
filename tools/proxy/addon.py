"""mitmproxy addon: enforced read-only, same-origin, DNS-pinned outbound access.

The target is immutable for a job. Scanner output never controls this file.
Only denial metadata is logged; cookies, response bodies and tokens are not.
"""
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from mitmproxy import http
from app.core.policy import origin, safe_read_url
from app.core.redact import safe_url


class ReadOnlyGuard:
    def __init__(self):
        self.config = json.loads(Path(os.environ["UWT_GUARD_CONFIG"]).read_text())
        self.count = 0
        self.next_slot = 0.0
        self.rate_lock = asyncio.Lock()

    def running(self):
        Path(self.config["ready_file"]).write_text("ready")

    def deny(self, flow, reason):
        with Path(self.config["events_file"]).open("a") as out:
            out.write(json.dumps({"url": safe_url(flow.request.pretty_url)[:1000], "reason": reason}) + "\n")
        flow.response = http.Response.make(451, b"Blocked by AI Universal Website Tester safety policy.",
                                          {"Content-Type": "text/plain", "X-UWT-Blocked": reason})

    async def request(self, flow: http.HTTPFlow):
        request = flow.request
        url = request.pretty_url
        if origin(url) != self.config["origin"]:
            self.deny(flow, "cross-origin")
            return
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            self.deny(flow, "mutation-method")
            return
        if not safe_read_url(url):
            self.deny(flow, "unsafe-action-url")
            return
        if request.headers.get("Upgrade", "").lower() == "websocket":
            self.deny(flow, "websocket")
            return
        if request.raw_content:
            self.deny(flow, "request-body")
            return
        self.count += 1
        if self.count > self.config["max_requests"]:
            self.deny(flow, "request-budget")
            return
        # One global rate limiter applies to every scanner, including concurrent load.
        async with self.rate_lock:
            current = time.monotonic()
            delay = max(0, self.next_slot - current)
            self.next_slot = max(current, self.next_slot) + 1 / self.config["rate"]
        if delay:
            await asyncio.sleep(delay)

    def server_connect(self, data):
        host, port = data.server.address
        if host.lower().rstrip(".") != self.config["hostname"] or port != self.config["port"]:
            data.server.error = "Unauthorized outbound connection."
            return
        # Keep the TLS SNI / Host as the original hostname; pin only the TCP destination.
        data.server.address = (self.config["address"], port)

    def responseheaders(self, flow: http.HTTPFlow):
        if flow.response is None or flow.response.headers.get("X-UWT-Blocked"):
            return
        content_length = flow.response.headers.get("Content-Length", "")
        if content_length.isdigit() and int(content_length) > self.config["body_limit"]:
            # Stop before buffering oversized data. Do not replace an in-flight
            # response body: that would corrupt HTTP message framing.
            with Path(self.config["events_file"]).open("a") as out:
                out.write(json.dumps({"url": safe_url(flow.request.pretty_url)[:1000], "reason": "body-limit"}) + "\n")
            flow.kill()

    def response(self, flow: http.HTTPFlow):
        # Buffered response hook runs BEFORE delivery to the client. Redirects
        # are refused here so scanners cannot follow them, while original HTTP
        # content-length framing has already been consumed correctly.
        if flow.response is None or flow.response.headers.get("X-UWT-Blocked"):
            return
        location = flow.response.headers.get("Location")
        if location:
            resolved = urljoin(flow.request.pretty_url, location)
            if origin(resolved) != self.config["origin"] or not safe_read_url(resolved):
                self.deny(flow, "unsafe-redirect")


addons = [ReadOnlyGuard()]
