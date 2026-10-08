import asyncio
import logging
import threading
from unittest.mock import AsyncMock

import pytest

from app.descarga.epresis_api import EpresisAPI
from app.visitas import fotos
from app.web.visit_photo_jobs import VisitPhotoJobs


def make_api(responses):
    api = EpresisAPI(None, {'base_url': 'https://example.test', 'filter_path': '/guias/filter'}, 'csrf', logging.getLogger())
    api._post_pairs = AsyncMock(side_effect=responses)
    return api


def test_all_pages_with_server_limit_and_exact_date_states():
    api = make_api([{'total': 3, 'rows': [{'id': 1}, {'id': 2}]}, {'total': 3, 'rows': [{'id': 3}]}])
    rows = asyncio.run(fotos.collect_visit_rows(api, '2026-10-08'))
    assert [r['id'] for r in rows] == [1, 2, 3]
    calls = api._post_pairs.call_args_list
    pairs = calls[0].args[1]
    assert [v for k, v in pairs if k == 'estados_id[]'] == ['127', '119', '183', '117']
    assert dict(pairs)['fecha_ingreso_planta'] == '08/10/2026 - 08/10/2026'
    assert dict(pairs)['cliente_id'] == ''
    assert dict(pairs)['fecha_ultimo_estado'] == ''
    assert dict(calls[1].args[1])['offset'] == '2'


def test_missing_total_fetches_until_empty():
    api = make_api([{'rows': [{'id': 1}]}, {'rows': [{'id': 2}]}, {'rows': []}])
    assert len(asyncio.run(fotos.collect_visit_rows(api, '2026-10-08'))) == 2


@pytest.mark.parametrize('response', [{'total': 0, 'rows': []}, {'rows': []}])
def test_empty_day(response):
    assert asyncio.run(fotos.collect_visit_rows(make_api([response]), '2026-10-08')) == []


@pytest.mark.parametrize('responses', [
    [{'message': 'unknown response'}],
    [{'total': 1, 'rows': []}],
    [{'total': 3, 'rows': [{'id': 1}]}, {'total': 3, 'rows': [{'id': 1}]}],
    [{'total': 4, 'rows': [{'id': 1}, {'id': 2}]}, {'total': 4, 'rows': [{'id': 2}, {'id': 3}]}],
    [{'total': 1, 'rows': [{'remito': '123'}]}],
])
def test_incomplete_results_are_not_reported_as_complete(responses):
    with pytest.raises(RuntimeError):
        asyncio.run(fotos.collect_visit_rows(make_api(responses), '2026-10-08'))


def test_today_uses_uruguay_date_at_utc_midnight(monkeypatch):
    from datetime import datetime, timezone
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(fotos, 'datetime', Clock)
    assert fotos.today_visits() == '2026-10-08'


@pytest.mark.parametrize('present,expected', [(True, 'Sí'), (False, 'No')])
def test_photo_from_successful_guide_page(monkeypatch, present, expected):
    url = 'https://example.test/guias/editar-guia-v2/show/12345'
    page = AsyncMock()
    page.url = url
    page.goto.return_value.ok = True
    monkeypatch.setattr(fotos, '_scrape_labeled_values', AsyncMock(return_value={'Estado': '1° VISITA'}))
    monkeypatch.setattr(fotos, 'photo_from_guide_page', AsyncMock(return_value=present))
    result = asyncio.run(fotos.inspect_visit(page, {'id': 12345}, {'base_url': 'https://example.test', 'request_timeout_ms': 1000}))
    assert result['foto'] == expected


def test_existing_payload_photo_avoids_extra_request():
    page = AsyncMock()
    result = asyncio.run(fotos.inspect_visit(page, {'id': 12345, 'foto': 'proof.jpg'}, {'base_url': 'https://example.test'}))
    assert result['foto'] == 'Sí'
    page.goto.assert_not_called()


@pytest.mark.parametrize('failure', ['timeout', 'login', 'http', 'empty', 'evaluate'])
def test_failed_photo_lookup_is_unknown_not_no(monkeypatch, failure):
    page = AsyncMock()
    page.url = 'https://example.test/guias/editar-guia-v2/show/12345'
    page.goto.return_value.ok = failure != 'http'
    if failure == 'login': page.url = 'https://example.test/login'
    if failure == 'timeout': page.goto.side_effect = TimeoutError
    monkeypatch.setattr(fotos, '_scrape_labeled_values', AsyncMock(return_value={} if failure == 'empty' else {'Estado': 'VISITA'}))
    monkeypatch.setattr(fotos, 'photo_from_guide_page', AsyncMock(side_effect=RuntimeError('failed')))
    result = asyncio.run(fotos.inspect_visit(page, {'id': 12345}, {'base_url': 'https://example.test', 'request_timeout_ms': 1000}))
    assert result['foto'] == 'Sin verificar'


def test_jobs_share_operation_lock_reuse_active_job_and_do_not_leak_errors():
    lock = threading.Lock()
    runner = lambda date, progress: {'rows': [{'guia': '1', 'foto': 'No'}], 'date': date}
    manager = VisitPhotoJobs(lock, runner)
    with lock:
        job = manager.create()
        assert manager.create()['id'] == job['id']
        assert manager.get(job['id'])['status'] == 'queued'
    # Call synchronously on a separate job to avoid test timing dependencies.
    manager.jobs['test'] = {'id': 'test', 'date': '2026-10-08'}
    manager._run('test')
    assert manager.get('test')['status'] == 'completed'
    snapshot = manager.get('test'); snapshot['rows'].clear()
    assert len(manager.get('test')['rows']) == 1
    manager.runner = lambda *a: (_ for _ in ()).throw(RuntimeError('private info'))
    manager._run('test')
    assert manager.get('test')['status'] == 'failed'
    assert 'private info' not in str(manager.get('test'))


def test_web_endpoints_require_pin_and_return_results():
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    from app.web.security import WebSecuritySettings
    from tests.test_web_busqueda_guias_v280 import FakeManager
    class Photos:
        def create(self): return {'id': 'abc', 'status': 'queued'}
        def get(self, job_id):
            return {'id': 'abc', 'status': 'completed', 'rows': [{'guia': '12345', 'foto': 'No'}]} if job_id == 'abc' else None
    app = create_app(security=WebSecuritySettings(pin='246810', session_secret='x'*64), manager=FakeManager(), visit_photo_manager=Photos())
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/api/visit-photo-jobs').status_code == 401
        assert client.get('/api/visit-photo-jobs/abc').status_code == 401
        client.post('/api/auth/login', json={'pin': '246810'})
        assert client.post('/api/visit-photo-jobs').json()['id'] == 'abc'
        assert client.get('/api/visit-photo-jobs/abc').json()['rows'][0]['foto'] == 'No'
        assert client.get('/api/visit-photo-jobs/missing').status_code == 404


def test_windows_filters_unknown_separately(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.gui.visitas_fotos_page import VisitasFotosPage
    app = QApplication.instance() or QApplication([])
    page = VisitasFotosPage()
    page._finished(True, {'date': '2026-10-08', 'total': 3, 'unverified': 1, 'rows': [
        {'guia': '12345', 'foto': 'Sí'}, {'guia': '12346', 'foto': 'No'}, {'guia': '12347', 'foto': 'Sin verificar'},
    ]})
    assert page.no_btn.isChecked()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == '12346'
    page.yes_btn.click()
    assert page.table.item(0, 0).text() == '12345'
    page.unknown_btn.click()
    assert page.table.item(0, 0).text() == '12347'
    page.close()
