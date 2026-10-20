from __future__ import annotations

import threading
import os

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


def test_search_guides_requires_auth_and_returns_desktop_fields():
    captured = []
    def runner(ids):
        captured.extend(ids)
        return [
            {
                "entrada": "6249087", "guia": "6249087", "guia_agente": "2000015",
                "remito": "48187020855", "cliente": "FARMACIA SELMA", "servicio": "FLEX",
                "destinatario": "Persona", "domicilio": "Calle 123", "localidad": "CABA",
                "provincia": "Buenos Aires", "codigo_postal": "1000", "telefono": "111111",
                "estado": "RC - EN RUTA PARA SU ENTREGA", "distribuidor_nombre": "CHOFER, NOMBRE",
                "distribuidor_dni": "12345678", "distribuidor_telefono": "222222",
                "show_url": "https://smartpostecommerce.epresis.com/guias/editar-guia-v2/show/6249087",
                "distribuidor_url": "https://smartpostecommerce.epresis.com/distribuidores/show/1",
            },
            {"entrada": "48111111111", "error": "No encontrado"},
        ]

    app = create_app(
        security=WebSecuritySettings(pin="246810", session_secret="x"*64),
        manager=FakeManager(),
        preview_runner=lambda ids, sid: [],
        search_runner=runner,
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/search-guides", json={"text": "6249087"}).status_code == 401
        assert client.post("/api/auth/login", json={"pin": "246810"}).status_code == 200
        r = client.post("/api/search-guides", json={"text": "6249087\n48111111111"})
        assert r.status_code == 200
        data = r.json()
        assert captured == ["6249087", "48111111111"]
        assert data["found"] == 1
        assert data["errors"] == 1
        assert data["rows"][0]["remito"] == "48187020855"
        assert data["rows"][0]["distribuidor_dni"] == "12345678"


def test_mobile_shell_exposes_home_and_search_module_without_removing_v2():
    html = open("app/web/static/index.html", encoding="utf-8").read()
    js = open("app/web/static/app.js", encoding="utf-8").read()
    assert "Cambio de estado v2" in html
    assert "Búsqueda de guías" in html
    assert 'id="searchInput"' in html
    assert "/api/search-guides" in js
    assert "/api/jobs/start" in js
    assert "/api/jobs" in js


def test_busqueda_photo_detection_and_sort_ui():
    from app.busqueda_guias.service import _photo_from_payload

    assert _photo_from_payload({"foto": "https://cdn.example/foto.jpg"}) is True
    assert _photo_from_payload({"evidencias": [{"url": "archivo.png"}]}) is True
    assert _photo_from_payload({"foto": "No"}) is False
    assert _photo_from_payload({"distribuidor": {"foto": "avatar.jpg"}}) is False

    html = open("app/web/static/index.html", encoding="utf-8").read()
    js = open("app/web/static/app.js", encoding="utf-8").read()
    assert 'id="searchPhotoSort"' in html
    assert "['Foto',r.foto||'No']" in js
    assert "searchPhotoSortMode=0" in js
    assert "Foto · Sí primero" in js
    assert "Foto · No primero" in js
