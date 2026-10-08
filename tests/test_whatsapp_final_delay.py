from pathlib import Path


def test_final_visitas_close_delay_present():
    src = (Path(__file__).parents[1] / "app" / "delivery" / "whatsapp.py").read_text(encoding="utf-8")
    assert 'final_visitas_close_delay_ms' in src
    assert '5000' in src
    assert 'res.get("status") == "sent"' in src
