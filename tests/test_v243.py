from pathlib import Path


def test_v243_more_lists_checks_popup_after_click():
    src = (Path(__file__).parents[1] / "app" / "delivery" / "chat_archive.py").read_text(encoding="utf-8")
    assert "ic-arrow-drop-down" in src
    assert "_more_lists_popup_visible" in src
    assert "page.mouse.click" in src
    assert "PointerEvent('pointerdown'" in src
