from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.core.config import load_config, resolve_path
from app.core.logging import setup_logging
from app.core.models import RunContext
from app.core.state import StateDB
from app.pipeline.orchestrator import run_pipeline


class GuiLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__(logging.INFO)
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(self.format(record))
        except Exception:
            pass


class PipelineWorker(QObject):
    log_line = Signal(str)
    stage = Signal(str, str, object)
    finished = Signal(int, object, str)

    def __init__(self, selected_date, dry_run: bool):
        super().__init__()
        self.selected_date = selected_date
        self.dry_run = dry_run

    @Slot()
    def run(self):
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        state = None
        try:
            cfg = load_config()
            work_dir = resolve_path(cfg, "work") / run_id
            ctx = RunContext(run_id=run_id, selected_date=self.selected_date, work_dir=work_dir, dry_run=self.dry_run)
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            state = StateDB(resolve_path(cfg, "state_db"))

            def progress(stage, status, payload):
                self.stage.emit(stage, status, payload)

            code = run_pipeline(cfg, ctx, state, logger, progress_callback=progress)
            summary_path = resolve_path(cfg, "logs") / f"run_summary_{run_id}.json"
            summary = {}
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            detail = str(summary.get("fatal_error", ""))
            self.finished.emit(code, summary, detail)
        except Exception:
            detail = traceback.format_exc()
            self.finished.emit(1, {}, detail)
        finally:
            if state is not None:
                state.close()


class WhatsAppLoginWorker(QObject):
    finished = Signal(bool, str)

    @Slot()
    def run(self):
        try:
            from app.delivery.whatsapp import login_only_gui
            cfg = load_config()
            asyncio.run(login_only_gui(cfg))
            self.finished.emit(True, "WhatsApp quedó vinculado correctamente.")
        except Exception:
            self.finished.emit(False, traceback.format_exc())

class DenunciasLookupWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, object, str)

    def __init__(self, entries):
        super().__init__()
        self.entries = entries

    @Slot()
    def run(self):
        try:
            from app.denuncias.service import resolve_shipments_and_driver, apply_saved_driver_profile
            cfg = load_config()
            run_id = datetime.now().strftime("denuncia_lookup_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            shipments, driver = asyncio.run(resolve_shipments_and_driver(cfg, self.entries, logger.getChild("DENUNCIAS")))
            driver = apply_saved_driver_profile(cfg, driver)
            self.finished.emit(True, [s.to_dict() for s in shipments], driver.__dict__, "")
        except Exception:
            self.finished.emit(False, [], {}, traceback.format_exc())


class DenunciasSubmitWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, shipments, driver, incident, narrative, dry_run: bool, send_whatsapp: bool = True):
        super().__init__()
        self.shipments = shipments
        self.driver = driver
        self.incident = incident
        self.narrative = narrative
        self.dry_run = dry_run
        self.send_whatsapp = send_whatsapp

    @Slot()
    def run(self):
        state = None
        try:
            from app.denuncias.gba_form import submit_gba_denuncia
            from app.denuncias.whatsapp import send_denuncia_pdf
            from app.denuncias.models import Driver
            from app.denuncias.service import save_driver_profile
            cfg = load_config()
            run_id = datetime.now().strftime("denuncia_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            state = StateDB(resolve_path(cfg, "state_db"))
            driver_obj = Driver(**self.driver)
            save_driver_profile(cfg, driver_obj)
            selected = datetime.strptime(self.incident["date"], "%d/%m/%Y")
            work_dir = resolve_path(cfg, "work") / run_id
            ctx = RunContext(run_id=run_id, selected_date=selected, work_dir=work_dir, dry_run=self.dry_run)
            self.log_line.emit("Iniciando formulario de Denuncias de Provincia…")
            pdf = asyncio.run(submit_gba_denuncia(cfg, self.driver, self.incident, self.narrative, logger.getChild("GBA"), dry_run=self.dry_run))
            summary = {"dry_run": self.dry_run, "send_whatsapp": self.send_whatsapp, "pdf": str(pdf) if pdf else "", "whatsapp": []}
            if pdf is not None and not self.dry_run:
                from app.denuncias.history import save_history
                save_history(pdf, self.shipments, cfg)
            if pdf is not None and not self.dry_run and self.send_whatsapp:
                grouped = {}
                for s in self.shipments:
                    seller = str(s.get("seller", "")).strip()
                    remito = str(s.get("remito", "")).strip()
                    if seller and remito:
                        grouped.setdefault(seller, []).append(remito)
                summary["whatsapp"] = asyncio.run(send_denuncia_pdf(Path(pdf), grouped, cfg, state, ctx, logger.getChild("WHATSAPP")))
            self.finished.emit(True, summary, "")
        except Exception:
            self.finished.emit(False, {}, traceback.format_exc())
        finally:
            if state is not None:
                try:
                    state.close()
                except Exception:
                    pass

class CambioEstadoAnalyzeWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, identifiers):
        super().__init__()
        self.identifiers = list(identifiers or [])

    @Slot()
    def run(self):
        try:
            from app.cambio_estado.service import analyze_identifiers
            cfg = load_config()
            run_id = datetime.now().strftime("cambio_estado_analisis_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            rows = asyncio.run(analyze_identifiers(cfg, self.identifiers, logger.getChild("CAMBIO_ESTADO")))
            self.finished.emit(True, rows, "")
        except Exception:
            self.finished.emit(False, [], traceback.format_exc())


class CambioEstadoApplyWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, analyzed_rows, state_id: int):
        super().__init__()
        self.analyzed_rows = list(analyzed_rows or [])
        self.state_id = int(state_id)

    @Slot()
    def run(self):
        try:
            from app.cambio_estado.service import apply_state_change
            cfg = load_config()
            run_id = datetime.now().strftime("cambio_estado_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            rows = asyncio.run(apply_state_change(cfg, self.analyzed_rows, self.state_id, logger.getChild("CAMBIO_ESTADO")))
            self.finished.emit(True, rows, "")
        except Exception:
            self.finished.emit(False, [], traceback.format_exc())


class CambioEstadoDirectWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, identifiers, state_id: int):
        super().__init__()
        self.identifiers = list(identifiers or [])
        self.state_id = int(state_id)

    @Slot()
    def run(self):
        try:
            from app.cambio_estado.service import analyze_identifiers, apply_state_change
            cfg = load_config()
            run_id = datetime.now().strftime("cambio_estado_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            self.log_line.emit(f"Resolviendo {len(self.identifiers)} identificador(es)…")
            analyzed = asyncio.run(analyze_identifiers(cfg, self.identifiers, logger.getChild("CAMBIO_ESTADO")))
            resolved = [r for r in analyzed if r.get("resolution_status") == "resolved" and r.get("retiro_id")]
            if resolved:
                self.log_line.emit(f"Se encontraron {len(resolved)} guía(s) única(s). Aplicando el estado seleccionado…")
                changed = asyncio.run(apply_state_change(cfg, analyzed, self.state_id, logger.getChild("CAMBIO_ESTADO")))
            else:
                changed = []
            by_id = {int(r["retiro_id"]): r for r in changed if r.get("retiro_id")}
            merged = []
            for row in analyzed:
                item = dict(row)
                if item.get("resolution_status") == "resolved" and item.get("retiro_id"):
                    item.update(by_id.get(int(item["retiro_id"]), {}))
                merged.append(item)
            self.finished.emit(True, merged, "")
        except Exception:
            self.finished.emit(False, [], traceback.format_exc())


class WhatsAppArchiveToggleWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, mode="auto"):
        super().__init__()
        self.mode = mode

    @Slot()
    def run(self):
        try:
            from app.delivery.chat_archive import toggle_company_chats
            cfg = load_config()
            run_id = datetime.now().strftime("whatsapp_chats_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            result = asyncio.run(toggle_company_chats(cfg, logger.getChild("WHATSAPP_CHATS"), mode=self.mode))
            self.finished.emit(True, result, "")
        except Exception:
            self.finished.emit(False, {}, traceback.format_exc())


class BusquedaGuiasWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, identifiers):
        super().__init__()
        self.identifiers = list(identifiers or [])

    @Slot()
    def run(self):
        try:
            from app.busqueda_guias.service import search_shipments
            cfg = load_config()
            run_id = datetime.now().strftime("busqueda_guias_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            rows = asyncio.run(search_shipments(cfg, self.identifiers, logger.getChild("BUSQUEDA_GUIAS")))
            self.finished.emit(True, rows, "")
        except Exception:
            self.finished.emit(False, [], traceback.format_exc())


class CambioEstadoV2Worker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, identifiers, state_id: int, selected_date=None):
        super().__init__()
        self.identifiers = list(identifiers or [])
        self.state_id = int(state_id)
        self.selected_date = selected_date

    @Slot()
    def run(self):
        try:
            from app.cambio_estado_v2.service import change_state_v2
            cfg = load_config()
            run_id = datetime.now().strftime("cambio_estado_v2_%Y%m%d_%H%M%S")
            handler = GuiLogHandler(self.log_line.emit)
            logger = setup_logging(resolve_path(cfg, "logs"), run_id, False, extra_handlers=[handler])
            rows = asyncio.run(change_state_v2(cfg, self.identifiers, self.state_id, logger.getChild("CAMBIO_ESTADO_V2"), selected_date=self.selected_date))
            self.finished.emit(True, rows, "")
        except Exception:
            self.finished.emit(False, [], traceback.format_exc())
