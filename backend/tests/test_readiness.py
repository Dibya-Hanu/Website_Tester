import asyncio

import pytest

from app.scanners.browser import wait_for_dom_stability


class StablePage:
    def __init__(self):
        self.calls = 0

    async def wait_for_load_state(self, state, timeout):
        assert state == "load"

    async def evaluate(self, script):
        self.calls += 1
        # Simulate a client-side app hydrating once after first paint.
        return {
            "ready_state": "complete",
            "text_length": 10 if self.calls < 2 else 120,
            "child_count": 1 if self.calls < 2 else 5,
            "link_count": 1 if self.calls < 2 else 7,
            "form_count": 0,
            "control_count": 0,
            "image_count": 0,
        }

    async def wait_for_timeout(self, milliseconds):
        await asyncio.sleep(milliseconds / 1000)


@pytest.mark.asyncio
async def test_readiness_waits_for_hydrated_dom_to_stabilize():
    result = await wait_for_dom_stability(StablePage(), timeout_ms=1800, sample_ms=100, required_stable_samples=2)
    assert result["strategy"] == "load-event-plus-dom-stability"
    assert result["stable"] is True
    assert result["snapshot"]["text_length"] == 120
    assert result["wait_ms"] >= 300
