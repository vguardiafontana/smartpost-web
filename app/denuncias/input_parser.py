from __future__ import annotations

import re


def parse_identifiers(text: str) -> list[str]:
    """Extract guide/remito/Guia Agente identifiers from free-form pasted text."""
    values = re.findall(r"(?<!\d)\d{5,20}(?!\d)", str(text or ""))
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def query_field_order(query: str) -> list[str]:
    """Efficient search order. Prefixes are hints only; all fields remain fallbacks."""
    q = re.sub(r"\D", "", str(query or ""))
    if q.startswith("2000") or len(q) >= 14:
        return ["guia_agente", "nroGuia", "rto_cliente"]
    if 5 <= len(q) <= 9:
        return ["nroGuia", "rto_cliente", "guia_agente"]
    if 10 <= len(q) <= 13:
        return ["rto_cliente", "nroGuia", "guia_agente"]
    return ["nroGuia", "rto_cliente", "guia_agente"]
