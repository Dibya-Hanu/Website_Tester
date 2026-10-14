"""Same-origin REST API, durable SSE progress and evidence-safe report exports."""
import asyncio
import json
import re
from pathlib import Path
from time import monotonic

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.api.xlsx_export import render_xlsx
from app.api.exports import evidence_file, render_csv, render_html, render_pdf
from app.core.models import CreateJob
from app.core.policy import PolicyError, normalized_url

router = APIRouter(prefix="/api")
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


def get_job(request: Request, jid: str, *, report=False):
    if not JOB_ID.fullmatch(jid):
        raise HTTPException(404, "Test not found.")
    job = request.app.state.store.get_job(jid, with_report=report)
    if not job:
        raise HTTPException(404, "Test not found.")
    return job


@router.get("/health")
async def health():
    return {"status": "ok", "app": "AI Universal Website Tester", "version": "1.0.0"}


@router.get("/policy")
async def policy(request: Request):
    return request.app.state.policy.public_description()


@router.get("/policy/check")
async def check_policy(request: Request, url: str = Query(max_length=2048)):
    try:
        canonical = normalized_url(url)
        allowed = request.app.state.policy.is_authorized(canonical)
        strict = request.app.state.settings.require_allowlist_all_scans
        warning = None if allowed else ("REFUSED: all scans require an approved exact origin." if strict else "Security and load tests REFUSED: this exact origin is not allowlisted.")
        return {"url": canonical, "authorized": allowed, "warning": warning}
    except PolicyError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/jobs", status_code=202)
async def create(request: Request, payload: CreateJob):
    try:
        payload.url = normalized_url(payload.url.strip())
        request.app.state.policy.validate_literal_host(payload.url)
    except PolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Reject disallowed hosts before even resolving their DNS when competition
    # mode is enabled. The worker repeats this policy check as defense in depth.
    if request.app.state.settings.require_allowlist_all_scans and not request.app.state.policy.is_authorized(payload.url):
        raise HTTPException(403, "Scan refused: this exact origin is not on the deployment-approved allowlist.")
    try:
        # Validate DNS and SSRF before enqueueing; worker resolves again and pins for the run.
        target = await request.app.state.policy.resolve(payload.url)
    except PolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    peer = request.client.host if request.client else "local"
    current = monotonic()
    previous = request.app.state.submissions.get(peer, 0)
    if current - previous < 2:
        raise HTTPException(429, "Wait two seconds between test submissions.")
    try:
        job = request.app.state.store.create_job(payload, request.app.state.settings.max_queue)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    request.app.state.submissions[peer] = current
    if len(request.app.state.submissions) > 1000:
        request.app.state.submissions = {k: v for k, v in request.app.state.submissions.items() if current-v < 60}
    request.app.state.worker.wake.set()
    return {**job, "authorized": target.authorized,
            "warning": None if target.authorized else "Security and load REFUSED; passive checks only are enabled by deployment policy."}


@router.get("/jobs")
async def history(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000)):
    return {"jobs": request.app.state.store.list_jobs(limit, offset)}


@router.get("/jobs/{jid}")
async def detail(request: Request, jid: str):
    return get_job(request, jid)


@router.post("/jobs/{jid}/cancel")
async def cancel(request: Request, jid: str):
    get_job(request, jid)
    await request.app.state.worker.cancel(jid)
    return {"status": "cancelled"}


@router.get("/jobs/{jid}/events")
async def events(request: Request, jid: str, since: int = Query(0, ge=0)):
    get_job(request, jid)
    resume = request.headers.get("last-event-id", "")
    if resume.isdigit():
        since = max(since, int(resume))
    async def stream():
        cursor = since
        ticks = 0
        while not await request.is_disconnected():
            batch = request.app.state.store.events(jid, cursor)
            for item in batch:
                cursor = item["id"]
                yield f"id: {cursor}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
            job = request.app.state.store.get_job(jid)
            if job and job["status"] in {"completed", "failed", "cancelled"} and not batch:
                yield f"data: {json.dumps({'type': 'terminal', 'status': job['status']})}\n\n"
                break
            ticks += 1
            if ticks % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(.7)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/reports/{jid}")
async def report(request: Request, jid: str):
    job = get_job(request, jid, report=True)
    if not job["report"]:
        raise HTTPException(409, "The report is not ready yet.")
    return job["report"]


