from __future__ import annotations

import asyncio
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from app.core.config import resolve_path, seller_map
from app.core.models import RunContext
from app.core.state import StateDB
from app.core.utils import sha256_file

def _title_locator(root, title: str):
    # Keep Unicode/emoji literal; only escape characters significant inside a
    # double-quoted CSS attribute value.
    safe = str(title).replace("\\", "\\\\").replace('"', '\\"')
    return root.locator(f'span[title="{safe}"]')


async def _exact_title_matches(root, title: str):
    # Exact attribute selector avoids scanning every visible chat/title one by
    # one through Playwright, which was a surprisingly expensive round trip.
    loc = _title_locator(root, title)
    matches = []
    for i in range(await loc.count()):
        item = loc.nth(i)
        try:
            if await item.is_visible():
                matches.append(item)
        except Exception:
            pass
    return matches


def _wa_perf(settings: dict, key: str, default):
    return settings.get("performance", {}).get("whatsapp", {}).get(key, default)


async def _wait_first_visible(locators, timeout_ms: int, poll_ms: int = 60):
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        for loc in locators:
            item = await _first_visible(loc)
            if item is not None:
                return item
        await asyncio.sleep(poll_ms / 1000.0)
    return None

async def _first_visible(locator):
    count = await locator.count()
    for i in range(count):
        item = locator.nth(i)
        try:
            if await item.is_visible():
                return item
        except Exception:
            pass
    return None


async def wait_until_logged_in(page, timeout_ms: int = 120000):
    await page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded")
    try:
        await page.locator("#pane-side").wait_for(state="visible", timeout=timeout_ms)
        return
    except PlaywrightTimeoutError:
        raise RuntimeError("WhatsApp Web no quedó vinculado. Abrí Configuración → Vincular WhatsApp y escaneá el QR.")


async def find_search_box(page):
    candidates = [
        page.get_by_role("textbox", name=re.compile(r"buscar|search", re.I)),
        page.locator("#side div[contenteditable='true'][role='textbox']"),
        page.locator("div[contenteditable='true'][role='textbox']"),
    ]
    for loc in candidates:
        item = await _first_visible(loc)
        if item is not None:
            return item
    raise RuntimeError("No encontré la caja de búsqueda de WhatsApp Web.")


async def _clear_chat_search(page):
    """Return WhatsApp's left pane to a clean search state between retries."""
    try:
        search = await find_search_box(page)
        await search.click()
        try:
            await search.fill("")
        except Exception:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        await page.wait_for_timeout(250)
    except Exception:
        # Escape also closes transient menus / attachment previews that can
        # otherwise intercept the next search click.
        try:
            await page.keyboard.press("Escape")
            await page.keyboard.press("Escape")
        except Exception:
            pass


