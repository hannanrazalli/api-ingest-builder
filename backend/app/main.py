import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.cache.store import Store
from backend.llm.codex_cli import CodexCLI
from backend.models import Event, Job, Settings, SettingsUpdate
from backend.orchestrator.events import EventBus
from backend.settings import effective_settings, public_settings


def create_app(db_path=None, static_dir=None):
    app = FastAPI(title="API Ingest Builder", version="0.1.0")
    store = Store(db_path or os.getenv("DATABASE_PATH", "data/app.sqlite3"))
    app.state.store = store

    @app.middleware("http")
    async def local_api_boundary(request: Request, call_next):
        # Reject browser cross-origin mutations (including requests without CORS preflight).
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = str(request.base_url).rstrip("/")
            if origin and origin != expected:
                return JSONResponse({"detail": "Cross-origin write blocked"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValidationError)
    async def configuration_error(request, exc):
        return JSONResponse({"detail": "Invalid settings configuration"}, status_code=422)

    # FastAPI validation errors may include submitted input, including API keys.
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "phase": 1}

    @app.get("/api/providers/codex/status")
    async def codex_status():
        settings = effective_settings(store)
        return await CodexCLI(
            store.path.parent / "codex-cli.lock", settings.codex_timeout_seconds
        ).status()

    @app.get("/api/settings")
    def settings():
        return public_settings(effective_settings(store))

    @app.put("/api/settings")
    def update_settings(update: SettingsUpdate):
        value = store.settings().model_dump()
        value.update(update.model_dump(exclude_unset=True))
        value["onboarded"] = True
        value["demo_mode"] = False
        updated = Settings.model_validate(value)
        store.save_settings(updated)
        return public_settings(effective_settings(store))

    @app.post("/api/onboarding/demo")
    def demo():
        value = store.settings()
        value.onboarded = True
        value.demo_mode = True
        store.save_settings(value)
        return public_settings(effective_settings(store))

    @app.post("/api/jobs", status_code=201)
    def create_job():
        job = Job(id=str(uuid4()))
        store.save_job(job)
        settings = effective_settings(store)
        bus = EventBus(store, [settings.api_key.get_secret_value()])
        bus.emit(
            Event(
                job_id=job.id,
                agent="orchestrator",
                state="idle",
                task="Foundation ready; research pipeline arrives in Phase 2",
            )
        )
        return job

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str, request: Request, after: int = Query(default=0, ge=0)):
        if not store.job(job_id):
            raise HTTPException(404, "Job not found")
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor") from None
        return StreamingResponse(
            EventBus(store).stream(job_id, cursor),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    assets = Path(static_dir or os.getenv("STATIC_DIR", "frontend/out"))
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="frontend")
    return app


app = create_app()
