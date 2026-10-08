from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

SUPPORTED_PROMPT_SHA256 = "ea0c597a2043519ce2919513b8859fb98ac6b2485bef94b4076f481c0177344a"

EXPECTED_HEADERS = [
    "Nro Guia", "Fecha", "Cliente", "Sucursal", "Estado", "Motivo", "Remito",
    "Guia Agente", "Servicio", "Tiempo", "Localidad Origen", "Localidad Destino",
    "Destino", "Peso", "Bultos", "Importe", "Valor Declarado", "Empresa",
    "Destinatario", "Domicilio", "Localidad", "Provincia", "Email", "Horario",
    "Distribuidor Recorrido", "Distribuidor Origen", "Distribuidor Destino",
    "Fecha Planilla", "Nro. Planilla", "Fecha Rendicion", "Nro. Rendicion",
    "Fecha Pactada", "Fecha Entrega", "Recibio", "Documento", "Lote",
    "Contrareembolso", "Other Info", "Obs 1", "Obs 2", "Nro.Socio", "Nro.Prestador",
    "Usuario", "Peso Volumetrico", "Volumen", "Ceco", "Importe Urgente", "Kg Exceso",
    "Importe Exceso", "Sector", "Trabajo", "Fecha Repactacion", "CP",
    "PLANILLA FACTURADO", "CONSTANCIA RETIRO", "SUCURSAL ORIGEN", "SUCURSAL DESTINO",
    "GRUPO", "COM.OBS 3", "COM.OBS 4", "COM.OTHER INFO", "COM.CELULAR",
    "FECHA ULTIMO ESTADO", "Precinto", "Codigo Sucursal", "Fecha Ingreso a Planta",
    "Datos Envios Obs", "Pago En", "Codigo Sucursal Naranja Devolucion",
    "Descripcion Sucursal Naranja Devolucion", "Zona Destino", "Sub Zona Destino",
    "Nombre Fantasia", "Nro.Liquidacion", "Canal"
]

CRITICAL_HEADERS = {"Nro Guia", "Estado", "Remito", "Servicio"}

INTEGER_COLUMNS = {
    "Nro Guia", "Nro. Planilla", "Nro. Rendicion", "Contrareembolso", "Kg Exceso",
    "Importe Exceso", "CP", "Nro.Socio", "Nro.Prestador", "Nro.Liquidacion", "Bultos"
}
DECIMAL_COLUMNS = {"Peso", "Importe", "Valor Declarado", "Volumen", "Importe Urgente"}
DATE_ONLY_COLUMNS = {"Fecha Planilla", "Fecha Rendicion", "Fecha Pactada", "Fecha Repactacion"}
DATETIME_COLUMNS = {"Fecha", "Fecha Entrega", "FECHA ULTIMO ESTADO", "Fecha Ingreso a Planta"}

# IMPORTANT: every column not explicitly declared numeric/date and not Remito
# is operational text. This matches the normal reports: fields such as
# Documento (AI), Trabajo (AY), COM.CELULAR (BJ), Guia Agente (H),
# Peso Volumetrico (AR), codes, observations and names must retain their exact
# characters. Numeric-looking strings must NOT be auto-converted by Excel.
# This also preserves leading zeroes (e.g. phone 011...) and punctuation
# (e.g. Documento '34.072273').
TEXT_COLUMNS = (
    set(EXPECTED_HEADERS)
    - INTEGER_COLUMNS
    - DECIMAL_COLUMNS
    - DATE_ONLY_COLUMNS
    - DATETIME_COLUMNS
    - {"Remito"}
)