async def open_exact_group(page, group: str, settings: dict):
    # WhatsApp Web can take several seconds to refresh search results.  A single
    # 4.5 s attempt caused false "group not found" errors in production, so use
    # controlled retries while keeping the exact-name safety check.
    timeout_ms = max(15000, int(_wa_perf(settings, "search_result_timeout_ms", 15000)))
    attempts = max(1, int(_wa_perf(settings, "search_attempts", 2)))
    retry_pause_ms = max(250, int(_wa_perf(settings, "search_retry_pause_ms", 800)))
    poll_ms = int(_wa_perf(settings, "ui_poll_ms", 60))
    last_reason = ""

    for attempt in range(1, attempts + 1):
        await _clear_chat_search(page)
        search = await find_search_box(page)
        await search.click()
        try:
            await search.fill("")
            await search.fill(group)
        except Exception:
            await page.keyboard.press("Control+A")
            await page.keyboard.type(group)

        pane = page.locator("#pane-side")
        title_locator = _title_locator(pane, group)
        text_locator = pane.get_by_text(group, exact=True)
        item = await _wait_first_visible([title_locator, text_locator], timeout_ms, poll_ms)
        if item is None:
            last_reason = f"No apareció el grupo exacto '{group}' dentro de {timeout_ms} ms"
            if attempt < attempts:
                await page.wait_for_timeout(retry_pause_ms)
                continue
            break

        visible = await _exact_title_matches(pane, group)
        if not visible:
            exact = pane.get_by_text(group, exact=True)
            for i in range(await exact.count()):
                try:
                    if await exact.nth(i).is_visible():
                        visible.append(exact.nth(i))
                except Exception:
                    pass
        if len(visible) != 1:
            last_reason = f"Esperaba 1 grupo exacto '{group}' y encontré {len(visible)} coincidencias visibles"
            if attempt < attempts:
                await page.wait_for_timeout(retry_pause_ms)
                continue
            break

        await visible[0].click()
        header_root = page.locator("header")
        header_timeout = max(5000, int(_wa_perf(settings, "header_timeout_ms", 5000)))
        header_title = _title_locator(header_root, group)
        header_text = header_root.get_by_text(group, exact=True)
        header_item = await _wait_first_visible([header_title, header_text], header_timeout, poll_ms)
        if header_item is not None:
            header_matches = await _exact_title_matches(header_root, group)
            if header_matches or await header_text.count() >= 1:
                return

        last_reason = f"Abrí un chat pero el encabezado no confirma exactamente '{group}'"
        if attempt < attempts:
            await page.wait_for_timeout(retry_pause_ms)
            continue
        break

    await _clear_chat_search(page)
    raise RuntimeError(f"{last_reason}. Se hicieron {attempts} intento(s). No envío.")


