from datetime import datetime

from app.delivery.chat_archive import _time_fallback_mode


def test_time_fallback_unarchive_window():
    assert _time_fallback_mode(datetime(2026, 9, 23, 17, 0)) == "unarchive"
    assert _time_fallback_mode(datetime(2026, 9, 23, 18, 59)) == "unarchive"


def test_time_fallback_archive_window_wraps_midnight():
    assert _time_fallback_mode(datetime(2026, 9, 23, 22, 0)) == "archive"
    assert _time_fallback_mode(datetime(2026, 9, 23, 23, 59)) == "archive"
    assert _time_fallback_mode(datetime(2026, 9, 24, 0, 59)) == "archive"


def test_time_fallback_none_outside_windows():
    assert _time_fallback_mode(datetime(2026, 9, 23, 12, 0)) is None
    assert _time_fallback_mode(datetime(2026, 9, 23, 20, 0)) is None
