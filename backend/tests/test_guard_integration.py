"""Actual proxy boundary test; never scans an external website."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.guard import EgressGuard
from app.core.policy import TargetPolicy


class Handler(BaseHTTPRequestHandler):
    mutation_count = 0
    reads = []
    def do_GET(self):
        self.reads.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location","http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"safe fixture")
    def do_POST(self):
        Handler.mutation_count += 1
        self.send_response(200)
        self.end_headers()
    def log_message(self,*args):
        pass


async def test_proxy_enforces_methods_origin_redirects_and_action_urls(settings, tmp_path):
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    root=f"http://127.0.0.1:{server.server_port}"
    settings.allowlist=root
    settings.proxy_advertised_host="127.0.0.1"
    target=await TargetPolicy(settings).resolve(root)
    try:
        async with EgressGuard(target,settings,tmp_path/"guard") as guard:
            async with guard.client() as client:
                assert (await client.get(root)).status_code == 200
                assert (await client.post(root)).status_code == 451
                assert (await client.get(root+"/delete/item")).status_code == 451
                assert (await client.get(root+"/redirect")).status_code == 451
                assert (await client.get("http://169.254.169.254/")).status_code == 451
            assert Handler.mutation_count == 0
            assert not any("delete" in value for value in Handler.reads)
            assert guard.observations()["blocked_requests"] >= 4
    finally:
        server.shutdown()
        server.server_close()
