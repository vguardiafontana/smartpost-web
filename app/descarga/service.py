from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path, report_seller_configs
from app.core.models import RunContext
from app.core.dates import seller_date_range
from app.core.state import StateDB
from app.core.utils import sha256_file
from app.core.async_utils import ordered_map
from .auth import ensure_authenticated, extract_csrf_token, navigate_to_guide_search
from .epresis_api import EpresisAPI, NoDataDetected, SellerResult, SessionExpired, csv_has_data_rows



async def _run_once(cfg: dict, run: RunContext, state: StateDB, logger, visible: bool = False) -> dict[str, SellerResult]:
    settings = epresis_settings(cfg)
    sellers = report_seller_configs(cfg, run.selected_date)
    if run.selected_date.weekday() == 5:
        logger.info("[REPORTES] Sábado seleccionado: se procesarán solo %s", ", ".join(str(s.get("seller")) for s in sellers))
    raw_dir = run.work_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, SellerResult] = {}

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
            await ensure_authenticated(page, settings, logger.getChild("EPRESIS"))

            api = EpresisAPI(context.request, settings, "", logger.getChild("EPRESIS"), referer=page.url or settings["base_url"])
            cache = state.client_cache_dict()
            resolved: list[tuple[dict, int, str]] = []
            async def resolve(scfg):
                return await api.resolve_client(scfg, cache)

            clients = await ordered_map(sellers, resolve, concurrency=3)
            for scfg, client in zip(sellers, clients):
                seller = scfg["seller"]
                if isinstance(client, Exception):
                    raise client
                cid, empresa = client
                state.save_client(seller, cid, empresa)
                resolved.append((scfg, cid, empresa))
                logger.info("[EPRESIS] Cliente %-28s -> %s (%s)", seller, cid, empresa)

            guides_url = await navigate_to_guide_search(page, settings, logger.getChild("EPRESIS"))
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger.getChild("EPRESIS"), referer=guides_url)

            for scfg, cid, empresa in resolved:
                results[scfg["seller"]] = SellerResult(seller=scfg["seller"], cliente_id=cid, empresa=empresa)
                if scfg.get("date_mode") == "month_to_selected":
                    logger.info("[EPRESIS] Rango especial %-28s -> %s", scfg["seller"], seller_date_range(scfg, run.selected_date))

            async def schedule(scfg: dict, cid: int, empresa: str):
                seller = scfg["seller"]
                date_range = seller_date_range(scfg, run.selected_date)
                try:
                    if settings.get("perform_filter_before_export", True):
                        filtered = await api.filter(cid, date_range)
                        count = api.filter_result_count(filtered)
                        if count == 0:
                            results[seller].status = "no_data"
                            logger.warning("[EPRESIS] SIN GUÍAS: %-28s", seller)
                            return {"_skip_no_data": True}
                        if count is not None:
                            logger.info("[EPRESIS] Filtro %-28s -> %d guía(s)", seller, count)
                    initial = await api.export_call(cid, date_range)
                    results[seller].job_id = initial.get("job_id")
                    logger.info("[EPRESIS] Export programado %-28s job=%s status=%s", seller, initial.get("job_id"), initial.get("status"))
                    return initial
                except SessionExpired:
                    raise
                except Exception as exc:
                    results[seller].status = "error"
                    results[seller].error = str(exc)
                    logger.error("[EPRESIS] ERROR programando %s: %s", seller, exc)
                    return None

            async def finish(item, initial):
                scfg, cid, empresa = item
                seller = scfg["seller"]
                if initial is None or initial.get("_skip_no_data"):
                    return
                date_range = seller_date_range(scfg, run.selected_date)
                try:
                    ready = await api.wait_for_export(cid, date_range, initial)
                    results[seller].job_id = ready.get("job_id") or results[seller].job_id
                    results[seller].remote_file = ready.get("file")
                    path = await api.download(ready, raw_dir)
                    if settings.get("skip_header_only_files", True) and path.suffix.lower() == ".csv" and not csv_has_data_rows(path):
                        results[seller].status = "no_data"
                        path.unlink(missing_ok=True)
                        logger.warning("[EPRESIS] SIN GUÍAS: %-28s (archivo solo con encabezado)", seller)
                        return
                    results[seller].status = "downloaded"
                    results[seller].local_file = str(path)
                    results[seller].bytes = path.stat().st_size
                    results[seller].sha256 = sha256_file(path)
                    logger.info("[EPRESIS] LISTO %-28s -> %s (%d bytes)", seller, path.name, path.stat().st_size)
                except NoDataDetected as exc:
                    results[seller].status = "no_data"
                    results[seller].error = None
                    logger.warning("[EPRESIS] SIN GUÍAS: %-28s (%s)", seller, exc)
                except SessionExpired:
                    raise
                except Exception as exc:
                    results[seller].status = "error"
                    results[seller].error = str(exc)
                    logger.error("[EPRESIS] ERROR finalizando %s: %s", seller, exc)

            async def download_one(item):
                # A ready export can download while later sellers are scheduled.
                # EpresisAPI still serializes export calls and respects HTTP 429.
                await finish(item, await schedule(*item))

            await asyncio.gather(*(download_one(item) for item in resolved))
            return results
        finally:
            await context.close()


async def download_all(cfg: dict, run: RunContext, state: StateDB, logger, visible: bool = False) -> dict[str, SellerResult]:
    """Download the complete Epresis batch.

    One automatic full retry is allowed only for an expired session.  HTTP 429
    retry/backoff remains inside EpresisAPI and does not restart the whole run.
    """
    for attempt in (1, 2):
        try:
            results = await _run_once(cfg, run, state, logger, visible=visible)
            downloaded = sum(r.status == "downloaded" for r in results.values())
            no_data = sum(r.status == "no_data" for r in results.values())
            errors = [r for r in results.values() if r.status == "error"]
            logger.info("[EPRESIS] Resumen: %d descargados | %d sin guías | %d errores", downloaded, no_data, len(errors))
            return results
        except SessionExpired as exc:
            if attempt == 2:
                raise
            logger.warning("[EPRESIS] Sesión expirada durante el lote. Reintentando una vez: %s", exc)
    raise RuntimeError("No se pudo completar la descarga Epresis.")
