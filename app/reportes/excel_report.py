from __future__ import annotations

import math
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.procesamiento.rules import (
    DATE_ONLY_COLUMNS,
    DATETIME_COLUMNS,
    EXPECTED_HEADERS,
    REPORT_MAP,
    TEXT_COLUMNS,
    normalize_key,
    remito_as_string,
)

XL_CELL_TYPE_FORMULAS = -4123
XL_ERRORS = 16
XL_PASTE_FORMATS = -4122
XL_VALIDATE_LIST = 3
XL_ALERT_STOP = 1
XL_BETWEEN = 1
XL_SRC_RANGE = 1
XL_YES = 1
XL_SHEET_VISIBLE = -1
XL_GENERAL = -4108
XL_TOP = -4160

EXCEL_EPOCH = datetime(1899, 12, 30)
MAX_BASE_ROW_HEIGHT = 60.0
MAX_REPORT_ROW_HEIGHT = 69.75


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _values_2d(value: Any) -> list[list[Any]]:
    if value is None:
        return []
    if not isinstance(value, tuple):
        return [[value]]
    if value and not isinstance(value[0], tuple):
        return [list(value)]
    return [list(r) for r in value]


def _contiguous_ranges(indices: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted row/column indices into contiguous ranges.

    Excel COM calls are relatively expensive. Grouping 50 text columns into a
    dozen ranges is much faster than touching every column/cell separately.
    """
    if not indices:
        return []
    values = sorted(set(indices))
    out: list[tuple[int, int]] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        out.append((start, prev))
        start = prev = value
    out.append((start, prev))
    return out


def _set_format_for_columns(ws, start_row: int, end_row: int, col_indices: list[int], fmt: str) -> None:
    if end_row < start_row:
        return
    for c1, c2 in _contiguous_ranges(col_indices):
        ws.Range(ws.Cells(start_row, c1), ws.Cells(end_row, c2)).NumberFormat = fmt


def _restore_column_formats(ws, start_row: int, end_row: int, formats: dict[int, Any]) -> None:
    """Restore template formats using contiguous groups with identical formats."""
    if end_row < start_row or not formats:
        return
    ordered = sorted(formats)
    group_start = group_prev = ordered[0]
    group_fmt = formats[group_start]
    groups: list[tuple[int, int, Any]] = []
    for idx in ordered[1:]:
        fmt = formats[idx]
        if idx == group_prev + 1 and fmt == group_fmt:
            group_prev = idx
            continue
        groups.append((group_start, group_prev, group_fmt))
        group_start = group_prev = idx
        group_fmt = fmt
    groups.append((group_start, group_prev, group_fmt))
    for c1, c2, fmt in groups:
        ws.Range(ws.Cells(start_row, c1), ws.Cells(end_row, c2)).NumberFormat = fmt


def _excel_serial(value: datetime | date) -> float:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    return (value - EXCEL_EPOCH).total_seconds() / 86400.0


def _excel_write_value(column: str, value: Any) -> Any:
    """Convert Python values to COM-safe Excel Value2 values.

    Crucially, datetimes are converted to OLE serial numbers ourselves instead
    of handing datetime objects to pywin32. That avoids the +3h UTC/local-time
    conversion observed on Windows/Argentina.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _excel_serial(value)
    if isinstance(value, date):
        return _excel_serial(value)
    if column in TEXT_COLUMNS:
        return str(value)
    return value


def _equivalent(expected: Any, actual: Any, tol: float = 2e-9) -> bool:
    if expected in (None, "") and actual in (None, ""):
        return True
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        if isinstance(expected, float) and math.isnan(expected):
            return actual in (None, "")
        return abs(float(expected) - float(actual)) <= tol
    return expected == actual


def _cap_row_heights(ws, start_row: int, end_row: int, max_height: float) -> None:
    if end_row < start_row:
        return
    try:
        ws.Rows(f"{start_row}:{end_row}").AutoFit()
        # Excel returns one height for a uniform range, None for mixed heights.
        # Split only mixed ranges: thousands of ordinary rows need one COM read.
        pending = [(start_row, end_row)]
        while pending:
            first, last = pending.pop()
            group = ws.Rows(f"{first}:{last}")
            height = group.RowHeight
            if height is not None:
                if float(height) > max_height:
                    group.RowHeight = max_height
            elif first < last:
                middle = (first + last) // 2
                pending.extend(((first, middle), (middle + 1, last)))
    except Exception:
        # Row-height differences should never corrupt the report; the structural
        # and data audit below remains authoritative.
        pass


def _remove_existing_report_table(report) -> None:
    try:
        # Delete backwards in case a previous template version already has one.
        for i in range(report.ListObjects.Count, 0, -1):
            report.ListObjects(i).Unlist()
    except Exception:
        pass


def _add_report_table(report, final_last: int):
    _remove_existing_report_table(report)
    try:
        if report.AutoFilterMode:
            report.AutoFilterMode = False
    except Exception:
        pass
    lo = report.ListObjects.Add(XL_SRC_RANGE, report.Range(f"A1:Q{max(2, final_last)}"), None, XL_YES)
    lo.Name = "ReporteTable"
    # The normal report is a real Excel table. We do not impose a guessed
    # coloured table style here; the explicit template/header/body formatting
    # remains in control while the ListObject provides the true table semantics.
    try:
        lo.TableStyle = ""
    except Exception:
        pass
    try:
        lo.ShowTableStyleRowStripes = False
        lo.ShowTableStyleColumnStripes = False
    except Exception:
        pass
    return lo


def _unfreeze_report(excel, report) -> bool:
    try:
        report.Activate()
        win = excel.ActiveWindow
        if win is not None:
            win.FreezePanes = False
            win.SplitRow = 0
            win.SplitColumn = 0
            return not bool(win.FreezePanes)
    except Exception:
        pass
    return False


def verify_template(wb) -> list[str]:
    problems = []
    names = [wb.Worksheets(i).Name for i in range(1, wb.Worksheets.Count + 1)]
    for required in ("REPORTE", "base", "aux"):
        if required not in names:
            problems.append(f"Falta la hoja obligatoria {required}.")
    if problems:
        return problems

    base = wb.Worksheets("base")
    actual_matrix = _values_2d(base.Range("A1:BW1").Value2)
    actual = actual_matrix[0] if actual_matrix else []
    for i, (expected, got) in enumerate(zip(EXPECTED_HEADERS, actual), start=1):
        if normalize_key(expected) != normalize_key(got):
            problems.append(f"base!{_col_letter(i)}1 esperado '{expected}', encontrado '{got}'.")

    report = wb.Worksheets("REPORTE")
    expected_headers = [
        "Nro Guia", "Fecha ingreso a Planta", "Cliente", "Estado", "TIPO DE ESTADO",
        "GESTIÓN REALIZADA", "Remito", "Servicio", "Destinatario", "Domicilio", "Localidad",
        "Distribuidor Recorrido", "Recibio", "Documento", "CP", "FECHA ULTIMO ESTADO", "Zona Destino"
    ]
    report_matrix = _values_2d(report.Range("A1:Q1").Value2)
    actual_report = report_matrix[0] if report_matrix else []
    for i, (expected, got) in enumerate(zip(expected_headers, actual_report), start=1):
        if normalize_key(expected) != normalize_key(got):
            problems.append(f"REPORTE!{_col_letter(i)}1 esperado '{expected}', encontrado '{got}'.")
    return problems


def write_report(excel, template_path: Path, output_path: Path, rows: list[dict[str, Any]], seller: str, audit: dict) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)
    wb = None
    try:
        wb = excel.Workbooks.Open(str(output_path), UpdateLinks=0, ReadOnly=False, AddToMru=False)
        structural = verify_template(wb)
        if structural:
            raise RuntimeError("Estructura de template no compatible: " + " | ".join(structural))

        base = wb.Worksheets("base")
        report = wb.Worksheets("REPORTE")
        aux = wb.Worksheets("aux")
        header_index = {h: i + 1 for i, h in enumerate(EXPECTED_HEADERS)}

        # Preserve the template's own display format per base column. We may
        # temporarily force text format while writing to stop Excel from
        # auto-converting numeric-looking strings, then restore the original
        # format without changing the stored text value. This is how the normal
        # files can contain string cells under a General number format.
        original_base_formats = {
            idx: base.Cells(2, idx).NumberFormat
            for idx in range(1, 76)
        }

        # ------------------------------------------------------------------
        # BASE: preserve data semantics before writing.
        # ------------------------------------------------------------------
        used_last = max(2, base.UsedRange.Row + base.UsedRange.Rows.Count - 1)
        base.Range(base.Cells(2, 1), base.Cells(used_last, 75)).ClearContents()

        n = len(rows)
        if n:
            # Extend base formatting using a normal Calibri-11 base row, not the
            # REPORTE first data row (which is the source of the Calibri-18 bug).
            base_template_last = max(2, base.UsedRange.Row + base.UsedRange.Rows.Count - 1)
            if n + 1 > base_template_last:
                base.Range("A2:BW2").Copy()
                base.Range(f"A{base_template_last + 1}:BW{n + 1}").PasteSpecial(Paste=XL_PASTE_FORMATS)
                excel.CutCopyMode = False

            target = base.Range(base.Cells(2, 1), base.Cells(n + 1, 75))

            # MUST be formatted as text *before* writing. If applied afterwards,
            # Excel may convert any numeric-looking operational text to numbers:
            # long IDs, Documento, Trabajo, phone numbers, decimal-comma text,
            # codes with leading zeroes, etc.
            text_indices = sorted(header_index[col] for col in TEXT_COLUMNS)
            _set_format_for_columns(base, 2, n + 1, text_indices, "@")

            # Set date formats before Value2 assignment. Values themselves are
            # serials, so COM never receives timezone-aware/naive datetime objects.
            for col in DATE_ONLY_COLUMNS:
                idx = header_index[col]
                base.Range(base.Cells(2, idx), base.Cells(n + 1, idx)).NumberFormat = "mm-dd-yy"
            for col in DATETIME_COLUMNS:
                idx = header_index[col]
                base.Range(base.Cells(2, idx), base.Cells(n + 1, idx)).NumberFormat = "m/d/yy h:mm"

            matrix = [
                [_excel_write_value(h, r.get(h)) for h in EXPECTED_HEADERS]
                for r in rows
            ]
            target.Value2 = tuple(tuple(x) for x in matrix)

            # The target ranges were already formatted as Text before the bulk
            # Value2 write, so Excel cannot reinterpret numeric-looking strings.
            # Restore the template display formats in grouped COM calls; stored
            # string values remain strings even when display format returns to General.
            _restore_column_formats(
                base, 2, n + 1,
                {idx: original_base_formats.get(idx, "General") for idx in text_indices},
            )

            # Mixed Remito column: textual/alphanumeric/#/long values must stay
            # text, while safe ordinary numeric remitos may remain numeric.
            rem_idx = header_index["Remito"]
            string_remito_rows = [ridx for ridx, row in enumerate(rows, start=2) if isinstance(row.get("Remito"), str)]
            for r1, r2 in _contiguous_ranges(string_remito_rows):
                rng = base.Range(base.Cells(r1, rem_idx), base.Cells(r2, rem_idx))
                rng.NumberFormat = "@"
                rng.Value2 = tuple((str(rows[r - 2].get("Remito")),) for r in range(r1, r2 + 1))
                rng.NumberFormat = original_base_formats.get(rem_idx, "General")

            _cap_row_heights(base, 2, n + 1, MAX_BASE_ROW_HEIGHT)

        # ------------------------------------------------------------------
        # REPORTE: exact row count, live formulas, normal body styling.
        # ------------------------------------------------------------------
        _remove_existing_report_table(report)
        template_last = max(1, report.UsedRange.Row + report.UsedRange.Rows.Count - 1)
        final_last = n + 1
        if final_last < template_last:
            report.Rows(f"{final_last + 1}:{template_last}").Delete()
        elif final_last > template_last:
            start = template_last + 1
            # Only create rows. Body formatting is normalized below instead of
            # cloning A2 (Calibri 18 / centered), which caused the v2 regression.
            report.Rows(f"{start}:{final_last}").Insert()

        if n:
            formulas = []
            for rnum, source in enumerate(rows, start=2):
                rowf = []
                for letter in "ABCDEFGHIJKLMNOPQ":
                    if letter == "F":
                        rowf.append(
                            f'=IF(D{rnum}="","",IF(OR(ISNUMBER(SEARCH("VISITA",D{rnum})),ISNUMBER(SEARCH("RUTA",D{rnum})),ISNUMBER(SEARCH("ARRIB",D{rnum})),ISNUMBER(SEARCH("MATRIZ",D{rnum})),ISNUMBER(SEARCH("PENDIENTE",D{rnum}))),"VISITA COORDINADA CON EL CLIENTE","N/A"))'
                        )
                    elif letter == "G" and remito_as_string(source.get("Remito")).startswith("#"):
                        literal = remito_as_string(source.get("Remito")).replace('"', '""')
                        rowf.append(f'="{literal}"')
                    else:
                        src = REPORT_MAP[letter]
                        rowf.append(f'=IF(base!{src}{rnum}="","",base!{src}{rnum})')
                formulas.append(rowf)
            report.Range(f"A2:Q{final_last}").Formula = tuple(tuple(x) for x in formulas)

            # Normal report body: Calibri 11, general alignment, wrapped text;
            # never inherit the Calibri-18 centered A2 style from the raw template.
            body = report.Range(f"A2:Q{final_last}")
            body.Font.Name = "Calibri"
            body.Font.Size = 11
            body.HorizontalAlignment = XL_GENERAL
            body.VerticalAlignment = XL_TOP
            body.WrapText = True

            # Keep date displays on their two report date/time columns.
            report.Range(f"B2:B{final_last}").NumberFormat = "dd/mm/yyyy hh:mm:ss"
            report.Range(f"P2:P{final_last}").NumberFormat = "dd/mm/yyyy hh:mm:ss"

            # Rebuild dropdown exactly for active data rows.
            vr = report.Range(f"F2:F{final_last}")
            try:
                vr.Validation.Delete()
            except Exception:
                pass
            vr.Validation.Add(Type=XL_VALIDATE_LIST, AlertStyle=XL_ALERT_STOP, Operator=XL_BETWEEN, Formula1="=aux!$A$1:$A$4")
            vr.Validation.IgnoreBlank = True
            vr.Validation.InCellDropdown = True

            _cap_row_heights(report, 2, final_last, MAX_REPORT_ROW_HEIGHT)

        # The good/normal output has a true Excel table, not only AutoFilter.
        table = _add_report_table(report, final_last)

        # Latest confirmed structural behaviour from the normal comparison.
        aux.Visible = XL_SHEET_VISIBLE
        unfrozen = _unfreeze_report(excel, report)

        # Only REPORTE contains formulas we just changed. A full Excel rebuild is
        # dramatically slower and unnecessary; calculate this worksheet only.
        report.Calculate()

        # ------------------------------------------------------------------
        # Strict regression audit. Any reappearance of the diagnosed problems
        # blocks the file before WhatsApp can send it.
        # ------------------------------------------------------------------
        errors: list[str] = []
        actual_base = _values_2d(base.Range(base.Cells(2, 1), base.Cells(n + 1, 75)).Value2) if n else []
        report_values = _values_2d(report.Range(f"A2:Q{final_last}").Value2) if n else []
        formulas_now = _values_2d(report.Range(f"A2:Q{final_last}").Formula) if n else []
        if n:
            try:
                err_cells = report.Range(f"A2:Q{final_last}").SpecialCells(XL_CELL_TYPE_FORMULAS, XL_ERRORS)
                if err_cells is not None:
                    errors.append(f"Errores de fórmula en {err_cells.Address}")
            except Exception:
                pass

        # 1:1 base value audit against the already-normalized source rows.
        base_mismatches: list[str] = []
        if n:
            for ridx, source in enumerate(rows):
                for cidx, header in enumerate(EXPECTED_HEADERS):
                    expected = _excel_write_value(header, source.get(header))
                    actual = actual_base[ridx][cidx]
                    if not _equivalent(expected, actual):
                        base_mismatches.append(
                            f"{_col_letter(cidx + 1)}{ridx + 2}: {expected!r} != {actual!r}"
                        )
                        if len(base_mismatches) >= 30:
                            break
                if len(base_mismatches) >= 30:
                    break
        if base_mismatches:
            errors.append("BASE modificó valores al escribir: " + " | ".join(base_mismatches[:30]))

        # Explicit guard for every operational text column. This is intentionally
        # strict: a leading zero, punctuation mark, line break or final digit may
        # not disappear merely because the cell looks numeric.
        text_corruption: list[str] = []
        if n:
            for col in TEXT_COLUMNS:
                cidx = header_index[col] - 1
                for ridx, source in enumerate(rows):
                    expected = source.get(col)
                    actual = actual_base[ridx][cidx]
                    if not _equivalent(expected, actual):
                        text_corruption.append(f"{col} fila {ridx + 2}: {expected!r} -> {actual!r}")
                        if len(text_corruption) >= 20:
                            break
                if len(text_corruption) >= 20:
                    break
        if text_corruption:
            errors.append("Corrupción de columnas de texto: " + " | ".join(text_corruption))

        # Date/time guard: REPORTE B/P must be the exact same Excel serial as
        # base BN/BK. This specifically catches the former +0.125-day (+3h) bug.
        date_shift_cells: list[str] = []
        if n:
            bn_idx = header_index["Fecha Ingreso a Planta"] - 1
            bk_idx = header_index["FECHA ULTIMO ESTADO"] - 1
            for ridx in range(n):
                for report_idx, base_idx, letter in ((1, bn_idx, "B"), (15, bk_idx, "P")):
                    bval = actual_base[ridx][base_idx]
                    rval = report_values[ridx][report_idx]
                    if bval in (None, "") and rval in (None, ""):
                        continue
                    if not _equivalent(bval, rval, tol=1e-10):
                        date_shift_cells.append(f"{letter}{ridx + 2}: base={bval!r}, reporte={rval!r}")
                        if len(date_shift_cells) >= 20:
                            break
                if len(date_shift_cells) >= 20:
                    break
        if date_shift_cells:
            errors.append("Fecha/hora alterada entre base y REPORTE: " + " | ".join(date_shift_cells))

        # False zero verification for direct mapped cells.
        false_zeros = []
        if n:
            letter_to_report_idx = {letter: i for i, letter in enumerate("ABCDEFGHIJKLMNOPQ")}
            base_letter_to_header = {}
            for report_letter, base_letter in REPORT_MAP.items():
                colnum = 0
                for ch in base_letter:
                    colnum = colnum * 26 + (ord(ch) - 64)
                base_letter_to_header[report_letter] = EXPECTED_HEADERS[colnum - 1]
            for ridx, source in enumerate(rows):
                for report_letter, header in base_letter_to_header.items():
                    if source.get(header) in (None, ""):
                        val = report_values[ridx][letter_to_report_idx[report_letter]]
                        if val in (0, "0"):
                            false_zeros.append(f"{report_letter}{ridx + 2}")
        if false_zeros:
            errors.append("Falsos 0 en: " + ", ".join(false_zeros[:25]))

        # Formula audit, allowing the required special literal formula for # remitos.
        if n:
            for ridx, frow in enumerate(formulas_now, start=2):
                for cidx, formula in enumerate(frow, start=1):
                    letter = _col_letter(cidx)
                    if letter == "G" and remito_as_string(rows[ridx - 2].get("Remito")).startswith("#"):
                        if not isinstance(formula, str) or not formula.startswith('="'):
                            errors.append(f"Fórmula literal # incorrecta en G{ridx}: {formula!r}")
                            break
                    elif not isinstance(formula, str) or not formula.startswith("=IF("):
                        errors.append(f"Fórmula faltante/inesperada en {report.Cells(ridx, cidx).Address}: {formula!r}")
                        break
                if errors and errors[-1].startswith(("Fórmula faltante", "Fórmula literal")):
                    break

        # Structural checks requested by the normal/v2 comparison.
        try:
            if report.ListObjects.Count != 1 or report.ListObjects(1).Name != "ReporteTable":
                errors.append("Falta la tabla real ReporteTable.")
            else:
                table_addr = report.ListObjects(1).Range.Address.replace("$", "")
                expected_addr = f"A1:Q{max(2, final_last)}"
                if table_addr.upper() != expected_addr.upper():
                    errors.append(f"ReporteTable tiene rango {table_addr}; esperado {expected_addr}.")
        except Exception:
            errors.append("No se pudo confirmar ReporteTable.")

        try:
            if aux.Visible != XL_SHEET_VISIBLE:
                errors.append("La hoja aux quedó oculta; debe quedar visible.")
        except Exception:
            errors.append("No se pudo confirmar visibilidad de aux.")

        if not unfrozen:
            errors.append("REPORTE conserva Freeze Panes; debe quedar sin paneles inmovilizados.")

        if n:
            try:
                size = report.Range(f"A2:Q{final_last}").Font.Size
                if size not in (11, 11.0):
                    errors.append(f"Fuente de datos de REPORTE no es Calibri 11 (Size={size!r}).")
                name = report.Range(f"A2:Q{final_last}").Font.Name
                if name not in ("Calibri", None):
                    errors.append(f"Fuente de datos de REPORTE inesperada: {name!r}.")
            except Exception:
                errors.append("No se pudo confirmar formato de fuente de REPORTE.")

        if n:
            try:
                if report.Range("F2").Validation.Type != XL_VALIDATE_LIST:
                    errors.append("La validación de GESTIÓN REALIZADA no es lista.")
            except Exception:
                errors.append("No se pudo confirmar la validación de GESTIÓN REALIZADA.")

        try:
            if report.Shapes.Count < 1:
                errors.append("No se detectó el logo/drawing del template.")
        except Exception:
            errors.append("No se pudo confirmar el logo/drawing del template.")

        wb.Save()
        audit["excel"] = {
            "base_rows": n,
            "report_rows": n,
            "formula_errors": len(errors),
            "errors": errors,
            "logo_count": int(report.Shapes.Count) if hasattr(report, "Shapes") else None,
            "table": f"ReporteTable A1:Q{max(2, final_last)}",
            "aux_visible": True,
            "freeze_panes": False,
            "regression_guards": {
                "timezone_shift": "checked",
                "all_non_numeric_operational_columns_as_text": "checked",
                "leading_zero_and_punctuation_preservation": "checked",
                "embedded_newlines": "preserved by CSV parser / exact base audit",
                "trailing_spaces": "trimmed only at field edges",
                "hash_remito_formula": "checked",
            },
        }
    finally:
        if wb is not None:
            wb.Close(SaveChanges=True)

    # Internal ZIP validity check after Excel has closed the file.
    try:
        with zipfile.ZipFile(output_path, "r") as z:
            bad = z.testzip()
            if bad:
                audit.setdefault("excel", {}).setdefault("errors", []).append(f"ZIP interno corrupto: {bad}")
    except Exception as exc:
        audit.setdefault("excel", {}).setdefault("errors", []).append(f"XLSX no válido como ZIP: {exc}")
    audit["excel"]["formula_errors"] = len(audit["excel"]["errors"])
    return audit
