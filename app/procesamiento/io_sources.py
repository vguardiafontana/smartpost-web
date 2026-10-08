from __future__ import annotations

import csv
import io
import math
from pathlib import Path
from typing import Any

from .rules import EXPECTED_HEADERS, TEXT_COLUMNS, normalize_key


def _matrix(value: Any) -> list[list[Any]]:
    if value is None:
        return []
    if not isinstance(value, tuple):
        return [[value]]
    if value and not isinstance(value[0], tuple):
        return [list(value)]
    return [list(r) for r in value]


def _numeric_to_operational_text(value: Any) -> str:
    """Fast lossless-enough text conversion for General-format operational cells.

    For integer-looking Excel doubles within the exact integer range, avoid the
    trailing `.0`. Non-integers use Python's shortest round-trip representation.
    Custom number formats still fall back to Excel's `.Text` below.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _find_header_index(data: list[list[Any]]) -> int:
    expected = {normalize_key(h) for h in EXPECTED_HEADERS}
    best_idx = None
    best_score = -1
    for idx, row in enumerate(data[:10]):
        keys = {normalize_key(v) for v in row if v not in (None, "")}
        score = len(keys & expected)
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx is None or best_score < 4:
        raise ValueError("No pude identificar de forma confiable la fila de encabezados.")
    return best_idx


def read_xlsx_via_excel(excel, path: Path) -> tuple[list[str], list[list[Any]]]:
    """Read an XLS/XLSX through Excel without changing textual identifiers.

    Value2 is used for dates/numbers because it avoids locale conversions.  For
    columns that are not explicitly numeric/date by business rule, the
    displayed text is preferred when Excel exposes a numeric value. This keeps
    numeric-looking operational text exact: Guia Agente, Peso Volumetrico,
    Documento, Trabajo, COM.CELULAR, codes, observations, etc.
    """
    wb = None
    try:
        wb = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True, AddToMru=False)
        ws = wb.Worksheets(1)
        data = _matrix(ws.UsedRange.Value2)
        if not data:
            return [], []

        header_idx = _find_header_index(data)
        headers = [str(v).strip() if v is not None else "" for v in data[header_idx]]
        normalized = {normalize_key(h): i for i, h in enumerate(headers) if h}

        # Patch operational text columns. The old implementation called
        # `Cells(...).Text` once per numeric-looking cell, which can mean
        # thousands of slow COM round trips. We now inspect one whole column
        # format at a time. General/Text columns are converted locally; only
        # mixed/custom-formatted cells fall back to Excel `.Text`.
        used_first_row = ws.UsedRange.Row
        used_first_col = ws.UsedRange.Column
        first_data_excel_row = used_first_row + header_idx + 1
        last_data_excel_row = used_first_row + len(data) - 1
        for col_name in TEXT_COLUMNS:
            cidx = normalized.get(normalize_key(col_name))
            if cidx is None or last_data_excel_row < first_data_excel_row:
                continue
            excel_col = used_first_col + cidx
            try:
                common_fmt = ws.Range(
                    ws.Cells(first_data_excel_row, excel_col),
                    ws.Cells(last_data_excel_row, excel_col),
                ).NumberFormat
            except Exception:
                common_fmt = None

            simple_format = isinstance(common_fmt, str) and common_fmt.strip().lower() in {"general", "@"}
            for data_row_idx in range(header_idx + 1, len(data)):
                raw = data[data_row_idx][cidx] if cidx < len(data[data_row_idx]) else None
                if raw in (None, "") or isinstance(raw, str):
                    continue
                if simple_format:
                    data[data_row_idx][cidx] = _numeric_to_operational_text(raw)
                    continue

                # Mixed/custom number formats may encode visible leading zeroes
                # or punctuation, so ask Excel only for those exceptional cells.
                excel_row = used_first_row + data_row_idx
                try:
                    shown = ws.Cells(excel_row, excel_col).Text
                    if shown not in (None, "", "#####") and "###" not in str(shown):
                        data[data_row_idx][cidx] = str(shown)
                    else:
                        data[data_row_idx][cidx] = _numeric_to_operational_text(raw)
                except Exception:
                    data[data_row_idx][cidx] = _numeric_to_operational_text(raw)

        return _find_header_and_rows(data)
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)


def _read_text_with_fallbacks(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin1", errors="replace")


def read_csv_file(path: Path) -> tuple[list[str], list[list[Any]]]:
    text = _read_text_with_fallbacks(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        dialect = type("D", (csv.excel,), {"delimiter": delimiter})
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect=dialect))
    return _find_header_and_rows(rows)


def _find_header_and_rows(data: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    best_idx = _find_header_index(data)
    headers = [str(v).strip() if v is not None else "" for v in data[best_idx]]
    rows = data[best_idx + 1 :]
    # Ignore completely empty trailing rows.
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    return headers, rows


def rows_to_dicts(headers: list[str], rows: list[list[Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized_source: dict[str, int] = {}
    duplicates: list[str] = []
    for i, h in enumerate(headers):
        k = normalize_key(h)
        if not k:
            continue
        if k in normalized_source:
            duplicates.append(h)
        else:
            normalized_source[k] = i

    # Los encabezados no cambian entre filas de este archivo.
    column_map = [(expected, normalized_source.get(normalize_key(expected))) for expected in EXPECTED_HEADERS]
    mapped: list[dict[str, Any]] = []
    for raw in rows:
        if all(v in (None, "") for v in raw):
            continue
        item = {}
        for expected, idx in column_map:
            item[expected] = raw[idx] if idx is not None and idx < len(raw) else None
        mapped.append(item)
    return mapped, duplicates
