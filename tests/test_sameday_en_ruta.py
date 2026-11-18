from datetime import datetime
import csv
import logging
from unittest.mock import Mock
import pytest
from openpyxl import load_workbook
from app.descarga.epresis_api import EpresisAPI
from app.visitas.filtering import filter_sameday_rows
from app.procesamiento.rules import EXPECTED_HEADERS


def test_route_query_downloads_all_services_for_state_and_date():
    api = EpresisAPI(Mock(), {'base_url': 'https://example.test'}, 'csrf', Mock(), referer='https://example.test')
    for export in (False, True):
        pairs = api.make_visits_payload('19/10/2026', [70], export)
        assert dict(pairs)['fecha_ingreso_planta'] == '19/10/2026 - 19/10/2026'
        assert dict(pairs)['servicio_id'] == ''
        assert [v for k, v in pairs if k == 'estados_id[]'] == ['70']


def test_filter_only_service_column_without_changing_values():
    headers = ['Nro Guia', 'Servicio', 'Remito']
    rows = [['001', 'SAMEDAY', '0001'], ['002', 'Same Day', '0002'],
            ['003', 'EXPRESS', 'SAMEDAY'], ['004', 'SDD', '0004'], ['005', '', '0005']]
    assert filter_sameday_rows(headers, rows) == [rows[0], rows[1], rows[3]]
    with pytest.raises(RuntimeError):
        filter_sameday_rows(['Servicio', 'Servicio'], [['SAMEDAY', 'EXPRESS']])


def test_portable_report_writes_only_sameday_rows(tmp_path, monkeypatch):
    from app.visitas import portable_excel as mod
    from app.core.models import RunContext
    csv_path = tmp_path / 'global.csv'
    rows = []
    for service, guide in [('SAMEDAY', '000001'), ('EXPRESS', '000002'), ('same day', '000003')]:
        row = [''] * len(EXPECTED_HEADERS)
        row[EXPECTED_HEADERS.index('Servicio')] = service
        row[EXPECTED_HEADERS.index('Nro Guia')] = guide
        rows.append(row)
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer=csv.writer(f, delimiter=';'); writer.writerow(EXPECTED_HEADERS); writer.writerows(rows)
    monkeypatch.setattr(mod, 'resolve_path', lambda cfg, key: tmp_path)
    run=RunContext('test', datetime(2026, 10, 19), tmp_path)
    result=mod.convert_visits_csv_to_xlsx_portable({}, run, csv_path, logging.getLogger('test'), sameday_only=True)
    ws=load_workbook(result['path'])['VISITAS']
    assert result['rows'] == 2
    assert [ws.cell(row, 1).value for row in (2, 3)] == ['000001', '000003']
    assert [ws.cell(row, 9).value for row in (2, 3)] == ['SAMEDAY', 'same day']
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer=csv.writer(f, delimiter=';'); writer.writerow(EXPECTED_HEADERS); writer.writerow(rows[1])
    result=mod.convert_visits_csv_to_xlsx_portable({}, run, csv_path, logging.getLogger('test'), sameday_only=True)
    assert result['status'] == 'no_data' and result['rows'] == 0


@pytest.mark.parametrize('hour', [0, 12, 22, 23])
def test_web_report_adds_today_route_at_any_hour(tmp_path, monkeypatch, hour):
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
    def convert(cfg, run, path, logger, sameday_only=False):
        assert sameday_only
        dest = tmp_path / 'SAMEDAY EN RUTA.xlsx'
        dest.write_bytes(b'fake spreadsheet')
        return {'status': 'generated', 'path': str(dest)}
    monkeypatch.setattr(web, 'download_all', download_all)
    monkeypatch.setattr(web, 'download_visits', download_visits)
    monkeypatch.setattr(web, '_process_batch_portable', lambda *args: {'reports': {}})
    monkeypatch.setattr(web, 'convert_visits_csv_to_xlsx_portable', convert)
    result = web.generate_reports_and_visits(datetime(2026, 10, 18), requested_at=datetime(2026, 10, 19, hour))
    routes = [a for a in result['artifacts'] if a['kind'] == 'en_ruta_sameday']
    assert len(routes) == 1
    assert seen[0] == ('18/10/2026', False)
    assert seen[1] == ('19/10/2026', True)
    bundle = next(a for a in result['artifacts'] if a['kind'] == 'all')
    with zipfile.ZipFile(bundle['path']) as zf:
        assert routes[0]['filename'] in zf.namelist()
