#!/usr/bin/env python3
"""Automatic, idempotent Ollama model bootstrap. No work after URL submission."""
import json
import sys
import time

import httpx

from app.ai.client import OPEN_MODELS
from app.core.config import Settings

settings = Settings()
if not settings.ai_enabled:
    print("Local AI disabled by deployment settings; no model downloads.", flush=True)
    sys.exit(0)
models = [settings.text_model]
if settings.pull_vision:
    models.append(settings.vision_model)
for model in models:
    if model not in OPEN_MODELS:
        raise SystemExit(f"Model {model} is not in the reviewed open-source manifest.")
with httpx.Client(base_url=settings.ollama_url, timeout=None, trust_env=False) as client:
    for attempt in range(60):
        try:
            response = client.get("/api/tags", timeout=5)
            response.raise_for_status()
            break
        except httpx.HTTPError:
            time.sleep(2)
    else:
        raise SystemExit("Local Ollama did not become ready.")
    for model in dict.fromkeys(models):
        print(f"Ensuring local {model} ({OPEN_MODELS[model]})", flush=True)
        with client.stream("POST", "/api/pull", json={"model": model, "stream": True}) as response:
            response.raise_for_status()
            previous = ""
            success = False
            for line in response.iter_lines():
                item = json.loads(line)
                if item.get("error"):
                    raise SystemExit(item["error"])
                status = item.get("status", "")
                if status != previous:
                    print(f"{model}: {status}", flush=True)
                    previous = status
                if status == "success":
                    success = True
            if not success:
                raise SystemExit(f"Pull of {model} did not finish successfully.")
print("Local model bootstrap complete. URL-only tests are ready.", flush=True)
