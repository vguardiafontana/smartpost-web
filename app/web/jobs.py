from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import threading
import traceback
import uuid
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.cambio_estado.states import STATE_BY_ID
from app.core.config import load_config, resolve_path
from app.core.logging import setup_logging
from app.core.dates import operation_date


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "success": sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "ok"),
        "already_assigned": sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "already_assigned"),
        "warnings": sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "warning"),
        "errors": sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "error"),
        "unresolved": sum(1 for r in rows if r.get("resolution_status") in {"unresolved", "error"}),
        "duplicates": sum(1 for r in rows if r.get("resolution_status") == "duplicate"),
    }


def failed_inputs(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        resolution = str(row.get("resolution_status") or "")
        change = str(row.get("change_status") or "")
        failed = resolution in {"unresolved", "error"} or (resolution == "resolved" and change == "error")
        if not failed:
            continue
        value = str(row.get("input_value") or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


class JobProgressHandler(logging.Handler):
    _resolve_re = re.compile(r"Resolviendo\s+(\d+)\/(\d+)", re.I)

    def __init__(self, callback: Callable[[str, int | None, int | None], None]):
        super().__init__(logging.INFO)
        self.callback = callback
        self._last_update = float("-inf")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            # A log line must not add two network round trips to Neon.
            now = time.monotonic()
            if now - self._last_update < 0.5:
                return
            self._last_update = now
            current = total = None
            m = self._resolve_re.search(message)
            if m:
                current, total = int(m.group(1)), int(m.group(2))
            self.callback(message, current, total)
        except Exception:
            pass


class _FileJobStore:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^a-fA-F0-9]", "", str(job_id))
        return self.jobs_dir / f"{safe}.json"

    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(self, job: dict[str, Any]) -> None:
        path = self._path(str(job["id"]))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def active(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self.jobs_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if job.get("status") in {"queued", "running"}:
                out.append(job)
        return out


class _PostgresJobStore:
    """Persistencia durable opcional para hosting efímero (Render + Neon)."""

    def __init__(self, database_url: str):
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # pragma: no cover - validación de despliegue
            raise RuntimeError("DATABASE_URL está configurado pero falta psycopg.") from exc
        self.psycopg = psycopg
        self.database_url = database_url
        self._init_schema()

    def _connect(self):
        return self.psycopg.connect(self.database_url, connect_timeout=10)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS smartpost_web_jobs (
                        id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM smartpost_web_jobs WHERE id = %s", (str(job_id),))
                row = cur.fetchone()
        if not row:
            return None
        payload = row[0]
        return dict(payload) if isinstance(payload, dict) else json.loads(payload)

    def save(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO smartpost_web_jobs (id, payload, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    (str(job["id"]), payload),
                )
            conn.commit()

    def active(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM smartpost_web_jobs
                    WHERE payload->>'status' IN ('queued', 'running')
                    """
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = row[0]
            out.append(dict(payload) if isinstance(payload, dict) else json.loads(payload))
        return out


class JobManager:
    """Cola secuencial de Cambio de estado v2 con persistencia local o Postgres."""

    def __init__(self, operation_lock: threading.Lock | None = None):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.RLock()
        self._cache = {}
        self.operation_lock = operation_lock or threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        database_url = (os.environ.get("DATABASE_URL") or "").strip()
        if database_url:
            self._store = _PostgresJobStore(database_url)
            self.storage_backend = "postgres"
        else:
            cfg = load_config()
            jobs_dir = resolve_path(cfg, "logs") / "web_jobs"
            self._store = _FileJobStore(jobs_dir)
            self.storage_backend = "files"
        self._recover_interrupted_jobs()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._worker, name="smartpost-web-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._queue.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)

    def create_job(self, identifiers: list[str], state_id: int, *, retry_of: str | None = None, selected_date=None) -> dict[str, Any]:
        state_id = int(state_id)
        if state_id not in STATE_BY_ID:
            raise ValueError(f"Estado no permitido: {state_id}")
        cleaned = [str(x).strip() for x in identifiers if str(x).strip()]
        if not cleaned:
            raise ValueError("No hay identificadores para procesar.")
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "identifiers": cleaned,
            "state_id": state_id,
            "selected_date": operation_date(selected_date).isoformat(),
            "state_label": STATE_BY_ID[state_id],
            "retry_of": retry_of,
            "progress": {"current": 0, "total": len(cleaned), "message": "En cola…"},
            "summary": None,
            "results": [],
            "error": "",
        }
        self._save(job)
        self._queue.put(job_id)
        return deepcopy(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            cached = self._cache.get(job_id)
            if cached and time.monotonic() - cached[0] < 2:
                return deepcopy(cached[1])
            try:
                job = self._store.get(job_id)
                if job:
                    self._remember(job)
                return job
            except Exception:
                return None

    def retry_failed(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        rows = list(job.get("results") or [])
        ids = failed_inputs(rows)
        if not ids and job.get("status") in {"failed", "interrupted"}:
            ids = [str(x) for x in job.get("identifiers") or []]
        if not ids:
            raise ValueError("Este trabajo no tiene errores para reintentar.")
        return self.create_job(ids, int(job["state_id"]), retry_of=job_id, selected_date=job.get("selected_date"))

    def update_progress(self, job_id: str, message: str, current: int | None = None, total: int | None = None) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        p = dict(job.get("progress") or {})
        p["message"] = str(message)[-500:]
        if current is not None:
            p["current"] = current
        if total is not None:
            p["total"] = total
        job["progress"] = p
        self._save(job)

    def _worker(self) -> None:
        while not self._stopping.is_set():
            job_id = self._queue.get()
            if job_id is None:
                break
            try:
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = _now()
        job["progress"] = {"current": 0, "total": len(job["identifiers"]), "message": "Iniciando…"}
        self._save(job)

        try:
            cfg = load_config()
            from app.cambio_estado_v2.service import change_state_v2

            with self.operation_lock:
                run_id = datetime.now().strftime("web_cambio_estado_v2_%Y%m%d_%H%M%S")
                handler = JobProgressHandler(lambda msg, cur, total: self.update_progress(job_id, msg, cur, total))
                logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
                rows = asyncio.run(
                    change_state_v2(
                        cfg,
                        list(job["identifiers"]),
                        int(job["state_id"]),
                        logger.getChild("WEB_CAMBIO_ESTADO_V2"),
                        selected_date=job.get("selected_date"),
                    )
                )
            job = self.get_job(job_id) or job
            job["status"] = "completed"
            job["results"] = list(rows or [])
            job["summary"] = summarize_results(job["results"])
            job["progress"] = {
                "current": len(job["identifiers"]),
                "total": len(job["identifiers"]),
                "message": "Terminado.",
            }
            job["finished_at"] = _now()
            self._save(job)
        except Exception:
            job = self.get_job(job_id) or job
            job["status"] = "failed"
            job["error"] = traceback.format_exc()
            job["progress"] = {
                **(job.get("progress") or {}),
                "message": "El proceso terminó con un error general.",
            }
            job["finished_at"] = _now()
            self._save(job)

    def _recover_interrupted_jobs(self) -> None:
        try:
            active = self._store.active()
        except Exception:
            active = []
        for job in active:
            job["status"] = "interrupted"
            job["finished_at"] = _now()
            job["error"] = "El servidor se reinició mientras el trabajo estaba activo. Podés reintentar el lote."
            job["progress"] = {**(job.get("progress") or {}), "message": "Interrumpido por reinicio del servidor."}
            self._save(job)

    def _save(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._store.save(job)
            self._remember(job)

    def _remember(self, job):
        self._cache.pop(job["id"], None)
        self._cache[job["id"]] = (time.monotonic(), deepcopy(job))
        if len(self._cache) > 128:
            self._cache.pop(next(iter(self._cache)))
