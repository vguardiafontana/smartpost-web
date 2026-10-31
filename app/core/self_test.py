"""Offline validation for the self-contained Windows installer."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import traceback
from pathlib import Path


def run_self_test(report_path: str) -> int:
    report = Path(report_path).resolve()
    result = {'ok': False, 'checks': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='smartpost-self-test-') as temporary:
            os.environ['SMARTPOST_DATA_DIR'] = temporary
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            from app.core.runtime_paths import configure_bundled_playwright, resource_path
            configure_bundled_playwright()
            from app.core.config import load_config, save_config, resolve_path
            from app.core.utils import sha256_file
            cfg = load_config()
            for key in ('prompt', 'template'):
                assert sha256_file(resolve_path(cfg, key)) == cfg['app'][key + '_sha256'], key
            result['checks']['resources'] = True
            cfg['app']['first_run_complete'] = True
            save_config(cfg)
            from PySide6.QtWidgets import QApplication
            from app.gui.main_window import MainWindow
            from app.delivery.unarchive_all import unarchive_all
            import pythoncom
            import win32com.client
            import keyring
            app = QApplication.instance() or QApplication([])
            window = MainWindow()
            app.processEvents()
            assert window.archive_toggle_btn.text() == 'Archivar / desarchivar'
            assert window.cambio_estado_v2_page.date_edit.calendarPopup()
            assert not hasattr(window, 'cambio_estado_page')
            assert window.stack.count() == 6
            assert window.denuncias_page.messages_btn.text() == 'Ver mensajes'
            assert window.denuncias_page.downloads_btn.text() == 'Ver denuncias descargadas'
            from app.gui.denuncias_messages_dialog import DenunciasMessagesDialog
            messages = DenunciasMessagesDialog({'filename': 'PRUEBA.pdf', 'sellers': [{'seller': 'PRUEBA', 'message': 'Mensaje de prueba'}]})
            assert messages.sellers.currentText() == 'PRUEBA'
            messages.close()
            assert not window.windowIcon().isNull()
            assert resource_path('assets/fonts/InterVariable.ttf').is_file()
            assert resource_path('assets/icons/home.svg').is_file()
            assert callable(unarchive_all)
            window.close()
            app.processEvents()
            result['checks']['desktop_modules'] = True
            result['checks']['qt_plugins'] = True
            from playwright.async_api import async_playwright
            async def browser_check():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    try:
                        page = await browser.new_page()
                        await page.route('**/*', lambda route: route.abort())
                        await page.set_content('<h1>SmartPost offline test</h1>')
                        assert await page.locator('h1').inner_text() == 'SmartPost offline test'
                    finally:
                        await browser.close()
            asyncio.run(browser_check())
            result['checks']['bundled_chromium'] = True
            result['ok'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
