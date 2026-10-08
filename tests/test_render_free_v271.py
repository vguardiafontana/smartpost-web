from __future__ import annotations

from pathlib import Path


def test_render_files_exist_and_use_free_docker_web():
    docker = Path("Dockerfile").read_text(encoding="utf-8")
    render = Path("render.yaml").read_text(encoding="utf-8")
    assert "playwright install --with-deps chromium" in docker
    assert "plan: free" in render
    assert "runtime: docker" in render
    assert "healthCheckPath: /healthz" in render
    assert "DATABASE_URL" in render


def test_web_server_supports_render_port_without_breaking_local_defaults():
    text = Path("web_server.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT")' in text
    assert '"8787"' in text
    assert '"127.0.0.1"' in text


def test_web_requirements_include_postgres_but_not_desktop_deps():
    text = Path("requirements-web.txt").read_text(encoding="utf-8").lower()
    assert "psycopg" in text
    assert "pyside6" not in text
    assert "pywin32" not in text


def test_health_endpoint_is_public_and_minimal(monkeypatch):
    import os
    import threading
    os.environ.setdefault("SMARTPOST_WEB_PIN", "246810")
    os.environ.setdefault("SMARTPOST_WEB_SESSION_SECRET", "x" * 64)
    from fastapi.testclient import TestClient
    from app.web.security import WebSecuritySettings
    from app.web.server import create_app

    class FakeManager:
        def __init__(self):
            self.operation_lock = threading.Lock()
            self.storage_backend = "files"
        def start(self): pass
        def stop(self): pass
        def get_job(self, _): return None
        def create_job(self, *a, **k): raise AssertionError
        def retry_failed(self, *a, **k): raise AssertionError

    app = create_app(
        security=WebSecuritySettings(pin="246810", session_secret="x"*64),
        manager=FakeManager(),
        preview_runner=lambda ids, sid: [],
    )
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "storage": "files"}
