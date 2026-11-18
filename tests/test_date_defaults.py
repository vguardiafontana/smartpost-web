from datetime import date
import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDateEdit
from app.gui import date_defaults


def test_default_date_tracks_montevideo_day_but_preserves_manual_choice(monkeypatch):
    app = QApplication.instance() or QApplication([])
    current = [date(2026, 11, 18)]
    monkeypatch.setattr(date_defaults, 'operation_date', lambda: current[0])
    first, second = QDateEdit(), QDateEdit()
    timer1 = date_defaults.follow_business_date(first)
    timer2 = date_defaults.follow_business_date(second)
    assert first.date() == QDate(2026, 11, 18)
    second.setDate(QDate(2026, 11, 10))
    current[0] = date(2026, 11, 19)
    timer1.timeout.emit(); timer2.timeout.emit()
    assert first.date() == QDate(2026, 11, 19)
    assert second.date() == QDate(2026, 11, 10)
    current[0] = date(2026, 11, 20)
    timer1.timeout.emit(); timer2.timeout.emit()
    assert first.date() == QDate(2026, 11, 20)
    assert second.date() == QDate(2026, 11, 10)
