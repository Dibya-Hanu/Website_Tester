#!/usr/bin/env python3
"""Practice Shop: a tiny, deliberately flawed website for demonstrating the tester.

Safe by design
  * Pure Python standard library; works the same on Linux, macOS and Windows.
  * Binds to loopback (127.0.0.1) only and REFUSES any other host.
  * Stores nothing, executes nothing, reads no files, contacts no network.
  * All "secrets" are obviously fake placeholder strings.
  * Reflected text is filtered so that no script can ever execute (inert HTML only).

Every flaw is listed in practice_app/expected_findings.json and README.md.
"""
import argparse
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DEFAULT_PORT = 8765
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

STYLE = "body{font-family:system-ui,sans-serif;max-width:760px;margin:30px auto;padding:0 16px;color:#222}nav a{margin-right:14px}"


def page(title: str, body: str, extra_head: str = "") -> bytes:
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title>"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>{STYLE}</style>{extra_head}</head><body>"
            "<nav><a href=\"/\">Home</a><a href=\"/products\">Products</a><a href=\"/about\">About</a>"
            "<a href=\"/contact\">Contact</a><a href=\"/search\">Search</a><a href=\"/slow\">Reports</a></nav><main>"
            f"{body}</main></body></html>").encode()


HOME = page("Practice Shop", """
<h1>Practice Shop</h1>
<p>A fictional store used to demonstrate automated website testing.</p>
<img src="/assets/logo.svg" width="120" height="60">
<img src="/assets/missing-banner.png" alt="Sale banner" width="300" height="80">
<p><a href="/missing-page">Our summer catalogue</a> &middot; <a href="/about">Learn about us</a></p>
""")

ABOUT = page("About", """
<h1>About us</h1>
<h4>Our story</h4>
<p style="color:#bbbbbb;background:#ffffff">We have sold fictional goods since 2001. This light-grey paragraph has deliberately low contrast.</p>
<script>undefinedPracticeFunction();</script>
""")

CONTACT = page("Contact", """
<h1>Contact us</h1>
<form method="post" action="/contact">
  <p><span>Your name</span><br><input type="text" name="name"></p>
  <p><span>Email</span><br><input type="text" name="email"></p>
  <p><span>Message</span><br><textarea name="message"></textarea></p>
  <button type="submit">Send</button>
</form>
""")

PRODUCTS = page("Products", """
<h1>Products</h1>
<ul><li>Practice widget</li><li>Demo gadget</li></ul>
<a href="/about"><svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7"/></svg></a>
<button type="button"></button>
<script src="/assets/big.js"></script>
""")

SEARCH_FORM = """
<h1>Search</h1>
<form method="get" action="/search"><label for="q">Search term</label> <input id="q" name="q" type="text"> <button type="submit">Search</button></form>
"""

ENV_FILE = b"APP_ENV=practice\nDEMO_SECRET_KEY=not-a-real-secret\nDEMO_API_TOKEN=fake-token-for-demo\nDEMO_DB_PASSWORD=fake-password\n"
GIT_HEAD = b"ref: refs/heads/main\n"
ROBOTS = b"User-agent: *\nDisallow: /private/\n"
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect width="120" height="60" fill="#1f6f5c"/><text x="12" y="36" fill="#fff" font-size="16">Practice</text></svg>'
BIG_JS = (b"/* intentionally oversized practice asset (padding only) */\n" + (b"// padding padding padding padding padding padding padding\n" * 27000))


def inert(value: str) -> str:
    """Reflect text as HTML but never allow script execution (no <script>, on*= handlers, javascript:)."""
    value = re.sub(r"(?i)<\s*/?\s*(script|iframe|object|embed|svg|style)[^>]*>", "", value)
    value = re.sub(r"(?i)\bon\w+\s*=", "x=", value)
    return re.sub(r"(?i)javascript\s*:", "", value)[:300]


class Handler(BaseHTTPRequestHandler):
    server_version = "PracticeShop"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep consoles quiet; set PRACTICE_VERBOSE=1 to enable
        import os
        if os.environ.get("PRACTICE_VERBOSE"):
            sys.stderr.write("practice-app: " + fmt % args + "\n")

    # NOTE: deliberately NO security headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy).
    def send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8", cookie: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cookie:  # intentionally weak: no HttpOnly / Secure / SameSite
            self.send_header("Set-Cookie", "session_id=practice-demo-session; Path=/")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/":
            self.send(200, HOME, cookie=True)
        elif path == "/about":
            self.send(200, ABOUT)
        elif path == "/contact":
            self.send(200, CONTACT)
        elif path == "/products":
            self.send(200, PRODUCTS)
        elif path == "/search":
            q = query.get("q", [""])[0]
            shown = f"<p>Results for: {inert(q)}</p>" if q else ""  # intentional: unescaped (but inert) reflection
            self.send(200, page("Search", SEARCH_FORM + shown))
        elif path == "/slow":
            time.sleep(1.8)  # intentional measurable slow response
            self.send(200, page("Reports", "<h1>Reports</h1><p>This page deliberately responds slowly.</p>"))
        elif path == "/assets/logo.svg":
            self.send(200, LOGO, "image/svg+xml")
        elif path == "/assets/big.js":
            self.send(200, BIG_JS, "application/javascript")  # intentional ~1.5 MB uncached asset
        elif path == "/.env":
            self.send(200, ENV_FILE, "text/plain; charset=utf-8")  # intentional fake exposed file
        elif path == "/.git/HEAD":
            self.send(200, GIT_HEAD, "text/plain; charset=utf-8")
        elif path == "/robots.txt":
            self.send(200, ROBOTS, "text/plain; charset=utf-8")
        elif path == "/favicon.ico":
            self.send(204, b"", "image/x-icon")
        elif path == "/health":
            self.send(200, b'{"status":"ok","app":"practice-shop"}', "application/json")
        else:
            self.send(404, page("Not found", "<h1>404 - Page not found</h1>"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(min(length, 10_000))  # read and discard; nothing is stored
        if urlsplit(self.path).path == "/contact":  # intentional: accepts empty/invalid input
            self.send(200, page("Thanks", "<h1>Thanks!</h1><p>Your message was accepted (nothing is stored).</p>"))
        else:
            self.send(405, b"Method not allowed", "text/plain")


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise SystemExit(f"Refusing to bind to {host!r}: the practice app is loopback-only by design.")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    server = make_server(args.host, args.port)
    print(f"Practice Shop listening on http://{args.host}:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
