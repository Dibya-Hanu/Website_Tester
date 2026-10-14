import asyncio

import pytest

from app.core.config import Settings
from app.core.models import CreateJob
from app.core.store import Store
from app.pipeline.runner import JobWorker


async def test_external_worker_stops_pipeline_when_api_persists_cancellation(tmp_path):
    store = Store(tmp_path / "tester.sqlite3")
    job = store.create_job(CreateJob(url="http://lab.test:3000/"))
    store.update(job["id"], status="running")
    worker = JobWorker(Settings(data_dir=tmp_path, worker_mode="external"), store)
    stopped = asyncio.Event()

    async def long_running_pipeline():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    active = asyncio.create_task(long_running_pipeline())
    watcher = asyncio.create_task(worker._watch_persisted_cancellation(job["id"], active))
    await asyncio.sleep(0.05)
    store.update(job["id"], status="cancelled")
    await asyncio.wait_for(stopped.wait(), timeout=1.5)
    await asyncio.wait_for(watcher, timeout=1.5)
    assert active.cancelled()


def test_external_mode_does_not_start_an_inline_worker(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path, worker_mode="external"))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert app.state.worker.task is None
