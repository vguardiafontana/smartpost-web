from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

import pythoncom
import win32com.client

from app.core.config import build_alias_map, resolve_path, seller_configs
from app.core.models import RunContext
from app.core.state import StateDB
from app.core.utils import sha256_file
from app.reportes.excel_report import write_report
from .io_sources import read_csv_file, read_xlsx_via_excel, rows_to_dicts
from .rules import (
    CRITICAL_HEADERS,
    EXPECTED_HEADERS,
    canonical_seller_name,
    management_result,
    normalize_key,
    normalize_row,
    remito_as_string,
    resolve_seller_from_rows,
)

VALID_EXTS = {".csv", ".xlsx", ".xls", ".xlsm"}
ENGINE_VERSION = "unified-1.0-report-v2.7"


def make_excel_app():
    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.ScreenUpdating = False
    excel.EnableEvents = False
    try:
        excel.Calculation = -4135  # xlCalculationManual
        excel.CalculateBeforeSave = False
        excel.DisplayStatusBar = False
        excel.AskToUpdateLinks = False
    except Exception:
        pass
    return excel


def close_excel(excel) -> None:
    try:
        excel.Quit()
    finally:
        pythoncom.CoUninitialize()


def filename_seller_name(seller: str) -> str:
    return "PINTURERIAS MM - TIMARO" if seller == "PINTURERIAS MM / TIMARO" else seller


def _deduplicate(rows: list[dict], block_conflicts: bool) -> tuple[list[dict], int, list[str]]:
    by_guide = defaultdict(list)
    no_guide = []
    for row in rows:
        guide = row.get("Nro Guia")
        if guide in (None, ""):
            no_guide.append(row)
        else:
            by_guide[str(guide)].append(row)
    result = list(no_guide)
    removed = 0
    conflicts = []
    for guide, items in by_guide.items():
        if len(items) == 1:
            result.extend(items)
            continue
        fingerprints = {json.dumps(i, default=str, ensure_ascii=False, sort_keys=True) for i in items}
        if len(fingerprints) == 1:
            result.append(items[0])
            removed += len(items) - 1
        else:
            conflicts.append(guide)
            result.extend(items)
    if conflicts and block_conflicts:
        raise ValueError("Nro Guia duplicado con datos diferentes: " + ", ".join(conflicts[:20]))
    return result, removed, conflicts


def _audit_rows(original_count, removed_01, rows, unknown_services, ambiguous_states, duplicate_removed, duplicate_conflicts):
    services = Counter((r.get("Servicio") or "<VACIO>") for r in rows)
    states = Counter((str(r.get("Estado")).strip() if r.get("Estado") not in (None, "") else "<VACIO>") for r in rows)
    mgmt = Counter(management_result(r.get("Estado")) or "<VACIO>" for r in rows)
    starts47 = sum(1 for r in rows if remito_as_string(r.get("Remito")).startswith("47"))
    return {
        "original_rows": original_count,
        "removed_-01": removed_01,
        "final_rows": len(rows),
        "duplicate_identical_removed": duplicate_removed,
        "duplicate_conflicts": duplicate_conflicts,
        "services": dict(services),
        "remitos_47": starts47,
        "unknown_services": sorted(unknown_services),
        "states": dict(states),
        "ambiguous_states": sorted(ambiguous_states),
        "gestion": dict(mgmt),
    }


