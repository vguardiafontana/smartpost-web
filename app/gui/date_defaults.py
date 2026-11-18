"""Mantener al día la fecha predeterminada sin pisar elecciones manuales."""
from PySide6.QtCore import QDate, QTimer
from app.core.dates import operation_date


def follow_business_date(widget):
    def today_qdate():
        day = operation_date()
        return QDate(day.year, day.month, day.day)

    previous = today_qdate()
    widget.setDate(previous)
    timer = QTimer(widget)
    timer.setInterval(60_000)

    def refresh():
        nonlocal previous
        today = today_qdate()
        if today != previous:
            if widget.date() == previous:
                widget.setDate(today)
            previous = today

    timer.timeout.connect(refresh)
    timer.start()
    return timer
