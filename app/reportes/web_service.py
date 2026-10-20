from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook

from app.core.config import build_alias_map, load_config, resolve_path, seller_configs
from app.core.models import RunContext
from app.core.state import StateDB
from app.core.utils import sha256_file
from app.descarga.service import download_all
from app.procesamiento.io_sources import read_csv_file, rows_to_dicts
from app.procesamiento.rules import (
    CRITICAL_HEADERS,
    EXPECTED_HEADERS,
    canonical_seller_name,
    management_result,
    normalize_key,
    normalize_row,
    remito_as_string,
    resolve_seller_from_rows,
)
from app.reportes.portable_report import write_report_portable
from app.visitas.portable_excel import convert_visits_csv_to_xlsx_portable
from app.visitas.service import download_visits

ENGINE_VERSION = "web-portable-report-v1"


def _deduplicate(rows: list[dict], block_conflicts: bool) -> tuple[list[dict], int, list[str]]:
    by_guide = defaultdict(list)
    no_guide = []
    for row in rows:
        guide = row.get("Nro Guia")
        (no_guide if guide in (None, "") else by_guide[str(guide)]).append(row)
    result = list(no_guide)
    removed = 0
    conflicts: list[str] = []
    for guide, items in by_guide.items():
        if len(items) == 1:
            result.extend(items)
            continue
        fingerprints = {json.dumps(i, default=str, ensure_ascii=False, sort_keys=True) for i in items}
        if len(fingerprints) == 1:
            result.append(items[0]); removed += len(items) - 1
        else:
            conflicts.append(guide); result.extend(items)
    if conflicts and block_conflicts:
        raise ValueError("Nro Guia duplicado con datos diferentes: " + ", ".join(conflicts[:20]))
    return result, removed, conflicts


def _audit_rows(original_count, removed_01, rows, unknown_services, ambiguous_states, duplicate_removed, duplicate_conflicts):
    return {
        "original_rows": original_count,
        "removed_-01": removed_01,
        "final_rows": len(rows),
        "duplicate_identical_removed": duplicate_removed,
        "duplicate_conflicts": duplicate_conflicts,
        "services": dict(Counter((r.get("Servicio") or "<VACIO>") for r in rows)),
        "remitos_47": sum(1 for r in rows if remito_as_string(r.get("Remito")).startswith("47")),
        "unknown_services": sorted(unknown_services),
        "states": dict(Counter((str(r.get("Estado")).strip() if r.get("Estado") not in (None, "") else "<VACIO>") for r in rows)),
        "ambiguous_states": sorted(ambiguous_states),
        "gestion": dict(Counter(management_result(r.get("Estado")) or "<VACIO>" for r in rows)),
    }


