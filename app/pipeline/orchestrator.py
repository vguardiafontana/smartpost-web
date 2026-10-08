from __future__ import annotations

import asyncio
import json
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from app.core.config import resolve_path
from app.core.models import RunContext
from app.core.state import StateDB
from app.core.utils import zip_files
from app.descarga.service import download_all
from app.procesamiento.processor import process_batch
from app.delivery.whatsapp import send_reports
from app.visitas.excel import convert_visits_csv_to_xlsx
from app.visitas.service import download_visits


def _archive_raws(cfg: dict, run: RunContext, raw_files: list[Path], logger) -> Path | None:
    if not cfg.get("app", {}).get("archive_raw", True) or not raw_files:
        return None
    out = ((resolve_path(cfg, "dry_run_reports") / run.date_ddmmyyyy / run.run_id / f"CRUDOS {run.date_ddmmyyyy}.zip") if run.dry_run else (resolve_path(cfg, "raw_history") / f"CRUDOS {run.date_ddmmyyyy}.zip"))
    zip_files(raw_files, out, compression=zipfile.ZIP_DEFLATED)
    logger.info("[ARCHIVO] Crudos comprimidos -> %s", out)
    for p in raw_files:
        p.unlink(missing_ok=True)
    return out


def _cleanup_old_archives(cfg: dict, logger) -> None:
    days = int(cfg.get("app", {}).get("raw_retention_days", 0) or 0)
    if days <= 0:
        return
    folder = resolve_path(cfg, "raw_history")
    if not folder.exists():
        return
    cutoff = datetime.now().timestamp() - days * 86400
    for p in folder.glob("CRUDOS *.zip"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                logger.info("[LIMPIEZA] Eliminado histórico vencido: %s", p.name)
        except OSError:
            pass


def _create_reports_zip(cfg: dict, run: RunContext, reports: dict[str, str], logger) -> Path | None:
    if not cfg.get("reportes", {}).get("create_zip", True) or len(reports) <= 1:
        return None
    report_paths = [Path(p) for p in reports.values()]
    folder = report_paths[0].parent
    out = folder / f"REPORTES {run.date_short}.zip"
    zip_files(report_paths, out, compression=zipfile.ZIP_STORED)
    logger.info("[REPORTES] ZIP -> %s", out)
    return out


def _write_run_summary(cfg: dict, run: RunContext, payload: dict) -> None:
    p = resolve_path(cfg, "logs") / f"run_summary_{run.run_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def run_pipeline(cfg: dict, run: RunContext, state: StateDB, logger, visible_epresis: bool = False, progress_callback=None) -> int:
    started = time.perf_counter()

    def emit(stage: str, stage_status: str, **payload):
        # `payload` puede contener su propio campo `status` (por ejemplo
        # VISITAS: generated/no_data/disabled). Usar un nombre distinto para
        # el estado visual de la etapa evita el error:
        # "got multiple values for argument 'status'".
        if progress_callback:
            try:
                progress_callback(stage, stage_status, payload)
            except Exception:
                pass
    state.start_run(run.run_id, run.date_ddmmyyyy)
    run.work_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"run_id": run.run_id, "date": run.date_ddmmyyyy, "dry_run": run.dry_run}
    try:
        logger.info("========== SMARTPOST UNIFICADO ==========")
        logger.info("Fecha operativa: %s", run.date_ddmmyyyy)

        # 1) DESCARGA
        emit("epresis", "running")
        results = asyncio.run(download_all(cfg, run, state, logger, visible=visible_epresis))
        errors = {s: r.error for s, r in results.items() if r.status == "error"}
        no_data = sorted(s for s, r in results.items() if r.status == "no_data")
        downloaded = {s: r for s, r in results.items() if r.status == "downloaded"}
        summary["epresis"] = {"downloaded": sorted(downloaded), "no_data": no_data, "errors": errors}
        if errors:
            emit("epresis", "error", errors=errors, no_data=no_data, downloaded=sorted(downloaded))
            raise RuntimeError("Epresis terminó con errores: " + "; ".join(f"{s}: {e}" for s, e in errors.items()))
        emit("epresis", "ok", no_data=no_data, downloaded=sorted(downloaded))
        raw_files = [Path(r.local_file) for r in downloaded.values()]
        if not raw_files:
            raise RuntimeError("No se descargó ningún archivo con datos.")

        # 2) PROCESAMIENTO + REPORTE
        emit("reportes", "running")
        processed = process_batch(cfg, run, state, raw_files, set(downloaded), logger)
        summary["processing"] = processed
        if processed.get("blocked"):
            emit("reportes", "error", blocked=processed.get("blocked", []), reports=processed.get("reports", {}))
            reasons = "; ".join(f"{x.get('seller')}: {x.get('reason')}" for x in processed["blocked"][:10])
            raise RuntimeError("Hay reportes bloqueados. No se inicia WhatsApp. " + reasons)
        reports = processed.get("reports", {})
        if set(reports) != set(downloaded):
            raise RuntimeError(f"Lote inconsistente: descargados={sorted(downloaded)} reportes={sorted(reports)}")
        _create_reports_zip(cfg, run, reports, logger)
        emit("reportes", "ok", reports=reports)

        # 3) VISITAS (búsqueda global por estados, sin cliente)
        visits_path = None
        visits_raw = None
        if (cfg.get("visitas") or {}).get("enabled", True):
            emit("visitas", "running")
            visits_download = asyncio.run(download_visits(cfg, run, logger, visible=visible_epresis))
            summary["visitas"] = {
                "download_status": visits_download.status,
                "rows_hint": visits_download.rows_hint,
                "error": visits_download.error,
            }
            if visits_download.status == "error":
                emit("visitas", "error", error=visits_download.error)
                raise RuntimeError("VISITAS terminó con error: " + str(visits_download.error))
            if visits_download.status == "downloaded":
                visits_raw = Path(visits_download.local_file)
                visits_excel = convert_visits_csv_to_xlsx(cfg, run, visits_raw, logger)
                visits_path = Path(visits_excel["path"])
                summary["visitas"].update(visits_excel)
                emit("visitas", "ok", **summary["visitas"])
            elif visits_download.status == "no_data":
                summary["visitas"]["status"] = "no_data"
                emit("visitas", "ok", status="no_data", rows=0)
                logger.warning("[VISITAS] No hay registros. No se genera ni se envía archivo.")
            else:
                summary["visitas"]["status"] = visits_download.status
                emit("visitas", "ok", status=visits_download.status)
        else:
            summary["visitas"] = {"status": "disabled"}
            emit("visitas", "ok", status="disabled")

        # 4) WHATSAPP
        emit("whatsapp", "running")
        send_results = asyncio.run(
            send_reports(
                {s: Path(p) for s, p in reports.items()},
                cfg,
                state,
                run,
                logger,
                visits_path=visits_path,
            )
        )
        summary["whatsapp"] = send_results
        allowed = {"preview_only"} if run.dry_run else {"sent", "already_sent"}
        bad = [x for x in send_results if x.get("status") not in allowed]
        if bad:
            # WhatsApp delivery problems are now partial completion, not a fatal
            # pipeline crash. Reports are already generated and successful sends
            # must not be repeated on the next run. Keep exact pending details in
            # the run summary and UI while finishing/archiving the batch cleanly.
            summary["whatsapp_pending"] = [
                {"seller": x.get("seller"), "group": x.get("group"), "reason": x.get("reason", x.get("status"))}
                for x in bad
            ]
            logger.error(
                "[WHATSAPP] Finalizó con %d pendiente(s): %s",
                len(bad),
                "; ".join(f"{x.get('seller')}: {x.get('reason', x.get('status'))}" for x in bad[:10]),
            )
            emit("whatsapp", "error", results=send_results, pending=summary["whatsapp_pending"])
        else:
            emit("whatsapp", "ok", results=send_results)

        # Los reportes ya fueron generados y los envíos exitosos quedaron registrados.
        # Incluso con pendientes de WhatsApp, archivamos los crudos normalmente; el
        # detalle de pendientes permanece en run_summary y logs.
        archive_inputs = list(raw_files)
        if visits_raw is not None and visits_raw.exists():
            archive_inputs.append(visits_raw)
        _archive_raws(cfg, run, archive_inputs, logger)

        if run.dry_run:
            status = "dry_run_ok"
        elif bad:
            status = "partial_success"
        else:
            status = "success"
        visits_note = summary.get("visitas", {}).get("status") or summary.get("visitas", {}).get("download_status")
        state.finish_run(run.run_id, status, f"{len(reports)} reportes; {len(no_data)} sin guías; visitas={visits_note}; whatsapp_pendientes={len(bad)}")
        summary["status"] = status
        _write_run_summary(cfg, run, summary)
        _cleanup_old_archives(cfg, logger)
        if not cfg.get("app", {}).get("keep_failed_workdir", True):
            shutil.rmtree(run.work_dir, ignore_errors=True)
        else:
            # En éxito ya no necesitamos temporales; el resumen queda centralizado en logs/state.
            shutil.rmtree(run.work_dir, ignore_errors=True)
        logger.info(
            "TODO OK: %d reportes %s. VISITAS: %s. Sin guías: %s",
            len(reports),
            "preparados" if run.dry_run else "enviados",
            "sin registros" if summary.get("visitas", {}).get("status") == "no_data" else ("generado" if visits_path else "deshabilitado"),
            ", ".join(no_data) if no_data else "ninguno",
        )
        elapsed = time.perf_counter() - started
        logger.info("Tiempo total: %.2fs", elapsed)
        emit("pipeline", "ok", summary=summary, elapsed=elapsed)
        return 0
    except Exception as exc:
        state.finish_run(run.run_id, "error", str(exc))
        summary["fatal_error"] = str(exc)
        _write_run_summary(cfg, run, summary)
        logger.error("PIPELINE DETENIDO: %s", exc)
        logger.error("Los temporales de diagnóstico quedan en: %s", run.work_dir)
        emit("pipeline", "error", error=str(exc), summary=summary)
        return 1
