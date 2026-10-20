from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    BUSINESS_TZ = ZoneInfo("America/Montevideo")
except ZoneInfoNotFoundError:
    BUSINESS_TZ = timezone(timedelta(hours=-3), "America/Montevideo")


def business_now() -> datetime:
    return datetime.now(BUSINESS_TZ)


def operation_date(value: str | date | None = None) -> date:
    """A calendar date, never converted through midnight UTC."""
    if value is None:
        return business_now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def seller_date_range(seller_cfg: dict, selected_date) -> str:
    end = selected_date.strftime("%d/%m/%Y")
    if str(seller_cfg.get("date_mode", "single_day")).lower() == "month_to_selected":
        start = selected_date.replace(day=1).strftime("%d/%m/%Y")
        return f"{start} - {end}"
    return f"{end} - {end}"
