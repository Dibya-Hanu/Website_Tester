"""Application entrypoint; one worker per deployment (ZAP is shared state)."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.models_routes import router as models_router
from app.core.config import Settings, get_settings
from app.core.policy import TargetPolicy
from app.core.store import Store
from app.pipeline.runner import JobWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None, *, run_worker: bool | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare()
    # Preserve the one-command native developer experience, while allowing the
    # Docker deployment to keep browser/scanner subprocesses outside the API.
    start_inline_worker = settings.worker_mode == "inline" if run_worker is None else run_worker
    store = Store(settings.db_path)
    worker = JobWorker(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        if start_inline_worker:
            await worker.start()
        try:
            yield
        finally:
            if start_inline_worker:
                await worker.stop()

    app = FastAPI(title="AI Universal Website Tester", version="1.0.0", lifespan=lifespan,
                  description="Authorized, non-destructive black-box website quality checks. MIT licensed; local open-source AI.")
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker
    app.state.policy = TargetPolicy(settings)
    app.state.submissions = {}

    @app.middleware("http")
    async def secure_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Embedding is left to the deployment reverse proxy; Arena's live preview
        # intentionally embeds this application on another origin.
        # No external resources or analytics. 'self' SSE/images work in the live app.
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    app.include_router(models_router)
    assets = settings.frontend_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint.")
        index = settings.frontend_dir / "index.html"
        if not index.is_file():
            return {"app": "AI Universal Website Tester", "message": "Backend ready. Run the frontend development server or build frontend/dist.", "docs": "/docs"}
        return FileResponse(index)
    return app


app = create_app()