def _cache_key(seller: str, run: RunContext, source_hashes: list[str], prompt_hash: str, template_hash: str) -> str:
    raw = "|".join([ENGINE_VERSION, "dry" if run.dry_run else "live", seller, run.date_ddmmyyyy, *sorted(source_hashes), prompt_hash, template_hash])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _process_one_seller(excel, seller, all_rows, meta, safety, template, output, audit_base):
    missing = meta["missing"]
    critical_missing = [h for h in CRITICAL_HEADERS if h in missing]
    if critical_missing and safety.get("block_missing_critical_columns", True):
        return None, None, f"Faltan columnas críticas: {critical_missing}"

    normalized = []
    removed_01 = 0
    unknown_services = set()
    ambiguous_states = set()
    for raw in all_rows:
        out, flags = normalize_row(raw)
        if out is None:
            removed_01 += 1
            continue
        normalized.append(out)
        if flags["unknown_service"]:
            unknown_services.add(flags["unknown_service"])
        if flags["ambiguous_state"]:
            ambiguous_states.add(flags["ambiguous_state"])

    normalized, duplicate_removed, duplicate_conflicts = _deduplicate(
        normalized, safety.get("block_conflicting_duplicates", True)
    )

    bad_01 = [remito_as_string(r.get("Remito")) for r in normalized if remito_as_string(r.get("Remito")).endswith("-01")]
    bad_47 = [remito_as_string(r.get("Remito")) for r in normalized if remito_as_string(r.get("Remito")).startswith("47") and r.get("Servicio") != "FLEX"]
    if bad_01 or bad_47:
        return None, None, f"Fallo auditoría previa: -01={bad_01[:5]}, 47_no_flex={bad_47[:5]}"
    if unknown_services and safety.get("block_unknown_service", False):
        return None, None, f"Servicios desconocidos: {sorted(unknown_services)}"
    if ambiguous_states and safety.get("block_ambiguous_state", False):
        return None, None, f"Estados ambiguos: {sorted(ambiguous_states)}"

    audit = _audit_rows(meta["original"], removed_01, normalized, unknown_services, ambiguous_states, duplicate_removed, duplicate_conflicts)
    audit.update(audit_base)
    audit["source_files"] = meta["files"]
    audit["source_hashes"] = meta["hashes"]
    audit["missing_columns"] = sorted(missing)
    audit["duplicate_headers"] = meta["duplicate_headers"]
    audit["seller_evidence"] = meta["seller_evidence"]

    audit = write_report(excel, template, output, normalized, seller, audit)
    if audit["excel"]["errors"] and safety.get("block_formula_errors", True):
        return None, audit, " | ".join(audit["excel"]["errors"])
    return output, audit, None


