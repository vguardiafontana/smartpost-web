from __future__ import annotations

from pathlib import Path

from playwright.async_api import async_playwright

from app.core.config import resolve_path, seller_map
from app.core.models import RunContext
from app.core.state import StateDB
from app.delivery.whatsapp import wait_until_logged_in, send_one, _wa_perf
from app.denuncias.messages import seller_message
import re
import unicodedata


async def send_denuncia_pdf(pdf_path: Path, grouped_remitos: dict[str, list[str]], cfg: dict, state: StateDB, run: RunContext, logger):
    dcfg = cfg.get("denuncias") or {}
    wa_cfg = cfg.get("whatsapp") or {}
    general_group = str(dcfg.get("whatsapp_group", "CONSULTAS / Operación nocturna")).strip()
    if not general_group:
        raise RuntimeError("Falta el grupo general de WhatsApp para Denuncias.")
    sellers = seller_map(cfg)
    def norm_name(value: str) -> str:
        t = unicodedata.normalize("NFKD", str(value or ""))
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return re.sub(r"[^A-Z0-9]+", " ", t.upper()).strip()
    custom_groups = {}
    for item in dcfg.get("seller_groups") or []:
        name = str(item.get("seller", "")).strip()
        group = str(item.get("whatsapp_group", "")).strip()
        if name and group:
            custom_groups[norm_name(name)] = group
    singular = str(dcfg.get("seller_message_singular", "Buenas noches, lamentamos informar que el siguiente envío, remito {remito}, se encuentra en estado siniestrado. Adjuntamos la denuncia correspondiente."))
    plural = str(dcfg.get("seller_message_plural", "Buenas noches, lamentamos informar que los siguientes envíos se encuentran en estado siniestrado:\n\n{remitos}\n\nAdjuntamos la denuncia correspondiente."))
    settings = {
        "whatsapp": {"browser": wa_cfg.get("browser", "chromium"), "attachment_caption": ""},
        "performance": {"whatsapp": wa_cfg.get("performance", {})},
    }
    profile = resolve_path(cfg, "whatsapp_profile")
    screenshots = resolve_path(cfg, "logs") / "whatsapp_screens"
    auto_send = bool(wa_cfg.get("auto_send", True)) and not run.dry_run
    results = []

    async with async_playwright() as p:
        browser_type = getattr(p, wa_cfg.get("browser", "chromium"))
        context = await browser_type.launch_persistent_context(str(profile), headless=False, viewport={"width":1365,"height":900})
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await wait_until_logged_in(page)
            # General operations group: PDF only.
            results.append(await send_one(page, pdf_path, "DENUNCIA", general_group, auto_send, screenshots, settings, state, run, message_template=""))
            between_ms = int(_wa_perf(settings, "between_sends_ms", 150))
            if between_ms > 0: await page.wait_for_timeout(between_ms)

            for seller, remitos in grouped_remitos.items():
                group = custom_groups.get(norm_name(seller), "")
                if not group:
                    scfg = sellers.get(seller)
                    group = str((scfg or {}).get("whatsapp_group", "")).strip()
                if not group:
                    raise RuntimeError(
                        f"Falta el grupo de WhatsApp del seller {seller}. "
                        "Configurá ese seller en Configuración → Denuncias → Grupos adicionales."
                    )
                message = seller_message(remitos, singular, plural)
                res = await send_one(page, pdf_path, f"DENUNCIA {seller}", group, auto_send, screenshots, settings, state, run, message_template=message)
                results.append(res)
                logger.info("[DENUNCIAS][WHATSAPP] %s -> %s (%s)", seller, group, res.get("status"))
                if between_ms > 0: await page.wait_for_timeout(between_ms)
        finally:
            await context.close()
    return results
