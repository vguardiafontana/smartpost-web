from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.cambio_estado.service import analyze_identifiers, extract_identifiers
from app.cambio_estado.states import STATES, STATE_BY_ID
from app.busqueda_guias.service import search_shipments
from app.core.config import load_config, resolve_path
from app.core.logging import setup_logging
from app.web.jobs import JobManager
from app.web.report_jobs import ReportJobManager
from app.web.visit_photo_jobs import VisitPhotoJobs
from app.web.security import (
    COOKIE_NAME,
    WebSecuritySettings,
    create_session_token,
    validate_session_token,
    verify_pin,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"


class LoginBody(BaseModel):
    pin: str = Field(min_length=1, max_length=64)


class PreviewBody(BaseModel):
    text: str = Field(default="", max_length=20000)
    state_id: int


class ConfirmBody(BaseModel):
    preview_id: str


class SearchGuidesBody(BaseModel):
    text: str = Field(default="", max_length=20000)


class ReportGenerateBody(BaseModel):
    date: str = Field(min_length=10, max_length=10)


def _search_guides_sync(operation_lock: threading.Lock, identifiers: list[str]) -> list[dict[str, Any]]:
    cfg = load_config()
    with operation_lock:
        run_id = time.strftime("web_busqueda_%Y%m%d_%H%M%S")
        logger = setup_logging(resolve_path(cfg, "logs"), run_id, False)
        rows = asyncio.run(search_shipments(cfg, identifiers, logger.getChild("WEB_BUSQUEDA_GUIAS")))
    return [dict(r) for r in rows]


def _same_state(row: dict[str, Any], state_id: int) -> bool:
    current_state_id = row.get("current_state_id")
    try:
        if current_state_id not in (None, "") and int(current_state_id) == int(state_id):
            return True
    except Exception:
        pass
    current = str(row.get("current_state") or "").strip().casefold()
    target = str(STATE_BY_ID[int(state_id)]).strip().casefold()
    return bool(current and current == target)


def _preview_sync(operation_lock: threading.Lock, identifiers: list[str], state_id: int) -> list[dict[str, Any]]:
    cfg = load_config()
    with operation_lock:
        run_id = time.strftime("web_preview_%Y%m%d_%H%M%S")
        logger = setup_logging(resolve_path(cfg, "logs"), run_id, False)
        rows = asyncio.run(analyze_identifiers(cfg, identifiers, logger.getChild("WEB_PREVIEW")))
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["already_assigned"] = item.get("resolution_status") == "resolved" and _same_state(item, state_id)
        out.append(item)
    return out


def create_app(
    *,
    security: WebSecuritySettings | None = None,
    manager: JobManager | None = None,
    preview_runner: Callable[[list[str], int], list[dict[str, Any]]] | None = None,
    search_runner: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    report_manager: ReportJobManager | None = None,
    visit_photo_manager: VisitPhotoJobs | None = None,
) -> FastAPI:
    security = security or WebSecuritySettings.from_env()
    operation_lock = manager.operation_lock if manager else threading.Lock()
    manager = manager or JobManager(operation_lock=operation_lock)
    preview_runner = preview_runner or (lambda ids, sid: _preview_sync(operation_lock, ids, sid))
    search_runner = search_runner or (lambda ids: _search_guides_sync(operation_lock, ids))
    report_manager = report_manager or ReportJobManager(operation_lock=operation_lock)
    visit_photo_manager = visit_photo_manager or VisitPhotoJobs(operation_lock)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()
        report_manager.start()
        try:
            yield
        finally:
            report_manager.stop()
            manager.stop()

    app = FastAPI(title="SmartPost Web", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.manager = manager
    app.state.security = security
    app.state.preview_runner = preview_runner
    app.state.search_runner = search_runner
    app.state.report_manager = report_manager
    app.state.visit_photo_manager = visit_photo_manager
    app.state.previews: dict[str, dict[str, Any]] = {}
    app.state.login_attempts: dict[str, deque[float]] = defaultdict(deque)

    def require_auth(session: str | None) -> None:
        if not validate_session_token(session, security.session_secret):
            raise HTTPException(status_code=401, detail="Sesión no válida")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        """Healthcheck público mínimo para Render/UptimeRobot; no expone secretos."""
        return {"ok": True, "storage": getattr(manager, "storage_backend", "custom")}

    @app.get("/api/session")
    async def session_status(smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, bool]:
        require_auth(smartpost_session)
        return {"authenticated": True}

    @app.post("/api/auth/login")
    async def login(body: LoginBody, request: Request, response: Response) -> dict[str, bool]:
        host = request.client.host if request.client else "unknown"
        now = time.time()
        attempts = app.state.login_attempts[host]
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá unos minutos.")
        if not verify_pin(body.pin, security.pin):
            attempts.append(now)
            raise HTTPException(status_code=401, detail="PIN incorrecto")
        attempts.clear()
        token = create_session_token(security.session_secret, security.session_ttl_seconds)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=security.session_ttl_seconds,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
        )
        return {"ok": True}

    @app.post("/api/auth/logout")
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/states")
    async def states(smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        return {"states": [{"id": sid, "label": label} for sid, label in STATES]}

    @app.post("/api/report-jobs")
    async def create_report_job(body: ReportGenerateBody, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        try:
            datetime.strptime(body.date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha inválida")
        return report_manager.create_job(body.date)

    @app.get("/api/report-jobs/{job_id}")
    async def get_report_job(job_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        job = report_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Generación no encontrada")
        public = dict(job)
        if public.get("error"):
            public["error"] = "La generación tuvo un error. Revisá el log del servidor o reintentá."
        return public

    @app.post("/api/report-jobs/{job_id}/retry")
    async def retry_report_job(job_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        try:
            return report_manager.retry(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Generación no encontrada")

    @app.get("/api/report-jobs/{job_id}/artifacts/{artifact_id}")
    async def download_report_artifact(job_id: str, artifact_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
        require_auth(smartpost_session)
        meta, data = report_manager.get_artifact(job_id, artifact_id)
        if not meta or data is None:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        filename = str(meta.get("filename") or "smartpost.xlsx").replace('"', "")
        return FastAPIResponse(content=data, media_type=str(meta.get("content_type") or "application/octet-stream"), headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.post("/api/visit-photo-jobs")
    async def create_visit_photo_job(smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        return visit_photo_manager.create()

    @app.get("/api/visit-photo-jobs/{job_id}")
    async def get_visit_photo_job(job_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        job = visit_photo_manager.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="La consulta venció o el servidor se reinició. Volvé a consultar.")
        return job

    @app.post("/api/search-guides")
    async def search_guides(body: SearchGuidesBody, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        identifiers = extract_identifiers(body.text)
        if not identifiers:
            raise HTTPException(status_code=400, detail="Pegá al menos una guía, remito o guía agente.")
        if len(identifiers) > 250:
            raise HTTPException(status_code=400, detail="Máximo 250 identificadores por búsqueda.")
        rows = await asyncio.to_thread(search_runner, identifiers)
        rows = [dict(r) for r in rows]
        found = sum(1 for r in rows if not r.get("error"))
        return {
            "count": len(identifiers),
            "found": found,
            "errors": len(rows) - found,
            "rows": rows,
        }

    @app.post("/api/preview")
    async def preview(body: PreviewBody, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        if int(body.state_id) not in STATE_BY_ID:
            raise HTTPException(status_code=400, detail="Estado inválido")
        identifiers = extract_identifiers(body.text)
        if not identifiers:
            raise HTTPException(status_code=400, detail="Pegá al menos una guía, remito o guía agente.")
        if len(identifiers) > 250:
            raise HTTPException(status_code=400, detail="Máximo 250 identificadores por lote.")
        rows = await asyncio.to_thread(preview_runner, identifiers, int(body.state_id))
        rows = [dict(r) for r in rows]
        for item in rows:
            item["already_assigned"] = item.get("resolution_status") == "resolved" and _same_state(item, int(body.state_id))
        preview_id = uuid.uuid4().hex
        app.state.previews[preview_id] = {
            "created_at": time.time(),
            "identifiers": identifiers,
            "state_id": int(body.state_id),
            "rows": rows,
        }
        # Purga previews viejas (30 min).
        cutoff = time.time() - 1800
        for key, value in list(app.state.previews.items()):
            if float(value.get("created_at") or 0) < cutoff:
                app.state.previews.pop(key, None)
        return {
            "preview_id": preview_id,
            "state_id": int(body.state_id),
            "state_label": STATE_BY_ID[int(body.state_id)],
            "count": len(identifiers),
            "rows": rows,
        }

    @app.post("/api/jobs")
    async def create_job(body: ConfirmBody, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        preview_data = app.state.previews.pop(body.preview_id, None)
        if not preview_data or time.time() - float(preview_data.get("created_at") or 0) > 1800:
            raise HTTPException(status_code=409, detail="La vista previa venció. Volvé a revisar el lote.")
        job = manager.create_job(preview_data["identifiers"], int(preview_data["state_id"]))
        return job

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        job = manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        # No exponemos traceback completo al navegador; queda en logs del servidor.
        public = dict(job)
        if public.get("error"):
            public["error"] = "El proceso tuvo un error general. Revisá el log del servidor o reintentá."
        return public

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str, smartpost_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
        require_auth(smartpost_session)
        try:
            return manager.retry_failed(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return app


app = create_app()
