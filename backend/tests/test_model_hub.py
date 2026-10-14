"""Model Hub tests. Tests using httpx.MockTransport are MOCKS of Ollama (not real model integration)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.client import OPEN_MODELS, LocalAI
from app.ai.registry import Catalog, ModelStore, load_catalog, recommend, run_model_test, reviewed_ollama_models, CATALOG_PATH
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ai_enabled=True, ollama_url="http://127.0.0.1:1"), run_worker=False)
    with TestClient(app) as c:
        yield c


def test_default_models_are_allowed_regression():
    """Root-cause regression: a comment once swallowed the qwen2.5:1.5b entry, so the default text model never ran."""
    s = Settings()
    assert s.text_model in OPEN_MODELS and s.vision_model in OPEN_MODELS


def test_catalog_validates_and_ids_unique():
    cat = load_catalog()
    ids = [m.id for m in cat.models]
    assert len(ids) == len(set(ids)) and len(ids) >= 8
    assert {"general-reasoning", "coding", "vision"} <= {c for m in cat.models for c in m.categories}


def test_catalog_schema_rejects_unknown_fields():
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["models"][0]["surprise"] = 1
    with pytest.raises(Exception):
        Catalog.model_validate(data)


def test_unverified_facts_are_marked_unknown_not_invented():
    for m in load_catalog().models:
        assert not m.facts_verified and m.last_verified is None
        assert m.context_length.startswith("Unknown") and m.memory_requirements.startswith(("Unknown", "Not applicable"))
        assert m.pricing.source is None


def test_hosted_entry_is_not_selectable_or_testable(client):
    assert client.post("/api/models/hosted-openai-compatible/test?kind=text").status_code == 400
    assert client.put("/api/models/selection", json={"kind": "text", "model_id": "hosted-openai-compatible"}).status_code == 400
    hosted = next(m for m in client.get("/api/models").json()["models"] if m["id"] == "hosted-openai-compatible")
    assert hosted["status"] == "Unsupported in this build" and hosted["api_key_required"] and hosted["cost_type"] == "paid-api"


def test_list_reports_honest_status_when_ollama_down(client):
    data = client.get("/api/models").json()
    assert data["ollama"]["reachable"] is False
    assert {m["status"] for m in data["models"] if m["supported_in_app"]} == {"Connection failed"}
    assert client.post("/api/models/qwen2.5-1.5b/test?kind=text").status_code == 503


def test_selection_saved_but_not_marked_working_and_validation(client, tmp_path):
    assert client.put("/api/models/selection", json={"kind": "text", "model_id": "qwen2.5-1.5b"}).status_code == 200
    sel = client.get("/api/models").json()["selection"]["text"]
    assert sel["ollama_tag"] == "qwen2.5:1.5b" and sel["verified_working"] is False
    assert ModelStore(tmp_path).selected_tag("text") == "qwen2.5:1.5b"
    assert client.put("/api/models/selection", json={"kind": "vision", "model_id": "qwen2.5-1.5b"}).status_code == 400   # wrong task
    assert client.put("/api/models/selection", json={"kind": "text", "model_id": "florence-2-large"}).status_code == 400  # not runnable here
    assert client.put("/api/models/selection", json={"kind": "text", "model_id": "nope"}).status_code == 404
    assert client.put("/api/models/selection", json={"kind": "text", "model_id": "qwen2.5-1.5b", "x": 1}).status_code == 422
    assert client.delete("/api/models/selection/text").json()["selection"] == {}


def test_recommendation_is_transparent_and_priorities_change_ranking(client):
    base = client.post("/api/models/recommend", json={"task": "coding"}).json()
    assert base["results"][0]["id"] == "qwen2.5-coder-7b"
    first = base["results"][0]
    assert set(first["criteria"]) == {"task_suitability", "license_suitability", "local_privacy", "free_to_run", "operational"}
    assert any("Not benchmarked" in x for x in first["not_measured"])
    heavy = client.post("/api/models/recommend", json={"task": "coding", "priorities": {"task_suitability": 0, "operational": 10}}).json()
    assert heavy["results"][0]["score"] != first["score"] or heavy["results"][0]["id"] != first["id"]
    assert all(r["id"] != "hosted-openai-compatible" for r in client.post("/api/models/recommend", json={"task": "text", "classification": "open"}).json()["results"])
    assert client.post("/api/models/recommend", json={"task": "bogus"}).status_code == 422


def test_recommend_function_ignores_out_of_range_weights():
    m = load_catalog().models[0]
    assert recommend(m, "text", {"task_suitability": 999}, "Installed")["criteria"]["task_suitability"]["weight"] == 3.0


def mock_ollama(answer):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": answer}})
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("kind,model,good,bad", [("text", "qwen2.5-1.5b", '{"answer": 4}', '{"answer": 5}'), ("coding", "qwen2.5-coder-7b", '{"bug": "It subtracts instead of adding."}', '{"bug": ""}'),
                                                    ("vision", "qwen2.5vl-7b", '{"colour": "Red"}', '{"colour": "blue"}')])
async def test_model_test_validates_output_with_mock_ollama(kind, model, good, bad):
    entry = next(m for m in load_catalog().models if m.id == model)
    assert (await run_model_test(entry, kind, "http://mock", transport=mock_ollama(good)))["ok"] is True
    failed = await run_model_test(entry, kind, "http://mock", transport=mock_ollama(bad))
    assert failed["ok"] is False and "validation" in failed["detail"]
    garbage = await run_model_test(entry, kind, "http://mock", transport=mock_ollama("not json at all"))
    assert garbage["ok"] is False and "invalid" in garbage["detail"].lower()


async def test_model_test_survives_server_error():
    entry = load_catalog().models[0]
    t = httpx.MockTransport(lambda r: httpx.Response(500))
    assert (await run_model_test(entry, "text", "http://mock", transport=t))["ok"] is False


async def test_local_ai_uses_saved_selection(tmp_path):
    ModelStore(tmp_path).write({"selection": {"text": {"model_id": "qwen2.5-7b", "ollama_tag": "qwen2.5:7b"}}})
    ai = LocalAI(Settings(data_dir=tmp_path, ai_enabled=False))
    await ai.perform("probe", "x", {}, dict)  # AI disabled: records the model it WOULD use
    assert ai.tasks[0]["model"] == "qwen2.5:7b"


def test_open_model_allow_list_comes_from_catalogue():
    assert set(reviewed_ollama_models()) <= set(OPEN_MODELS)


async def test_local_ai_http_error_with_non_object_json_does_not_leave_running_task(tmp_path, monkeypatch):
    from pydantic import BaseModel

    class Output(BaseModel):
        answer: str

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def get(self, url, **kwargs):
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]}, request=httpx.Request("GET", url))
        async def post(self, url, **kwargs):
            return httpx.Response(500, json=None, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    settings = Settings(data_dir=tmp_path, ai_enabled=True, ollama_url="http://mock-ollama", text_model="qwen2.5:1.5b")
    ai = LocalAI(settings)
    result = await ai.perform("regression test", "return answer", {}, Output)
    assert result is None
    assert ai.tasks[-1]["status"] == "failed"
    assert "running" not in [task["status"] for task in ai.tasks]


def test_tools_status_handles_malformed_local_service_json(client, monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def get(self, url, **kwargs):
            return httpx.Response(200, json=None, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    response = client.get("/api/tools")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ollama_reachable"] is False
    by_name = {tool["name"]: tool for tool in payload["tools"]}
    assert by_name["Ollama text model"]["available"] is False
    assert by_name["OWASP ZAP"]["available"] is False
