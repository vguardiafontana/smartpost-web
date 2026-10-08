from datetime import datetime

from app.core.utils import parse_operational_date
from app.core.dates import seller_date_range


def test_manual_date_parse():
    dt = parse_operational_date("18-09-2026")
    assert dt == datetime(2026, 9, 18)


def test_apollo_month_range():
    dt = datetime(2026, 9, 18)
    assert seller_date_range({"date_mode": "month_to_selected"}, dt) == "01/09/2026 - 18/09/2026"
    assert seller_date_range({"date_mode": "single_day"}, dt) == "18/09/2026 - 18/09/2026"
