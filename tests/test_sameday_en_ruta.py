from datetime import datetime
from unittest.mock import Mock
import pytest

from app.descarga.epresis_api import EpresisAPI
from app.visitas.service import _route_payload, _sameday_service_id


def test_sameday_selector_requires_one_unambiguous_service():
    assert _sameday_service_id([{'value': '4', 'text': 'Same Day'}, {'value': '9', 'text': 'Otro'}]) == '4'
    with pytest.raises(RuntimeError):
        _sameday_service_id([{'value': '4', 'text': 'Sameday'}, {'value': '5', 'text': 'Same day'}])
    with pytest.raises(RuntimeError):
        _sameday_service_id([])


def test_route_filter_and_export_use_same_date_service_and_state():
    api = EpresisAPI(Mock(), {'base_url': 'https://example.test'}, 'csrf', Mock(), referer='https://example.test')
    for export in (False, True):
        pairs = _route_payload(api, '19/10/2026', '4', export)
        assert dict(pairs)['fecha_ingreso_planta'] == '19/10/2026 - 19/10/2026'
        assert dict(pairs)['servicio_id'] == '4'
        assert [v for k, v in pairs if k == 'estados_id[]'] == ['70']
        assert dict(pairs)['cliente_id'] == ''


@pytest.mark.parametrize('hour,expected', [(22, False), (23, True), (0, False)])
def test_web_report_only_adds_today_route_at_23(tmp_path, monkeypatch, hour, expected):
    from types import SimpleNamespace
    import zipfile
    from app.reportes import web_service as web
    monkeypatch.setattr(web, 'load_config', lambda: {'visitas': {'enabled': True}, 'whatsapp': {}})
    monkeypatch.setattr(web, 'resolve_path', lambda cfg, key: tmp_path / key)
    async def download_all(*args, **kwargs): return {}
    seen = []
    async def download_visits(cfg, run, logger, **kwargs):
        seen.append((run.date_slash, kwargs.get('en_ruta_sameday', False)))
        return SimpleNamespace(status='downloaded' if kwargs.get('en_ruta_sameday') else 'no_data', local_file='raw.csv', error=None)
    def convert(cfg, run, path, logger):
        dest = tmp_path / 'SAMEDAY EN RUTA.xlsx'
        dest.write_bytes(b'fake spreadsheet')
        return {'path': str(dest)}
    monkeypatch.setattr(web, 'download_all', download_all)
    monkeypatch.setattr(web, 'download_visits', download_visits)
    monkeypatch.setattr(web, '_process_batch_portable', lambda *args: {'reports': {}})
    monkeypatch.setattr(web, 'convert_visits_csv_to_xlsx_portable', convert)
    result = web.generate_reports_and_visits(datetime(2026, 10, 18), requested_at=datetime(2026, 10, 19, hour))
    routes = [a for a in result['artifacts'] if a['kind'] == 'en_ruta_sameday']
    assert bool(routes) is expected
    assert seen[0] == ('18/10/2026', False)
    if expected:
        assert seen[1] == ('19/10/2026', True)
        bundle = next(a for a in result['artifacts'] if a['kind'] == 'all')
        with zipfile.ZipFile(bundle['path']) as zf:
            assert routes[0]['filename'] in zf.namelist()
