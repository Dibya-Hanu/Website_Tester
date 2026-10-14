"""Regression tests for replayable AI and pillar activity events."""
from app.core.models import Pillar
from app.pipeline.runner import Progress


class MemoryEventStore:
    def __init__(self):
        self.events = []
        self.updates = []

    def event(self, jid, payload):
        self.events.append((jid, payload))
        return len(self.events)

    def update(self, jid, **values):
        self.updates.append((jid, values))


def test_progress_persists_pipeline_and_pillar_activity_events():
    store = MemoryEventStore()
    progress = Progress(store, "job-1", [Pillar.FUNCTIONALITY])

    progress.step("crawl", "running", "Mapping a page")

    event_types = [payload["type"] for jid, payload in store.events if jid == "job-1"]
    assert "progress" in event_types
    assert "pillar_activity" in event_types
    assert "log" in event_types
    pillar_event = next(payload for _, payload in store.events if payload["type"] == "pillar_activity")
    assert pillar_event["pillars"][Pillar.FUNCTIONALITY.value]["selected"] is True
    assert pillar_event["pillars"][Pillar.SECURITY.value]["status"] == "not_selected"


def test_progress_coverage_is_workflow_coverage_not_a_quality_score():
    store = MemoryEventStore()
    progress = Progress(store, "job-2", [Pillar.SECURITY])
    progress.step("custom_security", "completed", "Headers inspected")
    event = [payload for _, payload in store.events if payload["type"] == "pillar_activity"][-1]
    security = event["pillars"][Pillar.SECURITY.value]
    assert security["completed_steps"] == 1
    assert security["pipeline_coverage_percent"] < 100
    assert "score" not in security