def _read_xlsx_portable(path: Path) -> tuple[list[str], list[list[Any]]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        data = [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    # Reuse the same header detector through a temporary CSV-like matrix path.
    expected = {normalize_key(h) for h in EXPECTED_HEADERS}
    best_idx = -1; best_score = -1
    for idx, row in enumerate(data[:10]):
        keys = {normalize_key(v) for v in row if v not in (None, "")}
        score = len(keys & expected)
        if score > best_score:
            best_idx = idx; best_score = score
    if best_idx < 0 or best_score < 4:
        raise ValueError("No pude identificar de forma confiable la fila de encabezados.")
    headers = [str(v).strip() if v is not None else "" for v in data[best_idx]]
    rows = data[best_idx + 1:]
    while rows and all(v in (None, "") for v in rows[-1]): rows.pop()
    return headers, rows


def _filename_seller_name(seller: str) -> str:
    return "PINTURERIAS MM - TIMARO" if seller == "PINTURERIAS MM / TIMARO" else seller


def _process_batch_portable(cfg: dict, run: RunContext, raw_files: list[Path], expected_sellers: set[str], logger) -> dict:
    template = resolve_path(cfg, "template")
    allowed_sellers = {s["seller"] for s in seller_configs(cfg)}
    alias_map = build_alias_map(cfg, normalize_key)
    safety = cfg.get("reportes", {}).get("safety", {})
    grouped: dict[str, list[dict]] = defaultdict(list)
    source_meta = defaultdict(lambda: {"files": [], "hashes": [], "original": 0, "missing": set(), "duplicate_headers": [], "seller_evidence": []})
    result = {"reports": {}, "seller_audits": {}, "blocked": []}

    for path in raw_files:
        try:
            if path.suffix.lower() == ".csv": headers, raw_rows = read_csv_file(path)
            elif path.suffix.lower() in {".xlsx", ".xlsm"}: headers, raw_rows = _read_xlsx_portable(path)
            else: raise ValueError(f"Extensión no soportada en servidor: {path.suffix}")
            rows, dup_headers = rows_to_dicts(headers, raw_rows)
            if not rows: raise ValueError("Archivo sin filas de datos.")
            seller_raw, evidence = resolve_seller_from_rows(rows, alias_map)
            seller = alias_map.get(normalize_key(seller_raw), canonical_seller_name(seller_raw))
            if seller not in allowed_sellers: raise ValueError(f"Seller no configurado: {seller!r}")
            grouped[seller].extend(rows)
            meta = source_meta[seller]
            meta["files"].append(path.name); meta["hashes"].append(sha256_file(path)); meta["original"] += len(rows)
            meta["duplicate_headers"].extend(dup_headers); meta["seller_evidence"].append({"file": path.name, "evidence": evidence})
            header_keys = {normalize_key(h) for h in headers}
            meta["missing"].update(h for h in EXPECTED_HEADERS if normalize_key(h) not in header_keys)
        except Exception as exc:
            result["blocked"].append({"seller": "<sin identificar>", "file": path.name, "reason": str(exc)})

    detected = set(grouped)
    if detected != expected_sellers:
        missing = sorted(expected_sellers - detected); unexpected = sorted(detected - expected_sellers)
        if missing: result["blocked"].append({"seller": "<lote>", "reason": f"Sellers descargados que no fueron detectados en tablas: {missing}"})
        if unexpected: result["blocked"].append({"seller": "<lote>", "reason": f"Sellers inesperados detectados: {unexpected}"})

    reports_root = resolve_path(cfg, "reports") / run.date_ddmmyyyy
    reports_root.mkdir(parents=True, exist_ok=True)
    for seller, rows in grouped.items():
        meta = source_meta[seller]
        missing = meta["missing"]
        critical_missing = [h for h in CRITICAL_HEADERS if h in missing]
        if critical_missing and safety.get("block_missing_critical_columns", True):
            result["blocked"].append({"seller": seller, "reason": f"Faltan columnas críticas: {critical_missing}"}); continue
        normalized = []; removed_01 = 0; unknown_services = set(); ambiguous_states = set()
        for raw in rows:
            out, flags = normalize_row(raw)
            if out is None: removed_01 += 1; continue
            normalized.append(out)
            if flags["unknown_service"]: unknown_services.add(flags["unknown_service"])
            if flags["ambiguous_state"]: ambiguous_states.add(flags["ambiguous_state"])
        try:
            normalized, dup_removed, dup_conflicts = _deduplicate(normalized, safety.get("block_conflicting_duplicates", True))
            bad_01 = [remito_as_string(r.get("Remito")) for r in normalized if remito_as_string(r.get("Remito")).endswith("-01")]
            bad_47 = [remito_as_string(r.get("Remito")) for r in normalized if remito_as_string(r.get("Remito")).startswith("47") and r.get("Servicio") != "FLEX"]
            if bad_01 or bad_47: raise RuntimeError(f"Fallo auditoría previa: -01={bad_01[:5]}, 47_no_flex={bad_47[:5]}")
            if unknown_services and safety.get("block_unknown_service", False): raise RuntimeError(f"Servicios desconocidos: {sorted(unknown_services)}")
            if ambiguous_states and safety.get("block_ambiguous_state", False): raise RuntimeError(f"Estados ambiguos: {sorted(ambiguous_states)}")
            audit = _audit_rows(meta["original"], removed_01, normalized, unknown_services, ambiguous_states, dup_removed, dup_conflicts)
            audit.update({"selected_run_date": run.date_ddmmyyyy, "cache": "generated", "source_files": meta["files"], "source_hashes": meta["hashes"], "missing_columns": sorted(missing), "duplicate_headers": meta["duplicate_headers"], "seller_evidence": meta["seller_evidence"]})
            out = reports_root / f"{_filename_seller_name(seller)} {run.date_short}.xlsx"
            audit = write_report_portable(template, out, normalized, seller, audit)
            if audit["excel"]["errors"] and safety.get("block_formula_errors", True): raise RuntimeError(" | ".join(audit["excel"]["errors"]))
            result["reports"][seller] = str(out); result["seller_audits"][seller] = audit
            logger.info("[REPORTES WEB] OK %-28s -> %s", seller, out.name)
        except Exception as exc:
            result["blocked"].append({"seller": seller, "reason": str(exc)})
            logger.error("[REPORTES WEB] BLOQUEADO %s: %s", seller, exc)
    return result


def generate_reports_and_visits(selected_date: datetime, progress: Callable[[str, int, int], None] | None = None) -> dict[str, Any]:
    cfg = load_config()
    run_id = selected_date.strftime("web_reportes_%Y%m%d_") + datetime.now().strftime("%H%M%S")
    work_dir = resolve_path(cfg, "work") / run_id
    run = RunContext(run_id=run_id, selected_date=selected_date, work_dir=work_dir, dry_run=False)
    work_dir.mkdir(parents=True, exist_ok=True)
    state = StateDB(work_dir / "state.sqlite")
    from app.core.logging import setup_logging
    logger = setup_logging(resolve_path(cfg, "logs"), run_id, False)
    artifacts: list[dict[str, Any]] = []
    try:
        if progress: progress("Descargando reportes de Epresis…", 1, 4)
        results = asyncio.run(download_all(cfg, run, state, logger, visible=False))
        errors = {s: r.error for s, r in results.items() if r.status == "error"}
        downloaded = {s: r for s, r in results.items() if r.status == "downloaded"}
        no_data = sorted(s for s, r in results.items() if r.status == "no_data")
        if errors: raise RuntimeError("Epresis terminó con errores: " + "; ".join(f"{s}: {e}" for s, e in errors.items()))
        raw_files = [Path(r.local_file) for r in downloaded.values()]
        if progress: progress("Generando archivos de clientes…", 2, 4)
        processed = _process_batch_portable(cfg, run, raw_files, set(downloaded), logger)
        if processed.get("blocked"):
            reasons = "; ".join(f"{x.get('seller')}: {x.get('reason')}" for x in processed["blocked"][:10])
            raise RuntimeError("Hay reportes bloqueados: " + reasons)
        message_template = str((cfg.get("whatsapp") or {}).get("attachment_caption", "Buenas noches, adjunto el reporte del día {date}."))
        message = message_template.format(date=run.message_date)
        for seller, p in processed.get("reports", {}).items():
            artifacts.append({"kind": "report", "seller": seller, "path": str(p), "filename": Path(p).name, "message": message})

        if progress: progress("Generando VISITAS…", 3, 4)
        visits_status = "disabled"
        if (cfg.get("visitas") or {}).get("enabled", True):
            vd = asyncio.run(download_visits(cfg, run, logger, visible=False))
            visits_status = vd.status
            if vd.status == "error": raise RuntimeError("VISITAS terminó con error: " + str(vd.error))
            if vd.status == "downloaded":
                info = convert_visits_csv_to_xlsx_portable(cfg, run, Path(vd.local_file), logger)
                vp = Path(info["path"])
                artifacts.append({"kind": "visitas", "seller": "VISITAS", "path": str(vp), "filename": vp.name, "message": str((cfg.get("visitas") or {}).get("whatsapp_message", ""))})
                visits_status = "generated"
            elif vd.status == "no_data": visits_status = "no_data"

        if progress: progress("Preparando descarga conjunta…", 4, 4)
        bundle = resolve_path(cfg, "reports") / run.date_ddmmyyyy / f"SMARTPOST REPORTES Y VISITAS {run.date_short}.zip"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in artifacts:
                zf.write(item["path"], arcname=item["filename"])
        artifacts.append({"kind": "all", "seller": "TODOS", "path": str(bundle), "filename": bundle.name, "message": ""})
        return {"date": run.date_ddmmyyyy, "no_data": no_data, "visitas_status": visits_status, "artifacts": artifacts}
    finally:
        state.close()
