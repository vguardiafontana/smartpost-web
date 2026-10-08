from __future__ import annotations

import os
import threading

os.environ.setdefault("SMARTPOST_WEB_PIN", "246810")
os.environ.setdefault("SMARTPOST_WEB_SESSION_SECRET", "x" * 64)

from fastapi.testclient import TestClient

from app.web.jobs import failed_inputs, summarize_results
from app.web.security import WebSecuritySettings, create_session_token, validate_session_token
from app.web.server import create_app


def test_signed_session_expires_and_rejects_tampering():
    token = create_session_token("s" * 64, 60, now=1000)
    assert validate_session_token(token, "s" * 64, now=1059)
    assert not validate_session_token(token, "s" * 64, now=1061)
    assert not validate_session_token(token + "x", "s" * 64, now=1050)


def test_summary_and_retry_only_real_failures():
    rows = [
        {"input_value": "1", "resolution_status": "resolved", "change_status": "ok"},
        {"input_value": "2", "resolution_status": "resolved", "change_status": "already_assigned"},
        {"input_value": "3", "resolution_status": "resolved", "change_status": "warning"},
        {"input_value": "4", "resolution_status": "resolved", "change_status": "error"},
        {"input_value": "5", "resolution_status": "unresolved"},
        {"input_value": "6", "resolution_status": "duplicate"},
    ]
    assert summarize_results(rows) == {
        "success": 1, "already_assigned": 1, "warnings": 1,
        "errors": 1, "unresolved": 1, "duplicates": 1,
    }
    assert failed_inputs(rows) == ["4", "5"]


class FakeManager:
    def __init__(self):
        self.operation_lock = threading.Lock()
        self.jobs = {}
        self.started = False

    def start(self): self.started = True
    def stop(self): self.started = False

    def create_job(self, identifiers, state_id, retry_of=None):
        job = {
            "id": "job1", "status": "queued", "identifiers": list(identifiers),
            "state_id": int(state_id), "state_label": "RC - EN RUTA PARA SU ENTREGA",
            "progress": {"current": 0, "total": len(identifiers), "message": "En cola…"},
            "results": [], "summary": None, "error": "", "retry_of": retry_of,
        }
        self.jobs[job["id"]] = job
        return job

    def get_job(self, job_id): return self.jobs.get(job_id)
    def retry_failed(self, job_id):
        raise ValueError("Este trabajo no tiene errores para reintentar.")


def test_web_requires_pin_and_preview_before_confirm():
    manager = FakeManager()
    security = WebSecuritySettings(pin="246810", session_secret="z" * 64, session_ttl_seconds=3600)

    def preview_runner(ids, state_id):
        return [{
            "input_value": ids[0], "resolution_status": "resolved", "retiro_id": int(ids[0]),
            "detected_type": "Guía", "current_state_id": 70, "current_state": "RC - EN RUTA PARA SU ENTREGA",
        }]

    app = create_app(security=security, manager=manager, preview_runner=preview_runner)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/states").status_code == 401
        assert client.post("/api/auth/login", json={"pin": "bad"}).status_code == 401
        assert client.post("/api/auth/login", json={"pin": "246810"}).status_code == 200
        states = client.get("/api/states")
        assert states.status_code == 200
        assert any(x["id"] == 70 for x in states.json()["states"])

        preview = client.post("/api/preview", json={"text": "6249087", "state_id": 70})
        assert preview.status_code == 200
        body = preview.json()
        assert body["rows"][0]["already_assigned"] is True

        created = client.post("/api/jobs", json={"preview_id": body["preview_id"]})
        assert created.status_code == 200
        assert created.json()["identifiers"] == ["6249087"]
        # El preview se consume una sola vez para evitar confirmar dos veces por doble toque.
        assert client.post("/api/jobs", json={"preview_id": body["preview_id"]}).status_code == 409


def test_web_requirements_avoid_desktop_only_dependencies():
    text = open("requirements-web.txt", encoding="utf-8").read().lower()
    assert "fastapi" in text and "uvicorn" in text and "playwright" in text
    assert "pyside6" not in text
    assert "pywin32" not in text
