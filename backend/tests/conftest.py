import pytest

from app.core.config import Settings
from app.core.models import Evidence, Finding, Location, Pillar, Severity
from app.core.store import Store


@pytest.fixture
def settings(tmp_path):
    value = Settings(data_dir=tmp_path / "data", allowlist="http://lab.test:3000", ai_enabled=False)
    value.prepare()
    return value


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


@pytest.fixture
def make_finding():
    def build(**changes):
        data = dict(title="Missing defense", pillar=Pillar.SECURITY, severity=Severity.MEDIUM,
                    category="header-csp", location=Location(url="http://lab.test:3000/", header="content-security-policy"),
                    evidence=[Evidence(detail="Header absent")], explanation="Observed missing header.",
                    suggested_fix="Set a restrictive CSP.", sources=["test scanner"])
        data.update(changes)
        return Finding(**data)
    return build


# ---- practice app fixture (real local HTTP server on a random loopback port) ----
import sys
import threading
from pathlib import Path

PRACTICE_DIR = Path(__file__).resolve().parents[2] / "practice_app"


@pytest.fixture(scope="session")
def practice_url():
    sys.path.insert(0, str(PRACTICE_DIR))
    import practice_shop as practice  # practice_app/practice_shop.py (stdlib only)
    server = practice.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        sys.path.remove(str(PRACTICE_DIR))
        sys.modules.pop("practice_shop", None)
