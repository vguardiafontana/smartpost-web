import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.visitas import fotos
from app.delivery import chat_archive, unarchive_all
from app.cambio_estado_v2 import service
from app.reportes.excel_report import _cap_row_heights


@pytest.mark.parametrize('state,photos,expected', [(127, 0, 'No'), (127, 1, 'Sí'), (119, 1, 'No'), (119, 2, 'Sí'), (183, 1, 'No'), (183, 2, 'No'), (183, 3, 'Sí')])
def test_each_visit_requires_its_own_photo(monkeypatch, state, photos, expected):
    page = SimpleNamespace(url='https://epresis.test/guias/editar-guia-v2/show/12345', goto=AsyncMock(return_value=SimpleNamespace(ok=True)))
    monkeypatch.setattr(fotos, '_scrape_labeled_values', AsyncMock(return_value={'Estado': 'VISITA'}))
    monkeypatch.setattr(fotos, 'photo_count_from_guide_page', AsyncMock(return_value=photos))
    result = asyncio.run(fotos.inspect_visit(page, {'id': 12345, 'estado': {'id': state}, 'foto': '/old.jpg'} if photos else {'id': 12345, 'estado': {'id': state}}, {'base_url': 'https://epresis.test', 'request_timeout_ms': 1000}))
    assert result['foto'] == expected
    assert result['fotos_requeridas'] == {127: 1, 119: 2, 183: 3}[state]
    assert result['fotos_pendientes'] == max(0, result['fotos_requeridas'] - photos)


@pytest.mark.parametrize('text,count', [('2° VISITA', 2), ('3era visita', 3), ('SEGUNDA VISITA', 2), ('3RVT - 3° VISITA', 3), ('REPROGRAMACIÓN', 1), ('4ª VISITA', 4)])
def test_visit_ordinal_variants(text, count):
    assert fotos.required_visit_photos({'estado': text}) == count


def test_photo_metadata_thumbnails_and_flags_do_not_count_as_extra_visits():
    assert fotos.photo_count_from_payload({'fotos': [{'id': 1, 'url': '/photo.jpg', 'thumbnail': '/thumb.jpg'}, {'url': '/photo.jpg?w=120'}], 'tiene_foto': True, 'distribuidor': {'foto': '/avatar.jpg'}}) == 1
    assert fotos.photo_count_from_payload({'fotos': ['/proof?id=1', '/proof?id=2']}) == 2
    assert fotos.photo_count_from_payload({'fotos': ['/no-image.png', '/logo.jpg'], 'foto': False}) == 0


def test_missing_second_photo_cannot_be_classified_from_old_payload_flag(monkeypatch):
    page = SimpleNamespace(goto=AsyncMock(side_effect=TimeoutError))
    result = asyncio.run(fotos.inspect_visit(page, {'id': 12345, 'estado_id': 119, 'foto': True}, {'base_url': 'https://epresis.test', 'request_timeout_ms': 100}))
    assert result['foto'] == 'Sin verificar'


@pytest.mark.parametrize('count,expected', [(4, 'unarchive'), (0, 'archive')])
def test_one_button_uses_new_archived_flow_or_archives_when_empty(monkeypatch, count, expected):
    page = SimpleNamespace(is_closed=lambda: False)
    context = SimpleNamespace(pages=[page])
    monkeypatch.setattr(chat_archive, '_open_home', AsyncMock())
    monkeypatch.setattr(chat_archive, '_find_archived_entry', AsyncMock(return_value=object()))
    action = AsyncMock(return_value={'mode': 'unarchive', 'count': count})
    archive = AsyncMock(return_value={'mode': 'archive', 'count': 8})
    monkeypatch.setattr(unarchive_all, 'unarchive_all', action)
    monkeypatch.setattr(chat_archive, '_archive_from_company_list', archive)
    monkeypatch.setattr(chat_archive, '_unarchive_from_archived', AsyncMock(side_effect=AssertionError('legacy path')))
    decision = {}
    result = asyncio.run(chat_archive._toggle_once(context, {}, logging.getLogger(), decision=decision))
    assert result['mode'] == expected
    assert decision['mode'] == expected
    assert archive.await_count == (count == 0)


