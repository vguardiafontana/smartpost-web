from __future__ import annotations

import json
from pathlib import Path

from app.core.dates import business_now
from app.denuncias.messages import seller_message


def messages_for_shipments(shipments, cfg):
    grouped = {}
    for item in shipments:
        seller = str(item.get("seller") or "").strip()
        remito = str(item.get("remito") or "").strip()
        if seller and remito and remito not in grouped.setdefault(seller, []):
            grouped[seller].append(remito)
    settings = cfg.get("denuncias") or {}
    singular = settings.get("seller_message_singular", "Buenas noches, lamentamos informar que el siguiente envío, remito {remito}, se encuentra en estado siniestrado. Adjuntamos la denuncia correspondiente.")
    plural = settings.get("seller_message_plural", "Buenas noches, lamentamos informar que los siguientes envíos se encuentran en estado siniestrado:\n\n{remitos}\n\nAdjuntamos la denuncia correspondiente.")
    return [{"seller": seller, "remitos": remitos, "message": seller_message(remitos, singular, plural)} for seller, remitos in grouped.items()]


def save_history(pdf_path, shipments, cfg):
    pdf = Path(pdf_path)
    entry = {"created_at": business_now().isoformat(timespec="seconds"), "sellers": messages_for_shipments(shipments, cfg)}
    target = pdf.with_suffix(".smartpost.json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return entry


def downloaded_reports(folder):
    entries = []
    for pdf in Path(folder).glob("*.pdf"):
        entry = {}
        try:
            entry = json.loads(pdf.with_suffix(".smartpost.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        entries.append({"pdf": str(pdf.resolve()), "filename": pdf.name, "sellers": entry.get("sellers") or [], "created_at": entry.get("created_at") or "", "modified": pdf.stat().st_mtime})
    return sorted(entries, key=lambda item: item["modified"], reverse=True)
