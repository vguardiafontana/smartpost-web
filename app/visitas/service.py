from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path
from app.core.models import RunContext
from app.core.utils import sha256_file
from app.descarga.auth import ensure_authenticated, extract_csrf_token, navigate_to_guide_search
from app.descarga.epresis_api import EpresisAPI, NoDataDetected, SessionExpired, csv_has_data_rows


@dataclass
class VisitsDownloadResult:
    status: str = "pending"  # downloaded | no_data | disabled | error
    local_file: str | None = None
    remote_file: str | None = None
    job_id: int | None = None
    rows_hint: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    error: str | None = None


def _state_ids(cfg: dict) -> list[int]:
    visits = cfg.get("visitas") or {}
    return [int(item["id"]) for item in (visits.get("estados") or [])]


async def _download_once(cfg: dict, run: RunContext, logger, visible: bool = False) -> VisitsDownloadResult:
    visits_cfg = cfg.get("visitas") or {}
    if not visits_cfg.get("enabled", True):
        return VisitsDownloadResult(status="disabled")

    state_ids = _state_ids(cfg)
    if not state_ids:
        return VisitsDownloadResult(status="error", error="No hay estados configurados para VISITAS.")

    settings = epresis_settings(cfg)
    raw_dir = run.work_dir / "visitas" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    date_text = run.date_slash

    async with async_playwright() as p:
        profile = resolve_path(cfg, "epresis_profile")
        profile.mkdir(parents=True, exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=(False if visible else bool(settings.get("headless", True))),
            accept_downloads=False,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_authenticated(page, settings, logger.getChild("VISITAS"))
            guides_url = await navigate_to_guide_search(page, settings, logger.getChild("VISITAS"))
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger.getChild("VISITAS"), referer=guides_url)

            logger.info(
                "[VISITAS] Buscando %s con estados: %s",
                run.date_slash,
                ", ".join(str(x) for x in state_ids),
            )

            filtered = await api.filter_visits(date_text, state_ids)
            count = api.filter_result_count(filtered)
            if count == 0:
                logger.warning("[VISITAS] Sin registros para %s", run.date_slash)
                return VisitsDownloadResult(status="no_data", rows_hint=0)
            if count is not None:
                logger.info("[VISITAS] Filtro -> %d registro(s)", count)

            initial = await api.export_visits_call(date_text, state_ids)
            logger.info(
                "[VISITAS] Export programado job=%s status=%s",
                initial.get("job_id"),
                initial.get("status"),
            )
            ready = await api.wait_for_visits_export(date_text, state_ids, initial)
            path = await api.download(ready, raw_dir)
            if path.suffix.lower() == ".csv" and not csv_has_data_rows(path):
                path.unlink(missing_ok=True)
                logger.warning("[VISITAS] Export sin filas de datos")
                return VisitsDownloadResult(status="no_data", rows_hint=0)

            result = VisitsDownloadResult(
                status="downloaded",
                local_file=str(path),
                remote_file=ready.get("file"),
                job_id=ready.get("job_id") or initial.get("job_id"),
                rows_hint=count,
                bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
            logger.info("[VISITAS] CSV listo -> %s (%d bytes)", path.name, path.stat().st_size)
            return result
        finally:
            await context.close()


async def download_visits(cfg: dict, run: RunContext, logger, visible: bool = False) -> VisitsDownloadResult:
    """Download the global VISITAS export with one automatic session retry."""
    for attempt in (1, 2):
        try:
            return await _download_once(cfg, run, logger, visible=visible)
        except NoDataDetected:
            return VisitsDownloadResult(status="no_data", rows_hint=0)
        except SessionExpired as exc:
            if attempt == 2:
                return VisitsDownloadResult(status="error", error=str(exc))
            logger.warning("[VISITAS] Sesión expirada. Reintentando una vez: %s", exc)
        except Exception as exc:
            logger.error("[VISITAS] ERROR: %s", exc)
            return VisitsDownloadResult(status="error", error=str(exc))
    return VisitsDownloadResult(status="error", error="No se pudo descargar VISITAS.")
