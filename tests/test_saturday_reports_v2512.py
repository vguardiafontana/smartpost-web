from datetime import datetime

from app.core.config import report_seller_configs


def _cfg():
    names = [
        "ENVIO PACK", "ZETABURGOS", "GIANGIU", "ENOTEK", "JAGUAR",
        "FARMALAND", "ONECLICK", "G-COMMERCE", "PINTURERIAS MM / TIMARO",
        "TECNONUBEL", "CLASS", "PINTURERIAS SAN ANTONIO",
        "PINTURERIA MILCOLORES", "APOLLO",
    ]
    return {
        "reportes": {
            "saturday_sellers": [
                "ZETABURGOS", "GIANGIU", "G-COMMERCE",
                "PINTURERIAS MM / TIMARO", "TECNONUBEL", "CLASS",
                "PINTURERIA MILCOLORES",
            ]
        },
        "sellers": [{"seller": n, "enabled": True} for n in names],
    }


def test_saturday_uses_only_requested_sellers():
    # 2026-10-03 es sábado.
    got = [x["seller"] for x in report_seller_configs(_cfg(), datetime(2026, 10, 3))]
    assert got == [
        "ZETABURGOS", "GIANGIU", "G-COMMERCE",
        "PINTURERIAS MM / TIMARO", "TECNONUBEL", "CLASS",
        "PINTURERIA MILCOLORES",
    ]


def test_non_saturday_keeps_all_enabled_sellers():
    got = [x["seller"] for x in report_seller_configs(_cfg(), datetime(2026, 10, 5))]
    assert len(got) == 14
    assert "APOLLO" in got
    assert "ENVIO PACK" in got


def test_disabled_seller_stays_disabled_on_saturday():
    cfg = _cfg()
    next(x for x in cfg["sellers"] if x["seller"] == "CLASS")["enabled"] = False
    got = [x["seller"] for x in report_seller_configs(cfg, datetime(2026, 10, 3))]
    assert "CLASS" not in got
