from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.config import resolve_path
from app.core.models import RunContext
from app.core.utils import safe_filename
from app.procesamiento.io_sources import read_csv_file
from app.procesamiento.processor import close_excel, make_excel_app
from app.procesamiento.rules import EXPECTED_HEADERS, normalize_key

XL_OPENXML_WORKBOOK = 51


def _validated_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    headers, rows = read_csv_file(path)
    expected = [normalize_key(x) for x in EXPECTED_HEADERS]
    actual = [normalize_key(x) for x in headers]
    if len(headers) != len(EXPECTED_HEADERS):
        raise RuntimeError(
            f"VISITAS: esperaba {len(EXPECTED_HEADERS)} columnas y encontré {len(headers)}."
        )
    mismatches = [
        f"{i + 1}: '{EXPECTED_HEADERS[i]}' != '{headers[i]}'"
        for i in range(len(expected))
        if expected[i] != actual[i]
    ]
    if mismatches:
        raise RuntimeError("VISITAS: encabezados inesperados: " + " | ".join(mismatches[:8]))
    clean_rows: list[list[str]] = []
    for row_num, row in enumerate(rows, start=2):
        if len(row) != len(headers):
            raise RuntimeError(
                f"VISITAS: fila {row_num} tiene {len(row)} columnas; esperaba {len(headers)}."
            )
        clean_rows.append(["" if value is None else str(value) for value in row])
    return [str(x) for x in headers], clean_rows


def _output_path(cfg: dict, run: RunContext) -> Path:
    visits_cfg = cfg.get("visitas") or {}
    template = str(visits_cfg.get("filename") or "VISITAS {date_short}.xlsx")
    name = template.format(
        date=run.message_date,
        date_short=run.date_short,
        date_ddmmyyyy=run.date_ddmmyyyy,
    )
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    name = safe_filename(name)
    root = (
        resolve_path(cfg, "dry_run_reports") / run.date_ddmmyyyy / run.run_id
        if run.dry_run
        else resolve_path(cfg, "reports") / run.date_ddmmyyyy
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def convert_visits_csv_to_xlsx(cfg: dict, run: RunContext, csv_path: Path, logger) -> dict:
    """Convert the Epresis VISITAS CSV into a stable XLSX using real Excel.

    Every source value is written as text. This intentionally prevents Excel
    from rounding long identifiers, stripping leading zeroes, interpreting '#'
    codes as errors or changing locale-sensitive values during the conversion.
    """
    headers, rows = _validated_csv(csv_path)
    output = _output_path(cfg, run)
    if output.exists():
        output.unlink()

    excel = make_excel_app()
    wb = None
    try:
        wb = excel.Workbooks.Add()
        ws = wb.Worksheets(1)
        ws.Name = "VISITAS"
        while wb.Worksheets.Count > 1:
            wb.Worksheets(wb.Worksheets.Count).Delete()

        total_rows = len(rows) + 1
        total_cols = len(headers)
        end_cell = ws.Cells(total_rows, total_cols)
        full_range = ws.Range(ws.Cells(1, 1), end_cell)
        # Pre-format everything as text BEFORE assigning values. This is the
        # reliable COM equivalent of importing a CSV without automatic coercion.
        full_range.NumberFormat = "@"

        ws.Range(ws.Cells(1, 1), ws.Cells(1, total_cols)).Value2 = (tuple(headers),)

        batch_size = 2000
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            first_excel_row = start + 2
            last_excel_row = first_excel_row + len(batch) - 1
            matrix = tuple(tuple(row) for row in batch)
            ws.Range(
                ws.Cells(first_excel_row, 1),
                ws.Cells(last_excel_row, total_cols),
            ).Value2 = matrix

        header = ws.Range(ws.Cells(1, 1), ws.Cells(1, total_cols))
        header.Font.Bold = True
        header.AutoFilter()
        try:
            ws.Activate()
            excel.ActiveWindow.SplitRow = 1
            excel.ActiveWindow.FreezePanes = True
        except Exception:
            pass

        try:
            ws.Columns.AutoFit()
            # Avoid absurd widths caused by long observations.
            for col in range(1, total_cols + 1):
                if float(ws.Columns(col).ColumnWidth or 0) > 45:
                    ws.Columns(col).ColumnWidth = 45
        except Exception:
            pass

        wb.SaveAs(str(output), FileFormat=XL_OPENXML_WORKBOOK)
        wb.Close(SaveChanges=False)
        wb = None
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        close_excel(excel)

    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError("VISITAS: Excel no generó el archivo XLSX final.")
    try:
        with zipfile.ZipFile(output, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"VISITAS: XLSX corrupto ({bad}).")
            names = set(zf.namelist())
            if "xl/workbook.xml" not in names:
                raise RuntimeError("VISITAS: el archivo generado no tiene estructura XLSX válida.")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("VISITAS: el archivo generado no es un XLSX válido.") from exc

    logger.info("[VISITAS] XLSX generado -> %s (%d registros)", output.name, len(rows))
    return {
        "status": "generated",
        "path": str(output),
        "rows": len(rows),
        "columns": len(headers),
    }