@router.get("/jobs/{jid}/evidence/{filename}")
async def evidence(request: Request, jid: str, filename: str):
    get_job(request, jid)
    directory = request.app.state.settings.data_dir / "jobs" / jid
    path = evidence_file(directory, filename)
    if not path:
        raise HTTPException(404, "Evidence not found.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.get("/reports/{jid}/export/{format}")
async def export(request: Request, jid: str, format: str):
    job = get_job(request, jid, report=True)
    result = job["report"]
    if not result:
        raise HTTPException(409, "The report is not ready yet.")
    directory = request.app.state.settings.data_dir / "jobs" / jid
    if format == "json":
        body, content_type = json.dumps(result, indent=2, ensure_ascii=False), "application/json"
    elif format == "html":
        body, content_type = await asyncio.to_thread(render_html, result, directory), "text/html"
    elif format == "csv":
        # UTF-8 BOM so Excel on Windows detects Unicode correctly.
        body, content_type = "\ufeff" + render_csv(result), "text/csv; charset=utf-8"
    elif format == "xlsx":
        from app.ai.registry import ModelStore, load_catalog
        stored = ModelStore(request.app.state.settings.data_dir).read()
        ctx = {"catalog": [{**m.model_dump(), "id": m.id} for m in load_catalog().models], "tests": stored.get("tests") or {}}
        body, content_type = render_xlsx(result, ctx), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format == "pdf":
        body, content_type = await asyncio.to_thread(render_pdf, result, directory), "application/pdf"
    else:
        raise HTTPException(400, "Choose html, pdf, json, csv or xlsx.")
    return Response(content=body, media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="website-report-{jid[:8]}.{format}"', "X-Content-Type-Options": "nosniff"})


@router.get("/tools")
async def tools_status(request: Request):
    import shutil
    import httpx
    settings = request.app.state.settings
    from app.ai.client import OPEN_MODELS
    models = []
    ollama_ok = False
    zap_version = None
    async def ollama():
        nonlocal models, ollama_ok
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                result = await client.get(settings.ollama_url.rstrip('/') + '/api/tags')
                result.raise_for_status()
                payload = result.json()
                if not isinstance(payload, dict) or not isinstance(payload.get('models', []), list):
                    return
                models = [item['name'] for item in payload['models']
                          if isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'].strip()]
                ollama_ok = True
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            pass
    async def zap():
        nonlocal zap_version
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                result = await client.get(settings.zap_url.rstrip('/') + '/JSON/core/view/version/', params={'apikey': settings.zap_api_key})
                result.raise_for_status()
                payload = result.json()
                if isinstance(payload, dict) and isinstance(payload.get('version'), (str, int, float)):
                    zap_version = str(payload['version'])
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            pass
    await asyncio.gather(ollama(), zap())
    items = [
        {'name': 'Ollama text model', 'available': settings.ai_enabled and settings.text_model in models and settings.text_model in OPEN_MODELS, 'detail': settings.text_model, 'license': OPEN_MODELS.get(settings.text_model, 'Unreviewed model (refused)')},
        {'name': 'Ollama vision model', 'available': settings.ai_enabled and settings.vision_model in models and settings.vision_model in OPEN_MODELS, 'detail': settings.vision_model, 'license': OPEN_MODELS.get(settings.vision_model, 'Unreviewed model (refused)')},
        {'name': 'OWASP ZAP', 'available': bool(zap_version), 'detail': zap_version or 'API unavailable', 'license': 'Apache-2.0'},
        {'name': 'Nuclei', 'available': bool(shutil.which(settings.nuclei_bin)), 'detail': 'Curated GET-only templates', 'license': 'MIT'},
    ]
    for name, directory, license in [('Lighthouse', 'lighthouse', 'Apache-2.0'), ('axe-core', 'axe-core', 'MPL-2.0'), ('Pa11y', 'pa11y', 'LGPL-3.0')]:
        items.append({'name': name, 'available': (settings.tools_dir/'node_modules'/directory).is_dir(), 'detail': 'Local scanner package', 'license': license})
    items.append({'name': 'Locust', 'available': settings.load_enabled, 'detail': f'{settings.max_users} users / {settings.load_seconds}s configured', 'license': 'MIT'})
    return {'tools': items, 'ready': all(item['available'] for item in items), 'ollama_reachable': ollama_ok}
