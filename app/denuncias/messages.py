from __future__ import annotations


def seller_message(remitos: list[str], singular_template: str, plural_template: str) -> str:
    clean = [str(x).strip() for x in remitos if str(x).strip()]
    if not clean:
        raise ValueError("No hay remitos para el mensaje")
    if len(clean) == 1:
        return singular_template.format(remito=clean[0])
    lines = "\n".join(f"Remito {x}" for x in clean)
    return plural_template.format(remitos=lines)
