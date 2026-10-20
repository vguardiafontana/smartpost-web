import asyncio


import json


import logging


import threading


from datetime import date, datetime, timezone


from types import SimpleNamespace


from unittest.mock import AsyncMock


import pytest


from app.core.dates import BUSINESS_TZ, operation_date


from app.core.async_utils import ordered_map


def test_date_at_23_in_uruguay_and_selected_date(monkeypatch):
    import app.core.dates as dates
    late = datetime(2026, 10, 20, 2, 59, tzinfo=timezone.utc).astimezone(BUSINESS_TZ)
    monkeypatch.setattr(dates, 'business_now', lambda: late)
    assert operation_date() == date(2026, 10, 19)
    assert operation_date('2026-10-17') == date(2026, 10, 17)
    with pytest.raises(ValueError):
        operation_date('2026-02-30')


def test_selected_day_reaches_route_and_confirm_payload_after_midnight(tmp_path, monkeypatch):
    from app.cambio_estado_v2 import service as service
    from app.cambio_estado.service import ResolvedGuide
    from app.descarga import auth
    page = SimpleNamespace(goto=AsyncMock(return_value=SimpleNamespace(status=200)))
    context = SimpleNamespace(pages=[page], request=object(), close=AsyncMock())
    launcher = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context)))
    class Playwright:
        async def __aenter__(self): return launcher
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(service, 'async_playwright', Playwright)
    monkeypatch.setattr(service, 'resolve_path', lambda cfg, key: tmp_path / key)
    monkeypatch.setattr(service, 'epresis_settings', lambda cfg: {'base_url': 'https://epresis.test', 'max_concurrent_requests': 3})
    monkeypatch.setattr(auth, 'ensure_authenticated', AsyncMock())
    monkeypatch.setattr(auth, 'extract_csrf_token', AsyncMock(return_value='token'))
    monkeypatch.setattr(service, '_resolve_one', AsyncMock(return_value=ResolvedGuide('12345', retiro_id=12345)))
    monkeypatch.setattr(service, '_extract_distributor_from_guide_show', AsyncMock(return_value={'id': '10'}))
    monkeypatch.setattr(service, '_filter_guide', AsyncMock(return_value={}))
    monkeypatch.setattr(service, '_load_planilla_rows', AsyncMock(return_value=[{'retiro_id': 12345, 'rendido': 'SI'}]))
    monkeypatch.setattr(service, '_enable_rendition', AsyncMock(return_value=7))
    monkeypatch.setattr(service, 'business_now', lambda: datetime(2026, 10, 20, 0, 5, tzinfo=BUSINESS_TZ))
    requests = []
    async def post(ctx, url, payload, *args):
        requests.append((url, payload))
        return {'rows': [{'id': 501}]} if url.endswith('list-route-json') else {'status': 'ok'}
    monkeypatch.setattr(service, '_post_form', post)
    rows = asyncio.run(service.change_state_v2({}, ['12345'], 70, logging.getLogger('v295'), selected_date='2026-10-19'))
    assert rows[0]['change_status'] == 'ok'
    assert rows[0]['selected_date'] == '2026-10-19'
    assert requests[0][1]['fecha_recorrido'] == '19/10/2026 - 19/10/2026'
    assert requests[-1][1]['receptor_fecha_hora'] == '19/10/2026'
    assert requests[-1][1]['receptor_fecha_hora_hora'] == '00:05'


def test_read_concurrency_is_bounded_and_results_keep_order_and_errors():
    async def run():
        active = peak = 0
        async def read(value):
            nonlocal active, peak
            active += 1; peak = max(active, peak)
            await asyncio.sleep((6-value) / 1000)
            active -= 1
            if value == 3: raise ValueError('single failure')
            return value
        rows = await ordered_map(range(6), read)
        assert rows[:3] == [0, 1, 2]
        assert isinstance(rows[3], ValueError)
        assert rows[4:] == [4, 5]
        assert peak == 3
    asyncio.run(run())


def test_guide_cache_is_per_run_and_does_not_leak_mutable_results():
    from app.cambio_estado.service import _filter_guide
    from app.descarga.epresis_api import EpresisAPI
    async def run():
        response = SimpleNamespace(status=200, ok=True, json=AsyncMock(return_value={'rows': [{'id': 12345, 'estado': 'fresh'}]}))
        request = SimpleNamespace(post=AsyncMock(return_value=response))
        settings = {'base_url': 'https://epresis.test', 'filter_path': '/filter', 'request_timeout_ms': 1000}
        api = EpresisAPI(request, settings, 'token', logging.getLogger('test'))
        first = await _filter_guide(api, '12345'); first['estado'] = 'changed locally'
        assert (await _filter_guide(api, '12345'))['estado'] == 'fresh'
        assert request.post.await_count == 1
        await _filter_guide(EpresisAPI(request, settings, 'token', logging.getLogger('test')), '12345')
        assert request.post.await_count == 2
    asyncio.run(run())


def test_linux_does_not_download_excel_requiring_windows_com(monkeypatch):
    from app.busqueda_guias import service
    monkeypatch.setattr(service, 'sys', SimpleNamespace(platform='linux'))
    # Neither page nor request is accessed on Linux.
    assert asyncio.run(service._download_distributor_excel_index(None, None, {}, logging.getLogger('test'))) == {}


def test_job_retry_preserves_selected_date_and_cache_avoids_reads(tmp_path, monkeypatch):
    from app.web import jobs
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(jobs, 'resolve_path', lambda cfg, key: tmp_path)
    manager = jobs.JobManager()
    job = manager.create_job(['12345'], 70, selected_date='2026-10-19')
    job['status'] = 'failed'; manager._save(job)
    retry = manager.retry_failed(job['id'])
    assert retry['selected_date'] == '2026-10-19'
    assert retry['retry_of'] == job['id']
    monkeypatch.setattr(manager._store, 'get', lambda jid: (_ for _ in ()).throw(AssertionError('unnecessary database read')))
    copy = manager.get_job(retry['id']); copy['identifiers'].append('bad')
    assert manager.get_job(retry['id'])['identifiers'] == ['12345']


def test_web_preview_confirmation_and_invalid_date():
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    from app.web.security import WebSecuritySettings
    class Manager:
        operation_lock = threading.Lock()
        def start(self): pass
        def stop(self): pass
        def create_job(self, ids, state, **kwargs): return {'id': 'test', **kwargs}
    app = create_app(security=WebSecuritySettings(pin='1234', session_secret='x'*64), manager=Manager(), preview_runner=lambda ids, sid: [])
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/api/auth/login', json={'pin': '1234'}).status_code == 200
        assert client.post('/api/preview', json={'text': '12345', 'state_id': 70, 'date': '2026-02-30'}).status_code == 400
        preview = client.post('/api/preview', json={'text': '12345', 'state_id': 70, 'date': '2026-10-19'}).json()
        assert preview['selected_date'] == '2026-10-19'
        assert client.post('/api/jobs', json={'preview_id': preview['preview_id']}).json()['selected_date'] == '2026-10-19'
        assert client.post('/api/jobs', json={'preview_id': preview['preview_id']}).status_code == 409
