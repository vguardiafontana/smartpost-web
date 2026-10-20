import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.web import jobs
from app.web.server import create_app
from app.web.security import WebSecuritySettings


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(jobs, 'resolve_path', lambda cfg, key: tmp_path / key)
    manager = jobs.JobManager()
    monkeypatch.setattr(manager, 'start', lambda: None)
    return manager


def app_for(manager):
    def preview(*args):
        raise AssertionError('Direct submission must not wait for Epresis preview')
    return create_app(security=WebSecuritySettings(pin='1234', session_secret='x'*64), manager=manager, preview_runner=preview)


def test_start_persists_and_queues_without_preview_or_confirmation(manager):
    body = {'text': '12345\n12345\n67890', 'state_id': 70, 'date': '2026-10-19', 'request_id': uuid4().hex}
    with TestClient(app_for(manager), base_url='https://testserver') as client:
        assert client.post('/api/jobs/start', json=body).status_code == 401
        client.post('/api/auth/login', json={'pin': '1234'})
        response = client.post('/api/jobs/start', json=body)
        assert response.status_code == 200
        job = response.json()
        assert job['id'] == body['request_id']
        assert job['identifiers'] == ['12345', '67890']
        assert job['selected_date'] == '2026-10-19'
        assert job['status'] == 'queued'
        assert manager._store.get(job['id']) == job
        assert manager._queue.qsize() == 1
        assert client.post('/api/jobs/start', json=body).json()['id'] == job['id']
        assert manager._queue.qsize() == 1
        assert client.post('/api/jobs/start', json={**body, 'state_id': 39}).status_code == 409


@pytest.mark.parametrize('patch,status', [
    ({'text': ''}, 400), ({'state_id': 999999}, 400),
    ({'date': '2026-02-30'}, 400), ({'request_id': 'invalid'}, 422),
    ({'text': '\n'.join(str(10000+i) for i in range(251))}, 400),
])
def test_invalid_batch_is_not_queued(manager, patch, status):
    body = {'text': '12345', 'state_id': 70, 'date': '2026-10-19', 'request_id': uuid4().hex, **patch}
    with TestClient(app_for(manager), base_url='https://testserver') as client:
        client.post('/api/auth/login', json={'pin': '1234'})
        assert client.post('/api/jobs/start', json=body).status_code == status
        assert manager._queue.empty()


def test_concurrent_retries_create_only_one_durable_job(manager):
    request_id = uuid4().hex
    def create(_):
        return manager.create_job(['12345'], 70, selected_date='2026-10-19', request_id=request_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(8)))
    assert {row['id'] for row in results} == {request_id}
    assert manager._queue.qsize() == 1
    manager._cache.clear()
    assert create(None)['id'] == request_id
    assert manager._queue.qsize() == 1


def test_idempotency_does_not_ignore_storage_failure(manager, monkeypatch):
    monkeypatch.setattr(manager._store, 'get', lambda _: (_ for _ in ()).throw(OSError('database unavailable')))
    with pytest.raises(OSError):
        manager.create_job(['12345'], 70, selected_date='2026-10-19', request_id=uuid4().hex)
    assert manager._queue.empty()


def test_worker_finishes_without_client_polling(tmp_path, monkeypatch):
    from app.cambio_estado_v2 import service
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(jobs, 'resolve_path', lambda cfg, key: tmp_path / key)
    manager = jobs.JobManager()
    started = threading.Event(); release = threading.Event()
    async def change(cfg, identifiers, state_id, logger, selected_date=None):
        assert selected_date == '2026-10-19'
        started.set()
        while not release.is_set(): await asyncio.sleep(0.01)
        return [{'input_value': identifiers[0], 'resolution_status': 'resolved', 'change_status': 'ok'}]
    monkeypatch.setattr(service, 'change_state_v2', change)
    with TestClient(app_for(manager), base_url='https://testserver') as client:
        client.post('/api/auth/login', json={'pin': '1234'})
        response = client.post('/api/jobs/start', json={'text': '12345', 'state_id': 70, 'date': '2026-10-19', 'request_id': uuid4().hex})
        assert response.status_code == 200
        assert started.wait(2)
        release.set()
        deadline = time.monotonic() + 3
        # No further client request: work completes in the server thread.
        while time.monotonic() < deadline:
            job = manager.get_job(response.json()['id'])
            if job['status'] == 'completed': break
            time.sleep(0.01)
        assert job['status'] == 'completed'
        assert job['summary']['success'] == 1


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_phone_reopens_after_lost_response_without_duplicate(tmp_path):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page(viewport={'width': 390, 'height': 844})
            submissions = []; stored = {}; unexpected = []
            async def route(route):
                path = route.request.url.split('https://smartpost.test', 1)[-1]
                if path == '/':
                    await route.fulfill(body=Path('app/web/static/index.html').read_text(encoding='utf-8'), content_type='text/html'); return
                if path.startswith('/static/'):
                    file = Path('app/web/static') / path.rsplit('/', 1)[-1]
                    await route.fulfill(body=file.read_bytes(), content_type='text/css' if file.suffix == '.css' else 'application/javascript'); return
                data = {'authenticated': True} if path == '/api/session' else {'states': [{'id': 70, 'label': 'EN RUTA'}]}
                if path == '/api/jobs/start':
                    body = route.request.post_data_json; submissions.append(body)
                    stored.setdefault(body['request_id'], {'id': body['request_id'], 'status': 'completed', 'selected_date': body['date'], 'identifiers': ['12345'], 'results': [], 'summary': {}})
                    if len(submissions) == 1:
                        await route.abort(); return  # Server accepted it; response was lost.
                    data = stored[body['request_id']]
                elif path.startswith('/api/jobs/'):
                    data = stored[path.rsplit('/', 1)[-1]]
                elif path == '/api/preview':
                    unexpected.append(path)
                await route.fulfill(body=json.dumps(data), content_type='application/json')
            await page.route('**/*', route)
            await page.goto('https://smartpost.test/')
            await page.locator('#openV2Btn').click()
            await page.locator('#bulkInput').fill('12345')
            await page.locator('#stateDate').fill('2026-10-19')
            await page.locator('#startBtn').click()
            await page.get_by_role('heading', name='Envío pendiente', exact=True).wait_for()
            saved_id = await page.evaluate("localStorage.getItem('smartpost_last_job')")
            assert saved_id == submissions[0]['request_id']
            await page.reload()
            await page.get_by_role('heading', name='Terminado', exact=True).wait_for()
            assert len(submissions) == 2
            assert submissions[0] == submissions[1]
            assert len(stored) == 1
            assert not unexpected
            assert await page.locator('#confirmBtn').count() == 0
            assert await page.evaluate("localStorage.getItem('smartpost_pending_batch')") is None
            await page.screenshot(path=str(tmp_path / 'inicio-directo.png'), full_page=True)
            await browser.close()
    asyncio.run(run())
