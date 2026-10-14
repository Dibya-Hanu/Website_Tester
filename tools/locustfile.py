"""Read-only light load, with hard caps and an early error/latency circuit breaker."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import gevent
from locust import HttpUser, between, events, task

CONFIG = json.loads(Path(os.environ["UWT_LOAD_CONFIG"]).read_text())
assert CONFIG["authorized"] is True, "Load REFUSED without organizer authorization."
assert 1 <= CONFIG["users"] <= 20 and 1 <= CONFIG["seconds"] <= 30
assert CONFIG["proxy"].startswith("http://"), "A mandatory egress guard is required."
TOTAL = FAILURES = SLOW = 0
CIRCUIT_REASON = ""
STARTED = time.monotonic()
ENVIRONMENT = None


@events.init.add_listener
def on_init(environment, **kwargs):
    global ENVIRONMENT
    ENVIRONMENT = environment
    if environment.parsed_options.num_users > 20:
        raise RuntimeError("Hard user cap exceeded.")


@events.request.add_listener
def on_request(response_time, exception, response=None, **kwargs):
    global TOTAL, FAILURES, SLOW, CIRCUIT_REASON
    TOTAL += 1
    if exception or (response is not None and response.status_code >= 400):
        FAILURES += 1
    if response_time > 5000:
        SLOW += 1
    reason = ""
    if response is not None and response.status_code in {429, 503}:
        reason = "Target requested backoff (429/503)."
    elif TOTAL >= 8 and FAILURES / TOTAL > .20:
        reason = "Error ratio exceeded 20%; stopped early to protect target."
    elif SLOW >= 3:
        reason = "Repeated responses over 5 seconds; stopped early to protect target."
    if reason and not CIRCUIT_REASON and ENVIRONMENT and ENVIRONMENT.runner:
        CIRCUIT_REASON = reason
        gevent.spawn(ENVIRONMENT.runner.quit)


@events.quitting.add_listener
def write_summary(environment, **kwargs):
    Path(CONFIG["result_file"]).write_text(json.dumps({
        "requests": TOTAL, "failures": FAILURES, "circuit_breaker": CIRCUIT_REASON or None,
        "elapsed_seconds": round(time.monotonic() - STARTED, 2),
        "configured_users": CONFIG["users"], "configured_seconds": CONFIG["seconds"],
    }))


class ReadOnlyVisitor(HttpUser):
    wait_time = between(.75, 1.5)

    def on_start(self):
        self.client.proxies = {"http": CONFIG["proxy"], "https": CONFIG["proxy"]}
        self.client.trust_env = False
        self.client.verify = CONFIG["ca_file"]
        self.client.headers["User-Agent"] = CONFIG["user_agent"]
        self.index = 0

    @task
    def read_public_page(self):
        path = CONFIG["paths"][self.index % len(CONFIG["paths"])]
        self.index += 1
        # Only configured, policy-reviewed GET paths; no scripts, bodies or form submissions.
        with self.client.get(path, name="Read-only page", timeout=5,
                             allow_redirects=False, catch_response=True) as response:
            if response.status_code >= 400:
                response.failure(f"HTTP {response.status_code}")