SERVICE_ALIASES = {
    "FLEX": "FLEX",
    "SAMEDAY": "SAMEDAY",
    "SAME DAY": "SAMEDAY",
    "SAME-DAY": "SAMEDAY",
    "SDD": "SAMEDAY",
    "EXPRESS": "EXPRESS",
    "EXP": "EXPRESS",
    "STANDARD": "STANDARD",
    "STD": "STANDARD",
    "ESTANDAR": "STANDARD",
    "PRIORITY": "PRIORITY",
    "PRIORITARIO": "PRIORITY",
    "ECONOMY": "ECONOMY",
    "ECONOMICO": "ECONOMY",
    "ECO": "ECONOMY",
}
KNOWN_FINAL_STATE_KEYWORDS = ("ENTREG", "ESTADO FINAL", "DEVOL", "RECHAZ", "CANCEL", "CERRAD")
VISIT_STATE_KEYWORDS = ("VISITA", "RUTA", "ARRIB", "MATRIZ", "PENDIENTE")

REPORT_MAP = {
    "A": "A", "B": "BN", "C": "C", "D": "E", "E": "BF", "G": "G",
    "H": "I", "I": "S", "J": "T", "K": "U", "L": "Y", "M": "AH",
    "N": "AI", "O": "BA", "P": "BK", "Q": "BS"
}


