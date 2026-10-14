"""AI model registry: schema-validated catalogue, installed-state detection, selection, test and recommendation.

The catalogue (model_catalog.json) is separate from what is installed. Nothing is downloaded automatically.
Only models served by the deployment's own Ollama (settings.ollama_url, never user-supplied) can be tested or used.
"""
import base64
import json
import struct
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

CATALOG_PATH = Path(__file__).with_name("model_catalog.json")
TaskKind = Literal["text", "vision", "coding"]
KIND_TO_CATEGORY = {"text": "general-reasoning", "vision": "vision", "coding": "coding"}


class License(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str | None
    reviewed: bool
    commercial_use: str
    notes: str


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    source: str | None
    last_verified: str | None


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.\-]{1,60}$")
    display_name: str
    provider: str
    categories: list[str]
    purpose: str
    tasks: list[str]
    modalities: list[Literal["text", "image"]]
    license: License
    classification: Literal["open-source", "open-weight", "hosted-api"]
    deployment: Literal["local", "hosted"]
    runtime: Literal["ollama", "transformers", "hosted-api"]
    ollama_tag: str | None
    api_key_required: bool
    cost_type: Literal["self-hosted", "free-tier", "paid-api"]
    pricing: Pricing
    context_length: str
    approx_size: str
    memory_requirements: str
    backends: list[str]
    limitations: list[str]
    repository_url: str | None
    setup: list[str]
    recommended_use: str
    supported_in_app: bool
    facts_verified: bool
    last_verified: str | None


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_version: str
    note: str
    models: list[ModelEntry]


def load_catalog() -> Catalog:
    return Catalog.model_validate(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def reviewed_ollama_models() -> dict[str, str]:
    """Allow-list for the AI client, derived from the catalogue so there is a single source of truth."""
    return {m.ollama_tag: m.license.name for m in load_catalog().models
            if m.ollama_tag and m.license.reviewed and m.runtime == "ollama"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModelStore:
    """Selection and test results persisted as JSON in the data directory (no secrets are stored)."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "model_selection.json"

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def selected_tag(self, kind: TaskKind) -> str | None:
        entry = (self.read().get("selection") or {}).get(kind)
        return entry.get("ollama_tag") if isinstance(entry, dict) else None


async def installed_tags(ollama_url: str, enabled: bool = True) -> tuple[set[str] | None, str]:
    """Returns (installed tags or None when unreachable, human-readable reason)."""
    if not enabled:
        return None, "AI is disabled by deployment configuration."
    try:
        async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
            response = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            return {m["name"] for m in response.json().get("models", [])}, "Ollama reachable."
    except (httpx.HTTPError, ValueError, KeyError):
        return None, "Ollama is not reachable."


def model_status(entry: ModelEntry, installed: set[str] | None, stored: dict) -> str:
    if not entry.supported_in_app:
        return "Unsupported in this build"
    if installed is None:
        return "Connection failed"
    if entry.ollama_tag not in installed and f"{entry.ollama_tag}:latest" not in installed:
        return "Not installed"
    result = (stored.get("tests") or {}).get(entry.id)
    if result:
        return "Test passed" if result.get("ok") else "Test failed"
    return "Installed"


def recommend(entry: ModelEntry, task: TaskKind, priorities: dict[str, float], status: str) -> dict:
    """Transparent score from documented criteria. Unknown criteria are excluded, never guessed."""
    weights = {"task_suitability": 3.0, "license_suitability": 2.0, "local_privacy": 1.0, "free_to_run": 1.0, "operational": 2.0}
    weights.update({k: float(v) for k, v in priorities.items() if k in weights and 0 <= float(v) <= 10})
    wanted = KIND_TO_CATEGORY[task]
    values = {
        "task_suitability": 1.0 if wanted in entry.categories else 0.0,
        "license_suitability": 1.0 if entry.license.reviewed and entry.license.name in {"Apache-2.0", "MIT"} else 0.0,
        "local_privacy": 1.0 if entry.deployment == "local" else 0.0,
        "free_to_run": 1.0 if entry.cost_type == "self-hosted" else 0.0,
        "operational": {"Test passed": 1.0, "Installed": 0.5}.get(status, 0.0),
    }
    total_weight = sum(weights.values())
    score = round(100 * sum(values[k] * weights[k] for k in values) / total_weight, 1) if total_weight else 0.0
    return {"score": score, "criteria": {k: {"value": values[k], "weight": weights[k]} for k in values},
            "not_measured": ["output quality (Not benchmarked)", "response speed (Not measured unless you run Test Model)", "hardware fit (memory requirements Unknown)"],
            "method": "Weighted average of the criteria above (editable weights). A ranking aid only, not a quality benchmark."}


def _tiny_png() -> str:
    """64x64 solid red PNG generated in code (no files, no extra dependency)."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 64 for _ in range(64))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


SAMPLES = {
    "text": {"prompt": 'Reply ONLY with JSON {"answer": <number>} for: what is 2 + 2?', "check": lambda d: d.get("answer") == 4},
    "coding": {"prompt": 'In this Python function, what is the bug? def add(a, b): return a - b. Reply ONLY with JSON {"bug": "<one sentence>"}.',
               "check": lambda d: isinstance(d.get("bug"), str) and len(d["bug"]) > 3},
    "vision": {"prompt": 'What is the dominant colour of the image? Reply ONLY with JSON {"colour": "<name>"}.',
               "check": lambda d: isinstance(d.get("colour"), str) and "red" in d["colour"].lower()},
}


async def run_model_test(entry: ModelEntry, kind: TaskKind, ollama_url: str, timeout: float = 60.0, transport=None) -> dict:
    """Small safe sample task against the deployment's Ollama. Output is schema-checked, never executed."""
    sample, started = SAMPLES[kind], time.monotonic()
    message = {"role": "user", "content": sample["prompt"]}
    if kind == "vision":
        message["images"] = [_tiny_png()]
    result = {"model_id": entry.id, "ollama_tag": entry.ollama_tag, "kind": kind, "tested_at": now(), "ok": False, "detail": "", "seconds": None}
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, transport=transport) as client:
            response = await client.post(f"{ollama_url.rstrip('/')}/api/chat", json={"model": entry.ollama_tag, "messages": [message], "stream": False, "format": "json", "options": {"temperature": 0, "num_predict": 120}})
            response.raise_for_status()
            content = response.json()["message"]["content"]
        parsed = json.loads(content)
        result["ok"] = bool(isinstance(parsed, dict) and sample["check"](parsed))
        result["detail"] = "Sample task answered correctly." if result["ok"] else "Model replied, but the answer failed validation."
    except httpx.HTTPError as exc:
        result["detail"] = f"Connection or HTTP error: {type(exc).__name__}"
    except (ValueError, KeyError, TypeError):
        result["detail"] = "Model returned invalid or unexpected JSON."
    result["seconds"] = round(time.monotonic() - started, 2)
    return result