def test_recovering_after_partial_unarchive_never_switches_to_archive(monkeypatch):
    page = SimpleNamespace(is_closed=lambda: False)
    context = SimpleNamespace(pages=[page])
    monkeypatch.setattr(chat_archive, '_open_home', AsyncMock())
    monkeypatch.setattr(chat_archive, '_find_archived_entry', AsyncMock(return_value=object()))
    action = AsyncMock(side_effect=[RuntimeError('Target page, context or browser has been closed'), {'mode': 'unarchive', 'count': 0}])
    monkeypatch.setattr(unarchive_all, 'unarchive_all', action)
    monkeypatch.setattr(chat_archive, '_archive_from_company_list', AsyncMock(side_effect=AssertionError('must not reverse')))
    decision = {}
    with pytest.raises(RuntimeError):
        asyncio.run(chat_archive._toggle_once(context, {}, logging.getLogger(), decision=decision))
    assert decision['mode'] == 'unarchive'
    assert asyncio.run(chat_archive._toggle_once(context, {}, logging.getLogger(), decision=decision))['mode'] == 'unarchive'


def test_exact_distributor_profiles_are_looked_up_once_per_code(monkeypatch):
    items = [{'retiro_id': i} for i in range(40)]
    monkeypatch.setattr(service, '_filter_guide', AsyncMock(side_effect=lambda api, guide: {'distribuidor': {'codigo': '37424493APP', 'nombre': 'PRUEBA'}}))
    combo = AsyncMock(return_value={'id': '2510', 'code': '37424493APP'})
    monkeypatch.setattr(service, '_combo_distributor', combo)
    result = asyncio.run(service._prefetch_distributors(object(), object(), items, 'https://test', 'csrf', 'https://test', 1000))
    assert len(result) == 40
    assert combo.await_count == 1
    assert all(row[2]['id'] == '2510' for row in result)


class Sheet:
    def __init__(self, heights): self.heights = heights[:]; self.reads = self.writes = self.autofits = 0
    def Rows(self, spec):
        first, last = map(int, str(spec).split(':')) if ':' in str(spec) else (int(spec), int(spec))
        sheet = self
        class Range:
            def AutoFit(self): sheet.autofits += 1
            @property
            def RowHeight(self):
                sheet.reads += 1
                values = set(sheet.heights[first - 1:last])
                return next(iter(values)) if len(values) == 1 else None
            @RowHeight.setter
            def RowHeight(self, value):
                sheet.writes += 1
                sheet.heights[first - 1:last] = [value] * (last - first + 1)
        return Range()


@pytest.mark.parametrize('heights', [[15.0] * 1000, [80.0] * 1000, [15., 90., 40., 100., 60., 14.], [15., 90.] * 500])
def test_bulk_row_height_optimization_keeps_all_existing_heights(heights):
    sheet = Sheet(heights)
    _cap_row_heights(sheet, 1, len(heights), 60.)
    assert sheet.heights == [min(h, 60.) for h in heights]
    assert sheet.autofits == 1
    if len(set(heights)) == 1: assert sheet.reads == 1
    else: assert sheet.reads <= len(heights) + (len(heights) + 63) // 64 + 1


def test_desktop_modules_navigation_icon_and_silent_launch(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('SMARTPOST_DATA_DIR', str(tmp_path / 'data'))
    from PySide6.QtWidgets import QApplication, QPushButton
    from app.core.config import load_config, save_config
    from app.gui.main_window import MainWindow
    cfg = load_config(); cfg['app']['first_run_complete'] = True; save_config(cfg)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.show(); app.processEvents()
    assert not window.windowIcon().isNull()
    assert hasattr(window, 'cambio_estado_v2_page')
    assert not hasattr(window, 'cambio_estado_page')
    assert not any(button.text() == 'Cambio de estado' for button in window.findChildren(QPushButton))
    assert window.cambio_estado_v2_page.date_edit.calendarPopup()
    assert len(window.nav_buttons) == 6
    for name, button in window.nav_buttons.items():
        button.click(); app.processEvents()
        assert window.stack.currentWidget() is getattr(window, name)
        assert button.isChecked()
    called = []
    window._toggle_whatsapp_archive = called.append
    window.nav_buttons['home_page'].click()
    window.archive_toggle_btn.click()
    assert called == ['auto']
    assert not hasattr(window, 'unarchive_btn')
    window.close()
    assert 'console=False' in Path('packaging/SmartPost.spec').read_text()
    assert 'SmartPost.Desktop' in Path('desktop.py').read_text()
    assert 'pythonw.exe' in Path('ABRIR_SMARTPOST.vbs').read_text()


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_count_unique_images_in_gallery_instead_of_decorations():
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.set_content('''<img src="/logo.png" alt="logo"><div class="card">Fotos
              <a href="https://test/photo?id=1" data-fancybox><img src="https://test/thumb1.jpg"></a>
              <a href="https://test/photo?id=2" data-fancybox><img src="https://test/thumb2.jpg"></a>
              <img src="https://test/photo?id=2" alt="foto"><button>Cargar foto</button><img src="/no-image.png"></div>''')
            assert await fotos.photo_count_from_guide_page(page) == 2
            await browser.close()
    asyncio.run(run())