def process_batch(cfg: dict, run: RunContext, state: StateDB, raw_files: list[Path], expected_sellers: set[str], logger) -> dict:
    started = time.perf_counter()
    prompt = resolve_path(cfg, "prompt")
    template = resolve_path(cfg, "template")
    actual_prompt = sha256_file(prompt)
    actual_template = sha256_file(template)
    expected_prompt = str(cfg.get("app", {}).get("prompt_sha256", ""))
    expected_template = str(cfg.get("app", {}).get("template_sha256", ""))
    if expected_prompt and actual_prompt != expected_prompt:
        raise RuntimeError("PROMPT_MAESTRO.md cambió. Actualizá las reglas/huella antes de procesar.")
    if expected_template and actual_template != expected_template:
        raise RuntimeError("TEMPLATE_REPORTE.xlsx cambió. Actualizá la huella en config.yaml antes de procesar.")

    allowed_sellers = {s["seller"] for s in seller_configs(cfg)}
    alias_map = build_alias_map(cfg, normalize_key)
    safety = cfg.get("reportes", {}).get("safety", {})
    grouped: dict[str, list[dict]] = defaultdict(list)
    source_meta = defaultdict(lambda: {"files": [], "hashes": [], "original": 0, "missing": set(), "duplicate_headers": [], "seller_evidence": []})
    result = {"reports": {}, "seller_audits": {}, "blocked": [], "performance": {}}

    excel = make_excel_app()
    try:
        read_started = time.perf_counter()
        for path in raw_files:
            try:
                if path.suffix.lower() == ".csv":
                    headers, raw_rows = read_csv_file(path)
                elif path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
                    headers, raw_rows = read_xlsx_via_excel(excel, path)
                else:
                    raise ValueError(f"Extensión no soportada: {path.suffix}")
                rows, dup_headers = rows_to_dicts(headers, raw_rows)
                if not rows:
                    raise ValueError("Archivo sin filas de datos.")
                seller_raw, evidence = resolve_seller_from_rows(rows, alias_map)
                seller = alias_map.get(normalize_key(seller_raw), canonical_seller_name(seller_raw))
                if seller not in allowed_sellers:
                    raise ValueError(f"Seller no configurado: {seller!r}")
                grouped[seller].extend(rows)
                meta = source_meta[seller]
                meta["files"].append(path.name)
                meta["hashes"].append(sha256_file(path))
                meta["original"] += len(rows)
                meta["duplicate_headers"].extend(dup_headers)
                meta["seller_evidence"].append({"file": path.name, "evidence": evidence})
                header_keys = {normalize_key(h) for h in headers}
                meta["missing"].update(h for h in EXPECTED_HEADERS if normalize_key(h) not in header_keys)
            except Exception as exc:
                result["blocked"].append({"seller": "<sin identificar>", "file": path.name, "reason": str(exc)})
        result["performance"]["input_read_seconds"] = round(time.perf_counter() - read_started, 3)

        detected = set(grouped)
        if detected != expected_sellers:
            missing = sorted(expected_sellers - detected)
            unexpected = sorted(detected - expected_sellers)
            if missing:
                result["blocked"].append({"seller": "<lote>", "reason": f"Sellers descargados que no fueron detectados en tablas: {missing}"})
            if unexpected:
                result["blocked"].append({"seller": "<lote>", "reason": f"Sellers inesperados detectados: {unexpected}"})

        reports_root = (resolve_path(cfg, "dry_run_reports") / run.date_ddmmyyyy / run.run_id) if run.dry_run else (resolve_path(cfg, "reports") / run.date_ddmmyyyy)
        reports_root.mkdir(parents=True, exist_ok=True)
        generation_started = time.perf_counter()
        for seller, rows in grouped.items():
            meta = source_meta[seller]
            out = reports_root / f"{filename_seller_name(seller)} {run.date_short}.xlsx"
            cache_key = _cache_key(seller, run, meta["hashes"], actual_prompt, actual_template)

            if (not run.dry_run) and cfg.get("reportes", {}).get("cache_enabled", True):
                cached = state.get_cached_report(cache_key)
                if cached:
                    cached_path = Path(cached["report_path"])
                    if cached_path.exists() and sha256_file(cached_path) == cached["report_sha256"]:
                        result["reports"][seller] = str(cached_path)
                        result["seller_audits"][seller] = {"cache": "reused", "source_files": meta["files"]}
                        logger.info("[REPORTES] CACHE %-28s -> %s", seller, cached_path.name)
                        continue

            seller_started = time.perf_counter()
            try:
                output, audit, error = _process_one_seller(
                    excel, seller, rows, meta, safety, template, out,
                    {"selected_run_date": run.date_ddmmyyyy, "cache": "generated"},
                )
                if audit is not None:
                    result["seller_audits"][seller] = audit
                if error:
                    result["blocked"].append({"seller": seller, "reason": error})
                    if out.exists():
                        quarantine = run.work_dir / "errores" / out.name
                        quarantine.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(out), str(quarantine))
                elif output is not None:
                    report_hash = sha256_file(output)
                    result["reports"][seller] = str(output)
                    if not run.dry_run:
                        state.save_cached_report(cache_key, seller, run.date_ddmmyyyy, output, report_hash)
                    logger.info("[REPORTES] OK %-28s -> %s (%.2fs)", seller, output.name, time.perf_counter() - seller_started)
            except Exception as exc:
                result["blocked"].append({"seller": seller, "reason": str(exc)})
                logger.error("[REPORTES] BLOQUEADO %s: %s", seller, exc)

        result["performance"]["generation_seconds"] = round(time.perf_counter() - generation_started, 3)
        result["performance"]["total_seconds"] = round(time.perf_counter() - started, 3)
        return result
    finally:
        close_excel(excel)
