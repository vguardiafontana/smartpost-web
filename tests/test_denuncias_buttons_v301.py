from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def gui(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_downloads_button_opens_the_complete_folder_in_explorer(gui, tmp_path, monkeypatch):
    from app.gui import denuncias_page as module
    folder = tmp_path / 'Todos los PDF'
    monkeypatch.setattr(module, 'resolve_path', lambda *_: folder)
    opened = []
    monkeypatch.setattr(module.QDesktopServices, 'openUrl', lambda url: opened.append(url) or True)
    monkeypatch.setattr(module, 'DenunciasMessagesDialog', lambda *_: pytest.fail('No debe abrir los mensajes'))
    page = module.DenunciasPage()
    assert page.messages_btn.text() == 'Ver mensajes'
    assert page.downloads_btn.text() == 'Ver denuncias descargadas'
    page.downloads_btn.click()
    assert folder.is_dir()
    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == folder.resolve()
    page.close()


def test_messages_use_completed_complaint_even_after_preparing_another(gui, monkeypatch):
    from app.gui import denuncias_page as module
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *_: None)
    monkeypatch.setattr(module, 'downloaded_reports', lambda *_: pytest.fail('No debe elegir otro PDF'))
    captured = []
    monkeypatch.setattr(module, 'DenunciasMessagesDialog', lambda entry, *_: SimpleNamespace(exec=lambda: captured.append(entry)))
    page = module.DenunciasPage()
    summary = {'pdf': 'ACTUAL.pdf', 'send_whatsapp': False, 'denuncia': {'filename': 'ACTUAL.pdf', 'sellers': [{'seller': 'SELLER ACTUAL', 'message': 'Remito 00123'}]}}
    page._submit_finished(True, summary, '')
    # The saved snapshot must not depend on later edits to the inputs or result.
    summary['denuncia']['sellers'][0]['message'] = 'CAMBIADO'
    page.shipments = [{'seller': 'OTRO SELLER', 'remito': '99999'}]
    page._clear_all()
    page.messages_btn.click()
    assert captured[0]['filename'] == 'ACTUAL.pdf'
    assert captured[0]['sellers'] == [{'seller': 'SELLER ACTUAL', 'message': 'Remito 00123'}]
    page.close()


def test_messages_restore_latest_download_without_mixing_sellers(gui, tmp_path, monkeypatch):
    import os
    from app.denuncias.history import save_history
    from app.gui import denuncias_page as module
    old = tmp_path / 'ANTERIOR.pdf'; old.write_bytes(b'%PDF-test')
    save_history(old, [{'seller': 'ANTERIOR', 'remito': 'OLD'}], {})
    os.utime(old, (1, 1))
    current = tmp_path / 'ACTUAL.pdf'; current.write_bytes(b'%PDF-test')
    save_history(current, [{'seller': 'ACTUAL', 'remito': '00123'}], {})
    monkeypatch.setattr(module, 'resolve_path', lambda *_: tmp_path)
    captured = []
    monkeypatch.setattr(module, 'DenunciasMessagesDialog', lambda entry, *_: SimpleNamespace(exec=lambda: captured.append(entry)))
    page = module.DenunciasPage(); page.messages_btn.click()
    assert captured[0]['filename'] == 'ACTUAL.pdf'
    assert [seller['seller'] for seller in captured[0]['sellers']] == ['ACTUAL']
    assert '00123' in captured[0]['sellers'][0]['message']
    assert 'OLD' not in captured[0]['sellers'][0]['message']
    page.close()


def test_messages_dialog_copies_each_seller_without_a_pdf_picker(gui):
    from PySide6.QtWidgets import QListWidget
    from app.gui.denuncias_messages_dialog import DenunciasMessagesDialog
    dialog = DenunciasMessagesDialog({'filename': 'ACTUAL.pdf', 'sellers': [
        {'seller': 'UNO', 'message': 'Mensaje 00123'}, {'seller': 'DOS', 'message': 'Mensaje 00456'},
    ]})
    assert not dialog.findChildren(QListWidget)
    dialog.copy_btn.click(); assert gui.clipboard().text() == 'Mensaje 00123'
    dialog.sellers.setCurrentIndex(1)
    dialog.copy_btn.click(); assert gui.clipboard().text() == 'Mensaje 00456'
    dialog.close()


def test_pdf_messages_survive_a_later_whatsapp_failure(gui, tmp_path, monkeypatch):
    from app.gui import workers
    from app.denuncias import gba_form, whatsapp, service
    pdf = tmp_path / 'DENUNCIA_ACTUAL.pdf'; pdf.write_bytes(b'%PDF-test')
    monkeypatch.setattr(workers, 'load_config', lambda: {})
    monkeypatch.setattr(workers, 'resolve_path', lambda cfg, key: tmp_path / key)
    monkeypatch.setattr(service, 'save_driver_profile', lambda *_: None)
    monkeypatch.setattr(gba_form, 'submit_gba_denuncia', AsyncMock(return_value=pdf))
    monkeypatch.setattr(whatsapp, 'send_denuncia_pdf', AsyncMock(side_effect=RuntimeError('Error simulado de WhatsApp')))
    worker = workers.DenunciasSubmitWorker([{'seller': 'SELLER ACTUAL', 'remito': '00123'}], {}, {'date': '30/10/2026'}, 'Prueba local', False)
    results = []; worker.finished.connect(lambda *args: results.append(args))
    worker.run()
    ok, summary, detail = results[0]
    assert not ok
    assert 'Error simulado' in detail
    assert summary['denuncia']['filename'] == pdf.name
    assert '00123' in summary['denuncia']['sellers'][0]['message']
    assert pdf.with_suffix('.smartpost.json').exists()