async def attach_document(page, path: Path, settings: dict):
    # Validate the final report before giving it to WhatsApp.
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"El archivo final no existe: {path}")
    suffix = path.suffix.lower()
    if suffix not in {".xlsx", ".pdf"}:
        raise RuntimeError(f"El archivo final debe ser .xlsx o .pdf: {path.name}")
    if path.stat().st_size <= 0:
        raise RuntimeError(f"El archivo final está vacío: {path.name}")
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(path, "r") as z:
                bad = z.testzip()
                if bad:
                    raise RuntimeError(f"XLSX corrupto; entrada ZIP dañada: {bad}")
                names = set(z.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise RuntimeError("El archivo no tiene la estructura interna esperada de un XLSX.")
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"El archivo no es un XLSX válido: {path.name}") from exc
    else:
        if not path.read_bytes()[:5].startswith(b"%PDF-"):
            raise RuntimeError(f"El archivo no es un PDF válido: {path.name}")

    # Open WhatsApp's attachment menu.
    button_candidates = [
        page.locator("footer").get_by_role("button", name=re.compile(r"adjuntar|attach|agregar|add", re.I)),
        page.locator("footer [data-icon='plus-rounded']"),
        page.locator("footer [data-icon='clip']"),
    ]
    clicked = False
    for loc in button_candidates:
        item = await _first_visible(loc)
        if item is not None:
            await item.click()
            clicked = True
            break
    if not clicked:
        raise RuntimeError("No encontré el botón de adjuntar.")
    # IMPORTANT: use the DOCUMENT chooser, never the Photos/Videos chooser.
    # Previous versions accepted inputs containing image/* because of the '*'
    # character, which makes WhatsApp reject .xlsx as an unsupported media file.
    doc_regex = re.compile(r"^(documento|document)$", re.I)
    document_candidates = [
        page.get_by_role("button", name=doc_regex),
        page.get_by_role("menuitem", name=doc_regex),
        page.get_by_text(doc_regex, exact=True),
        page.locator("[aria-label*='documento' i]"),
        page.locator("[aria-label*='document' i]"),
        page.locator("[title*='documento' i]"),
        page.locator("[title*='document' i]"),
    ]

    menu_timeout = int(_wa_perf(settings, "attachment_menu_timeout_ms", 3500))
    chosen_menu_item = await _wait_first_visible(
        document_candidates, menu_timeout, int(_wa_perf(settings, "ui_poll_ms", 60))
    )

    uploaded = False
    if chosen_menu_item is not None:
        try:
            async with page.expect_file_chooser(timeout=5000) as chooser_info:
                await chosen_menu_item.click()
            chooser = await chooser_info.value
            await chooser.set_files(str(path))
            uploaded = True
        except PlaywrightTimeoutError:
            # Some WhatsApp builds do not emit a FileChooser event; fall through
            # to the strict document-input selection below.
            uploaded = False

    if not uploaded:
        # Strict fallback: only accept a generic/document file input.
        # Never choose image/*, video/* or audio/* inputs.
        inputs = page.locator("input[type='file']")
        count = await inputs.count()
        chosen = None
        debug_accepts = []
        for i in range(count):
            inp = inputs.nth(i)
            accept = (await inp.get_attribute("accept") or "").strip().lower()
            debug_accepts.append(accept or "<vacío>")
            media_only = any(token in accept for token in ("image/", "video/", "audio/")) and not any(
                token in accept for token in ("application/", ".xlsx", "officedocument", "*/*")
            )
            document_like = (
                accept in ("", "*", "*/*")
                or "application/" in accept
                or ".xlsx" in accept
                or "officedocument" in accept
            )
            if document_like and not media_only:
                chosen = inp
                break
        if chosen is None:
            raise RuntimeError(
                "No encontré el selector 'Documento' de WhatsApp. "
                f"Selectores de archivo detectados: {debug_accepts}. No envío."
            )
        await chosen.set_input_files(str(path))

    # Event-driven preview wait: continue as soon as the exact filename appears
    # instead of sleeping a fixed 1.5 seconds for every seller.
    preview_timeout = int(_wa_perf(settings, "preview_timeout_ms", 7000))
    try:
        await page.get_by_text(path.name, exact=True).first.wait_for(state="visible", timeout=preview_timeout)
    except Exception:
        unsupported = page.get_by_text(
            re.compile(r"not supported|no.*compatible|no.*admitid|no.*soportad", re.I)
        )
        bad_msg = await _first_visible(unsupported)
        if bad_msg is not None:
            try:
                txt = (await bad_msg.inner_text()).strip()
            except Exception:
                txt = "archivo no compatible"
            raise RuntimeError(f"WhatsApp rechazó el adjunto como no compatible: {txt}")
        raise RuntimeError(f"WhatsApp no muestra el nombre exacto del archivo '{path.name}' en la vista previa. No envío.")

    # A rejection can appear just before/alongside the preview; check once more.
    unsupported = page.get_by_text(
        re.compile(r"not supported|no.*compatible|no.*admitid|no.*soportad", re.I)
    )
    bad_msg = await _first_visible(unsupported)
    if bad_msg is not None:
        try:
            txt = (await bad_msg.inner_text()).strip()
        except Exception:
            txt = "archivo no compatible"
        raise RuntimeError(f"WhatsApp rechazó el adjunto como no compatible: {txt}")


async def set_attachment_caption(page, message: str):
    # Prefer explicit caption/comment accessible labels. If WhatsApp changes the
    # UI, fail closed rather than sending the document without the required text.
    explicit_candidates = [
        page.get_by_role("textbox", name=re.compile(r"comentario|caption|pie de foto|add a caption|añade un comentario|anadir un comentario", re.I)),
        page.locator("div[contenteditable='true'][role='textbox'][aria-label*='coment' i]"),
        page.locator("div[contenteditable='true'][role='textbox'][aria-label*='caption' i]"),
    ]
    target = None
    for loc in explicit_candidates:
        item = await _first_visible(loc)
        if item is not None:
            target = item
            break

    if target is None:
        # Conservative fallback: a visible contenteditable outside the left chat
        # list, with the attachment preview open. Avoid the main search box.
        all_boxes = page.locator("div[contenteditable='true'][role='textbox']")
        candidates = []
        for i in range(await all_boxes.count()):
            item = all_boxes.nth(i)
            try:
                if not await item.is_visible():
                    continue
                in_side = await item.evaluate("el => !!el.closest('#side')")
                if in_side:
                    continue
                aria = (await item.get_attribute("aria-label") or "").lower()
                if re.search(r"buscar|search", aria, re.I):
                    continue
                # Attachment preview normally places the caption outside the
                # standard chat footer. Give preference to non-footer boxes.
                in_footer = await item.evaluate("el => !!el.closest('footer')")
                candidates.append((1 if in_footer else 0, item))
            except Exception:
                pass
        candidates.sort(key=lambda x: x[0])
        if len(candidates) == 1:
            target = candidates[0][1]
        elif candidates:
            # Use the first non-footer candidate only when unique at that rank.
            best_rank = candidates[0][0]
            best = [item for rank, item in candidates if rank == best_rank]
            if len(best) == 1:
                target = best[0]

    if target is None:
        raise RuntimeError("No encontré de forma inequívoca el campo de comentario del adjunto. No envío.")

    await target.click()
    try:
        await target.fill(message)
    except Exception:
        await page.keyboard.press("Control+A")
        await page.keyboard.type(message)
    await asyncio.sleep(0)

    # Verify the exact caption text before allowing the send click.
    current = ""
    try:
        current = (await target.inner_text()).strip()
    except Exception:
        try:
            current = (await target.text_content() or "").strip()
        except Exception:
            current = ""
    current = re.sub(r"\s+", " ", current)
    expected = re.sub(r"\s+", " ", message.strip())
    if current != expected:
        raise RuntimeError(
            f"El comentario del adjunto no coincide exactamente. Esperado: '{expected}' / Detectado: '{current}'. No envío."
        )
    return target


