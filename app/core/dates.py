from __future__ import annotations


def seller_date_range(seller_cfg: dict, selected_date) -> str:
    end = selected_date.strftime("%d/%m/%Y")
    if str(seller_cfg.get("date_mode", "single_day")).lower() == "month_to_selected":
        start = selected_date.replace(day=1).strftime("%d/%m/%Y")
        return f"{start} - {end}"
    return f"{end} - {end}"
