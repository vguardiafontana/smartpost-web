"""Integración con Epresis simulado local: no usa cuentas ni tráfico externo."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from playwright.async_api import async_playwright

from app.web import visit_photos as web


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_sixty_guides_with_three_browsers_no_images_downloaded(monkeypatch):
    image_downloads = []
    pages = []
    launches = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, body, mime='text/html'):
            data = body.encode()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path.endswith('.jpg'):
                image_downloads.append(self.path)
                self.send('unnecessary image bytes', 'image/jpeg')
            elif '/show/' in self.path:
                guide = self.path.rsplit('/', 1)[-1]
                image = f'<div class="card">Fotos<img src="/fotos/{guide}.jpg"></div>' if int(guide) % 2 else '<button>Cargar foto</button>'
                self.send(f'<table><tr><td>Estado</td><td>1RVT - 1° VISITA</td></tr><tr><td>Distribuidor</td><td>CHOFER DE PRUEBA</td></tr></table>{image}')
            else: self.send('<input name="_token" value="test">')
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            offset = int(form['offset'][0]); limit = int(form['limit'][0])
            assert form['estados_id[]'] == ['127', '119', '183', '117']
            pages.append(offset)
            # Payload pesado descartable: nunca debe retenerse por toda la consulta.
            rows = [{'id': 10000+i, 'cliente': {'empresa': 'PRUEBA'}, 'estado': {'nombre': '1° VISITA'}, 'unused_data': 'x'*65536} for i in range(offset, min(60, offset+limit))]
            self.send(json.dumps({'total': 60, 'rows': rows}), 'application/json')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    settings = {'base_url': base, 'filter_path': '/guias/filter', 'request_timeout_ms': 10000}
    monkeypatch.setattr(web, 'epresis_settings', lambda cfg: settings)
    async def authenticate(page, settings, logger): await page.goto(base)
    async def navigate(page, settings, logger): await page.goto(base); return base
    async def csrf(page): return 'test'
    monkeypatch.setattr(web, 'ensure_authenticated', authenticate)
    monkeypatch.setattr(web, 'navigate_to_guide_search', navigate)
    monkeypatch.setattr(web, 'extract_csrf_token', csrf)
    class LocalPlaywright:
        async def __aenter__(self):
            self.manager = async_playwright()
            self.driver = await self.manager.__aenter__()
            async def launch(**kwargs):
                assert all(not browser.is_connected() for browser in launches)
                browser = await self.driver.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], **kwargs)
                launches.append(browser)
                return browser
            return SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        async def __aexit__(self, *args): await self.manager.__aexit__(*args)
    monkeypatch.setattr(web, 'async_playwright', LocalPlaywright)
    try:
        result = asyncio.run(web.search_visit_photos_web({}, logging.getLogger(), date='2026-10-08'))
        assert result['total'] == 60 and result['unverified'] == 0
        assert sum(r['foto'] == 'Sí' for r in result['rows']) == 30
        assert sum(r['foto'] == 'No' for r in result['rows']) == 30
        assert len(launches) == 3
        assert all(not browser.is_connected() for browser in launches)
        assert image_downloads == []
        assert pages == [0, 50]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