async def click_send(page):
    candidates = [
        page.get_by_role("button", name=re.compile(r"enviar|send", re.I)),
        page.locator("[data-icon='send']"),
    ]
    for loc in candidates:
        item = await _first_visible(loc)
        if item is not None:
            await item.click()
            return
    raise RuntimeError("No encontré el botón Enviar en la vista previa.")




def _safe_filename_component(value: str) -> str:
    """Make a Windows-safe component for logs/screenshots only."""
    s = re.sub(r'[<>:"/\\|?*]+', ' - ', str(value))
    s = re.sub(r'\s+', ' ', s).strip(' .')
    return s or 'SELLER'

async def send_one(
    page,
    path: Path,
    seller: str,
    group: str,
    auto_send: bool,
    screenshots: Path,
    settings: dict,
    state: StateDB,
    run: RunContext,
    message_template: str | None = None,
):
    report_hash = sha256_file(path)
    if state.already_sent(report_hash, group):
        return {"status": "already_sent", "seller": seller, "group": group, "file": path.name}

    await open_exact_group(page, group, settings)
    await attach_document(page, path, settings)
    template = (
        settings.get("whatsapp", {}).get(
            "attachment_caption", "Buenas noches, adjunto el reporte del día {date}."
        )
        if message_template is None
        else str(message_template)
    )
    message = template.format(date=run.message_date)
    # VISITAS currently goes as a document with NO message. Empty caption is a
    # supported configuration value; do not force a textbox interaction.
    caption_target = None
    if message.strip():
        caption_target = await set_attachment_caption(page, message)
    screenshots.mkdir(parents=True, exist_ok=True)

    if not auto_send:
        result = {"status": "preview_only", "seller": seller, "group": group, "file": path.name, "message": message}
        if bool(_wa_perf(settings, "screenshot_preview", True)):
            shot = screenshots / f"PREVIEW_{_safe_filename_component(seller)}_{datetime.now().strftime('%H%M%S')}.png"
            await page.screenshot(path=str(shot), full_page=False)
            result["screenshot"] = str(shot)
        await page.keyboard.press("Escape")
        return result

    header_root = page.locator("header")
    header_matches = await _exact_title_matches(header_root, group)
    if not header_matches and await header_root.get_by_text(group, exact=True).count() < 1:
        raise RuntimeError(f"El grupo dejó de coincidir exactamente con '{group}' justo antes de enviar.")

    await click_send(page)
    try:
        target = caption_target if caption_target is not None else page.get_by_text(path.name, exact=True).first
        await target.wait_for(
            state="hidden",
            timeout=int(_wa_perf(settings, "send_commit_timeout_ms", 4500)),
        )
    except Exception:
        await page.wait_for_timeout(int(_wa_perf(settings, "post_send_fallback_ms", 500)))
    state.mark_sent(report_hash, group, seller, run.date_ddmmyyyy)
    result = {"status": "sent", "seller": seller, "group": group, "file": path.name, "message": message}
    if bool(_wa_perf(settings, "screenshot_sent", False)):
        shot = screenshots / f"ENVIADO_{_safe_filename_component(seller)}_{datetime.now().strftime('%H%M%S')}.png"
        try:
            await page.screenshot(path=str(shot), full_page=False)
            result["screenshot"] = str(shot)
        except Exception as exc:
            result["screenshot_warning"] = str(exc)
    return result


