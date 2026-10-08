from pathlib import Path


def test_default_whatsapp_retry_settings_present():
    text = Path('config.default.yaml').read_text(encoding='utf-8')
    assert 'search_result_timeout_ms: 15000' in text
    assert 'search_attempts: 2' in text
    assert 'pending_retry_pause_ms: 1800' in text


def test_delivery_has_pending_retry_pass_and_exact_guard():
    text = Path('app/delivery/whatsapp.py').read_text(encoding='utf-8')
    assert 'pending_retry' in text
    assert 'Reintentando %d envío(s) pendientes' in text
    assert 'already_sent' in text
    assert 'No envío.' in text


def test_pipeline_partial_success_instead_of_fatal_whatsapp():
    text = Path('app/pipeline/orchestrator.py').read_text(encoding='utf-8')
    assert 'partial_success' in text
    assert 'whatsapp_pending' in text
    assert 'raise RuntimeError("WhatsApp terminó con errores/bloqueos:' not in text


def test_gui_warns_pending_without_marking_full_crash():
    text = Path('app/gui/main_window.py').read_text(encoding='utf-8')
    assert 'envíos pendientes' in text
    assert 'NO se volverán a enviar automáticamente' in text