def normalize_spaces(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def clean_preserved_text(value: Any) -> str:
    """Preserve meaningful text/newlines while removing accidental edge spaces.

    Unlike normalize_spaces(), this MUST NOT collapse embedded line breaks or
    internal spaces.  It is used for operational text fields copied into base.
    """
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip(" \t")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_key(value: Any) -> str:
    text = strip_accents(normalize_spaces(value)).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_seller_name(value: Any) -> str:
    s = strip_accents(normalize_spaces(value)).upper().replace("_", " ")
    # Remove operational suffixes regardless of whether a date comes after them.
    s = re.sub(r"\b\d{1,2}[-_.]\d{1,2}[-_.]\d{2,4}\b", " ", s)
    s = re.sub(r"\((\d+)\)", " ", s)
    s = re.sub(r"\b(?:REPORTE|FINAL|V\s*\d+)\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -_.")
    return s


def resolve_seller_from_rows(
    rows: list[dict[str, Any]],
    alias_map: dict[str, str],
    columns: tuple[str, ...] = ("Cliente", "Nombre Fantasia", "Empresa"),
) -> tuple[str, dict[str, list[str]]]:
    """Resolve seller strictly from table data, never from the raw filename.

    Each candidate column is evaluated independently in priority order. If all
    non-empty values in a column collapse to one canonical seller (including
    aliases), that seller is accepted. Otherwise the next column is tried.
    Ambiguity fails closed instead of guessing.
    """
    evidence: dict[str, list[str]] = {}
    for col in columns:
        values: list[str] = []
        for row in rows:
            raw = canonical_seller_name(row.get(col))
            if not raw:
                continue
            mapped = alias_map.get(normalize_key(raw), raw)
            mapped = canonical_seller_name(mapped)
            if mapped:
                values.append(mapped)
        unique = sorted(set(values))
        evidence[col] = unique[:50]
        if len(unique) == 1:
            return unique[0], evidence

    # Last safe check: if all candidate columns together contain exactly one
    # canonical value, accept it. Otherwise do not infer a seller.
    all_values = sorted({v for vals in evidence.values() for v in vals})
    if len(all_values) == 1:
        return all_values[0], evidence
    raise ValueError(f"Seller ambiguo o ausente dentro de las tablas; evidencias: {evidence}")


def unwrap_excel_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip()
    m = re.fullmatch(r'=\s*"(.*)"\s*', s, flags=re.S)
    return m.group(1) if m else value


def remito_as_string(value: Any) -> str:
    value = unwrap_excel_text(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return format(value, ".15g")
    return normalize_spaces(value)


def normalize_remito(value: Any) -> Any:
    s = remito_as_string(value)
    if not s:
        return None
    # Preserve text when it contains letters, starts with #, has separators, or has leading zero.
    if s.startswith("#") or re.search(r"[A-Za-z]", s) or not re.fullmatch(r"\d+", s):
        return s
    if len(s) > 15 or (len(s) > 1 and s.startswith("0")):
        return s
    try:
        return int(s)
    except ValueError:
        return s


def remito_ends_01(value: Any) -> bool:
    return remito_as_string(value).endswith("-01")


def normalize_service(remito: Any, original_service: Any) -> tuple[str | None, bool]:
    rem = remito_as_string(remito)
    raw = normalize_spaces(original_service).upper()
    raw = re.sub(r"\s+", " ", raw)
    alias = SERVICE_ALIASES.get(raw, raw)

    if rem.startswith("47"):
        return "FLEX", False

    contains_letters = bool(re.search(r"[A-Za-z]", rem))
    if contains_letters and (alias == "FLEX" or alias == ""):
        return "SAMEDAY", False

    if alias == "":
        return None, False

    known = alias in set(SERVICE_ALIASES.values())
    return alias, not known


def parse_spanish_number(value: Any, integer: bool) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value) if integer else float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        if integer:
            return int(round(float(value)))
        return float(value)

    s = normalize_spaces(value)
    if not s:
        return None
    # Source convention from the Prompt Maestro: dot=thousands, comma=decimal.
    s = s.replace(".", "").replace(",", ".")
    try:
        num = float(s)
        return int(round(num)) if integer else num
    except ValueError:
        return None


def excel_serial_to_datetime(value: float) -> datetime:
    return datetime(1899, 12, 30) + timedelta(days=float(value))


def parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        try:
            return datetime(value.year, value.month, value.day, getattr(value, "hour", 0), getattr(value, "minute", 0), getattr(value, "second", 0))
        except Exception:
            pass
    if isinstance(value, (int, float)) and 1 <= float(value) <= 100000:
        return excel_serial_to_datetime(float(value))

    s = normalize_spaces(value)
    formats = (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def sanitize_value(column: str, value: Any) -> Any:
    value = unwrap_excel_text(value)
    if value is None:
        return None
    if isinstance(value, str) and clean_preserved_text(value) == "":
        return None
    if column == "Remito":
        return normalize_remito(value)
    if column in TEXT_COLUMNS:
        # These two columns are identifiers/text by business rule.  Never run
        # them through locale/float conversion.
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return clean_preserved_text(value)
    if column in INTEGER_COLUMNS:
        parsed = parse_spanish_number(value, integer=True)
        return parsed if parsed is not None else clean_preserved_text(value) if isinstance(value, str) else value
    if column in DECIMAL_COLUMNS:
        parsed = parse_spanish_number(value, integer=False)
        return parsed if parsed is not None else clean_preserved_text(value) if isinstance(value, str) else value
    if column in DATE_ONLY_COLUMNS or column in DATETIME_COLUMNS:
        # Excel Value2 already supplies OLE serial numbers. Keep those numbers
        # untouched so they cannot acquire a UTC/local-time offset on write.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and math.isnan(value):
                return None
            if 1 <= float(value) <= 100000:
                return float(value)
        parsed = parse_date(value)
        return parsed if parsed is not None else clean_preserved_text(value) if isinstance(value, str) else value
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        return clean_preserved_text(value)
    return value


def management_result(state: Any) -> str | None:
    s = normalize_spaces(state).upper()
    if not s:
        return None
    return "VISITA COORDINADA CON EL CLIENTE" if any(k in s for k in VISIT_STATE_KEYWORDS) else "N/A"


def state_is_ambiguous(state: Any) -> bool:
    s = normalize_spaces(state).upper()
    if not s:
        return True
    if any(k in s for k in VISIT_STATE_KEYWORDS):
        return False
    if any(k in s for k in KNOWN_FINAL_STATE_KEYWORDS):
        return False
    return True


def normalize_row(row_by_header: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    audit = {"unknown_service": None, "ambiguous_state": None}
    rem_raw = row_by_header.get("Remito")
    if remito_ends_01(rem_raw):
        return None, audit

    out = {h: sanitize_value(h, row_by_header.get(h)) for h in EXPECTED_HEADERS}
    service, unknown = normalize_service(out.get("Remito"), row_by_header.get("Servicio"))
    out["Servicio"] = service
    if unknown:
        audit["unknown_service"] = service

    state = out.get("Estado")
    if state_is_ambiguous(state):
        audit["ambiguous_state"] = normalize_spaces(state) or "<VACIO>"
    return out, audit