async def send_reports(
    report_map: dict[str, Path],
    cfg: dict,
    state: StateDB,
    run: RunContext,
    logger,
    visits_path: Path | None = None,
) -> list[dict]:
    wa_cfg = cfg.get("whatsapp", {})
    settings = {
        "whatsapp": {
            "browser": wa_cfg.get("browser", "chromium"),
            "attachment_caption": wa_cfg.get("attachment_caption", "Buenas noches, adjunto el reporte del día {date}."),
        },
        "performance": {"whatsapp": wa_cfg.get("performance", {})},
    }
    sellers = seller_map(cfg)
    missing_groups = [s for s in report_map if not str(sellers.get(s, {}).get("whatsapp_group", "")).strip()]
    if missing_groups:
        raise RuntimeError("Faltan grupos de WhatsApp en config.yaml para: " + ", ".join(sorted(missing_groups)))
    visits_cfg = cfg.get("visitas") or {}
    visits_group = str(visits_cfg.get("whatsapp_group", "")).strip()
    if visits_path is not None and not visits_group:
        raise RuntimeError("Falta configurar el grupo de WhatsApp para VISITAS.")

    profile = resolve_path(cfg, "whatsapp_profile")
    screenshots = resolve_path(cfg, "logs") / "whatsapp_screens"
    auto_send = bool(wa_cfg.get("auto_send", True)) and not run.dry_run
    results_by_seller: dict[str, dict] = {}
    pending: list[tuple[str, Path, str]] = []

    async with async_playwright() as p:
        browser_type = getattr(p, wa_cfg.get("browser", "chromium"))
        context = await browser_type.launch_persistent_context(
            user_data_dir=str(profile), headless=False, viewport={"width": 1365, "height": 900}
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await wait_until_logged_in(page)

            # First pass: every seller gets a chance. Failures are queued, never
            # allowed to interrupt the rest of the batch.
            for seller, path in report_map.items():
                path = Path(path)
                group = str(sellers[seller]["whatsapp_group"]).strip()
                try:
                    res = await send_one(page, path, seller, group, auto_send, screenshots, settings, state, run)
                    results_by_seller[seller] = res
                    logger.info("[WHATSAPP] %-28s -> %s (%s)", seller, group, res["status"])
                except Exception as exc:
                    results_by_seller[seller] = {"status": "pending_retry", "seller": seller, "group": group, "file": path.name, "reason": str(exc), "attempt_round": 1}
                    pending.append((seller, path, group))
                    logger.warning("[WHATSAPP] PENDIENTE %s -> %s: %s", seller, group, exc)
                    await _clear_chat_search(page)
                between_ms = int(_wa_perf(settings, "between_sends_ms", 350))
                if between_ms > 0:
                    await page.wait_for_timeout(between_ms)

            # Final pass: retry only the pending sellers. Already-sent reports
            # are never touched again (and StateDB is an additional duplicate guard).
            if pending:
                retry_round_pause_ms = max(500, int(_wa_perf(settings, "pending_retry_pause_ms", 1800)))
                logger.warning("[WHATSAPP] Reintentando %d envío(s) pendientes al final del lote.", len(pending))
                await page.wait_for_timeout(retry_round_pause_ms)
                for seller, path, group in pending:
                    try:
                        await _clear_chat_search(page)
                        res = await send_one(page, path, seller, group, auto_send, screenshots, settings, state, run)
                        res["retried"] = True
                        results_by_seller[seller] = res
                        logger.info("[WHATSAPP] REINTENTO OK %-20s -> %s (%s)", seller, group, res["status"])
                    except Exception as exc:
                        fail = {"status": "error", "seller": seller, "group": group, "file": path.name, "reason": str(exc), "retried": True, "attempt_round": 2}
                        # Keep a diagnostic screenshot for the final failure only.
                        try:
                            screenshots.mkdir(parents=True, exist_ok=True)
                            shot = screenshots / f"ERROR_{_safe_filename_component(seller)}_{datetime.now().strftime('%H%M%S')}.png"
                            await page.screenshot(path=str(shot), full_page=False)
                            fail["screenshot"] = str(shot)
                        except Exception:
                            pass
                        results_by_seller[seller] = fail
                        logger.error("[WHATSAPP] ERROR FINAL %s -> %s: %s", seller, group, exc)
                    between_ms = int(_wa_perf(settings, "between_sends_ms", 350))
                    if between_ms > 0:
                        await page.wait_for_timeout(between_ms)

            # VISITAS remains last so its existing close grace period continues
            # to protect the final upload commit.
            visits_result = None
            if visits_path is not None:
                try:
                    res = await send_one(
                        page,
                        Path(visits_path),
                        "VISITAS",
                        visits_group,
                        auto_send,
                        screenshots,
                        settings,
                        state,
                        run,
                        message_template=str(visits_cfg.get("whatsapp_message", "")),
                    )
                    visits_result = res
                    logger.info("[WHATSAPP] %-28s -> %s (%s)", "VISITAS", visits_group, res["status"])
                    if auto_send and res.get("status") == "sent":
                        final_delay_ms = int(_wa_perf(settings, "final_visitas_close_delay_ms", 5000))
                        if final_delay_ms > 0:
                            logger.info("[WHATSAPP] Esperando %.1fs antes de cerrar WhatsApp tras VISITAS.", final_delay_ms / 1000.0)
                            await page.wait_for_timeout(final_delay_ms)
                except Exception as exc:
                    # One controlled retry for VISITAS too, without risking duplicates:
                    # StateDB returns already_sent if the first click committed.
                    logger.warning("[WHATSAPP] VISITAS pendiente; reintentando: %s", exc)
                    try:
                        await _clear_chat_search(page)
                        await page.wait_for_timeout(max(500, int(_wa_perf(settings, "pending_retry_pause_ms", 1800))))
                        res = await send_one(
                            page, Path(visits_path), "VISITAS", visits_group, auto_send,
                            screenshots, settings, state, run,
                            message_template=str(visits_cfg.get("whatsapp_message", "")),
                        )
                        res["retried"] = True
                        visits_result = res
                        logger.info("[WHATSAPP] REINTENTO OK VISITAS -> %s (%s)", visits_group, res["status"])
                    except Exception as exc2:
                        visits_result = {"status": "error", "seller": "VISITAS", "group": visits_group, "file": Path(visits_path).name, "reason": str(exc2), "retried": True}
                        logger.error("[WHATSAPP] ERROR FINAL VISITAS -> %s: %s", visits_group, exc2)

            results = [results_by_seller[s] for s in report_map if s in results_by_seller]
            if visits_result is not None:
                results.append(visits_result)

            ok_statuses = {"sent", "already_sent", "preview_only"}
            sent_n = sum(1 for x in results if x.get("status") in ok_statuses)
            fail_n = len(results) - sent_n
            logger.info("[WHATSAPP] Resumen final: %d correctos | %d pendientes/error.", sent_n, fail_n)
            return results
        finally:
            await context.close()


async def login_only_gui(cfg: dict, timeout_ms: int = 300000) -> None:
    """GUI-friendly WhatsApp login: opens bundled Chromium and waits for login.

    No stdin/console interaction is required. The user scans the QR in the opened
    browser window; the function returns once the chat list is detected.
    """
    profile = resolve_path(cfg, "whatsapp_profile")
    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile), headless=False, viewport={"width": 1365, "height": 900}
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded")
            await wait_until_logged_in(page, timeout_ms=timeout_ms)
        finally:
            await context.close()
