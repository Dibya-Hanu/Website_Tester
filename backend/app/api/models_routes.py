from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ai.registry import (KIND_TO_CATEGORY, ModelStore, installed_tags, load_catalog, model_status, now,
                              recommend, run_model_test)

router = APIRouter(prefix="/api/models")


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text", "vision", "coding"]
    model_id: str = Field(max_length=64)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Literal["text", "vision", "coding"] = "text"
    priorities: dict[str, float] = Field(default_factory=dict, max_length=10)
    classification: Literal["all", "open", "paid", "local"] = "all"


def _store(request: Request) -> ModelStore:
    return ModelStore(request.app.state.settings.data_dir)


def _find(model_id: str):
    for entry in load_catalog().models:
        if entry.id == model_id:
            return entry
    raise HTTPException(404, "Unknown model id.")


@router.get("")
async def list_models(request: Request):
    s = request.app.state.settings
    installed, reason = await installed_tags(s.ollama_url, s.ai_enabled)
    stored = _store(request).read()
    catalog = load_catalog()
    models = [{**m.model_dump(), "status": model_status(m, installed, stored), "last_test": (stored.get("tests") or {}).get(m.id)} for m in catalog.models]
    return {"catalog_version": catalog.catalog_version, "note": catalog.note, "ollama": {"reachable": installed is not None, "detail": reason},
            "selection": stored.get("selection") or {}, "defaults": {"text": s.text_model, "vision": s.vision_model}, "models": models}


@router.post("/recommend")
async def recommend_models(payload: RecommendRequest, request: Request):
    s = request.app.state.settings
    installed, _ = await installed_tags(s.ollama_url, s.ai_enabled)
    stored, rows = _store(request).read(), []
    for m in load_catalog().models:
        if payload.classification == "open" and m.cost_type != "self-hosted":
            continue
        if payload.classification == "paid" and m.cost_type != "paid-api":
            continue
        if payload.classification == "local" and m.deployment != "local":
            continue
        status = model_status(m, installed, stored)
        rows.append({"id": m.id, "display_name": m.display_name, "status": status, **recommend(m, payload.task, payload.priorities, status)})
    rows.sort(key=lambda r: -r["score"])
    return {"task": payload.task, "category_used": KIND_TO_CATEGORY[payload.task], "results": rows}


@router.post("/{model_id}/test")
async def test_model(model_id: str, kind: Literal["text", "vision", "coding"], request: Request):
    entry, s = _find(model_id), request.app.state.settings
    if not entry.supported_in_app or not entry.ollama_tag:
        raise HTTPException(400, "This model cannot be tested here: it is not served by the built-in Ollama runner.")
    if KIND_TO_CATEGORY[kind] not in entry.categories:
        raise HTTPException(400, f"This model is not listed for the '{kind}' task.")
    installed, reason = await installed_tags(s.ollama_url, s.ai_enabled)
    if installed is None:
        raise HTTPException(503, reason)
    if entry.ollama_tag not in installed and f"{entry.ollama_tag}:latest" not in installed:
        raise HTTPException(409, f"{entry.ollama_tag} is not installed. Run: ollama pull {entry.ollama_tag}")
    result = await run_model_test(entry, kind, s.ollama_url)
    store = _store(request)
    data = store.read()
    data.setdefault("tests", {})[entry.id] = result
    store.write(data)
    return result


@router.put("/selection")
async def save_selection(payload: Selection, request: Request):
    entry = _find(payload.model_id)
    if not entry.supported_in_app or not entry.license.reviewed or not entry.ollama_tag:
        raise HTTPException(400, "Only licence-reviewed models served by the built-in Ollama runner can be selected.")
    if KIND_TO_CATEGORY[payload.kind] not in entry.categories:
        raise HTTPException(400, f"This model is not listed for the '{payload.kind}' task.")
    store = _store(request)
    data = store.read()
    data.setdefault("selection", {})[payload.kind] = {"model_id": entry.id, "ollama_tag": entry.ollama_tag, "saved_at": now(),
        "verified_working": bool(((data.get("tests") or {}).get(entry.id) or {}).get("ok"))}
    store.write(data)
    return {"selection": data["selection"], "note": "Saved. The model is only reliable once Test Model has passed."}


@router.delete("/selection/{kind}")
async def clear_selection(kind: Literal["text", "vision", "coding"], request: Request):
    store = _store(request)
    data = store.read()
    (data.get("selection") or {}).pop(kind, None)
    store.write(data)
    return {"selection": data.get("selection") or {}}
