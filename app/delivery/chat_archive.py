from __future__ import annotations

import asyncio
import re
from datetime import datetime, time

from playwright.async_api import Locator, Page, async_playwright

from app.core.config import resolve_path
from app.delivery.whatsapp import wait_until_logged_in


_ARCHIVED_RE = re.compile(r"^(Archivados|Archived)$", re.I)
_ARCHIVE_RE = re.compile(r"^(Archivar chat|Archivar|Archive chat|Archive)$", re.I)
_UNARCHIVE_RE = re.compile(r"^(Desarchivar chat|Desarchivar|Unarchive chat|Unarchive)$", re.I)
_ARCHIVE_CONTAINS_RE = re.compile(r"\b(archivar|archive)(?:\s+chat)?\b", re.I)
_UNARCHIVE_CONTAINS_RE = re.compile(r"\b(desarchivar|unarchive)(?:\s+chat)?\b", re.I)


async def _first_visible(locator: Locator):
    try:
        count = await locator.count()
    except Exception:
        return None
    for idx in range(min(count, 50)):
        item = locator.nth(idx)
        try:
            if await item.is_visible():
                return item
        except Exception:
            continue
    return None


async def _click_exact_text(page: Page, text: str) -> bool:
    candidates = [
        page.get_by_role("button", name=text, exact=True),
        page.get_by_role("tab", name=text, exact=True),
        page.get_by_text(text, exact=True),
    ]
    for loc in candidates:
        item = await _first_visible(loc)
        if item is not None:
            try:
                await item.click(timeout=2500)
                return True
            except Exception:
                try:
                    await item.click(force=True, timeout=1500)
                    return True
                except Exception:
                    pass
    return False




def _flexible_text_pattern(text: str) -> re.Pattern:
    """Match WhatsApp list labels even when it inserts spaces/count badges."""
    words = [re.escape(w) for w in re.split(r"\s+", text.strip()) if w]
    body = r"\s*".join(words) if words else re.escape(text.strip())
    return re.compile(rf"^\s*{body}(?:\s+\d+)?\s*$", re.I)


async def _click_company_list_if_visible(page: Page, list_name: str) -> bool:
    """Click a custom list when its chip/menu entry is already visible.

    WhatsApp can render custom lists as a top chip or as a row inside the
    More lists popup. Prefer interactive roles to avoid matching a chat with
    the same name.
    """
    pattern = _flexible_text_pattern(list_name)
    candidates = [
        page.get_by_role("button", name=pattern),
        page.get_by_role("tab", name=pattern),
        page.get_by_role("menuitem", name=pattern),
        page.get_by_text(pattern),
    ]
    for loc in candidates:
        try:
            count = await loc.count()
        except Exception:
            continue
        for idx in range(min(count, 40)):
            item = loc.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                # If text is nested, click the closest interactive ancestor when possible.
                target = item.locator("xpath=ancestor-or-self::*[self::button or @role='button' or @role='tab' or @role='menuitem'][1]")
                if await target.count() and await target.first.is_visible():
                    await target.first.click(timeout=2500)
                else:
                    await item.click(timeout=2500)
                return True
            except Exception:
                try:
                    await item.click(force=True, timeout=1500)
                    return True
                except Exception:
                    continue
    return False


async def _more_lists_popup_visible(page: Page) -> bool:
    """Return True only when the custom-list overflow is actually open.

    WhatsApp currently shows a small popover containing at least ``New list`` /
    ``Nueva lista`` plus any hidden custom lists.  We deliberately verify the
    popover after every click so a click on the SVG/title that does nothing is
    never treated as success.
    """
    new_list_re = re.compile(r"^(New list|Nueva lista)$", re.I)
    for loc in (
        page.get_by_text(new_list_re),
        page.get_by_role("menuitem", name=new_list_re),
        page.get_by_role("button", name=new_list_re),
    ):
        if await _first_visible(loc) is not None:
            return True
    return False


async def _open_more_lists(page: Page) -> bool:
    """Open WhatsApp's custom-list overflow (``More lists``).

    The operator's current WhatsApp build renders the control as a circular
    clickable wrapper around a ``span > svg > title`` whose title is
    ``ic-arrow-drop-down``.  The span itself is *not* necessarily the clickable
    node.  Try accessible selectors first, then climb several DOM ancestors of
    the exact SVG, and finally click its screen coordinates.  Success is only
    returned after the popover is visibly open.
    """
    if await _more_lists_popup_visible(page):
        return True

    name_re = re.compile(r"^(More lists|Más listas|Mas listas)$", re.I)

    async def try_click(loc: Locator) -> bool:
        item = await _first_visible(loc)
        if item is None:
            return False
        for force in (False, True):
            try:
                await item.click(timeout=1800, force=force)
                await page.wait_for_timeout(300)
                if await _more_lists_popup_visible(page):
                    return True
            except Exception:
                pass
        return False

    # Accessible/semantic variants (English and Spanish).
    for loc in (
        page.get_by_role("button", name=name_re),
        page.locator("button[aria-label*='More lists' i], [role='button'][aria-label*='More lists' i]"),
        page.locator("button[aria-label*='Más listas' i], [role='button'][aria-label*='Más listas' i]"),
        page.locator("[title*='More lists' i], [title*='Más listas' i], [title*='Mas listas' i]"),
    ):
        if await try_click(loc):
            return True

    # Exact DOM observed by the operator.  Click the visible icon and then each
    # plausible clickable ancestor because WhatsApp's generated wrapper varies
    # between builds and can be a div/span instead of a button.
    icon_span = page.locator("span:has(svg title:text-is('ic-arrow-drop-down'))")
    icon = await _first_visible(icon_span)
    if icon is not None:
        # First use normal Playwright clicks on the span and nearby ancestors.
        candidates = [
            icon,
            icon.locator("xpath=.."),
            icon.locator("xpath=../.."),
            icon.locator("xpath=../../.."),
            icon.locator("xpath=ancestor::*[@role='button'][1]"),
            icon.locator("xpath=ancestor::button[1]"),
            icon.locator("xpath=ancestor::*[@tabindex][1]"),
        ]
        for candidate in candidates:
            if await try_click(candidate):
                return True

        # Dispatch the full pointer/mouse click sequence on the most likely
        # wrapper.  ``HTMLElement.click()`` alone did not open this build.
        try:
            await icon.evaluate(
                """el => {
                    const chain = [];
                    let n = el;
                    for (let i = 0; n && i < 6; i++, n = n.parentElement) chain.push(n);
                    const target = chain.find(x =>
                        x.tagName === 'BUTTON' || x.getAttribute('role') === 'button' ||
                        x.hasAttribute('tabindex') || getComputedStyle(x).cursor === 'pointer'
                    ) || el;
                    const opts = {bubbles:true, cancelable:true, composed:true, view:window};
                    target.dispatchEvent(new PointerEvent('pointerdown', opts));
                    target.dispatchEvent(new MouseEvent('mousedown', opts));
                    target.dispatchEvent(new PointerEvent('pointerup', opts));
                    target.dispatchEvent(new MouseEvent('mouseup', opts));
                    target.dispatchEvent(new MouseEvent('click', opts));
                }"""
            )
            await page.wait_for_timeout(350)
            if await _more_lists_popup_visible(page):
                return True
        except Exception:
            pass

        # Last resort: real mouse click at the centre of the visible arrow.
        try:
            box = await icon.bounding_box()
            if box:
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await page.wait_for_timeout(350)
                if await _more_lists_popup_visible(page):
                    return True
        except Exception:
            pass

    return False


async def _open_company_list(page: Page, list_name: str, logger) -> bool:
    # Variant A: the custom list is already one of the visible chips at the top.
    if await _click_company_list_if_visible(page, list_name):
        logger.info("[WHATSAPP CHATS] Lista '%s' visible arriba; abierta directamente.", list_name)
        return True

    # Variant B: only All/Unread/Favorites/Groups are visible and the rest are
    # behind the small More lists arrow.
    if not await _open_more_lists(page):
        return False
    logger.info("[WHATSAPP CHATS] Abierto 'Más listas'. Buscando '%s'…", list_name)
    await page.wait_for_timeout(180)
    if await _click_company_list_if_visible(page, list_name):
        return True

    # Last DOM fallback: look for visible text in the popup and click the nearest
    # interactive/container node. This avoids depending on WhatsApp's generated classes.
    wanted = re.sub(r"\s+", "", list_name).casefold()
    try:
        clicked = await page.evaluate(
            r"""wanted => {
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const norm = s => (s || '').replace(/\s+/g, '').toLowerCase();
                const els = [...document.querySelectorAll('button,[role=\"button\"],[role=\"menuitem\"],[role=\"tab\"],div,span')];
                for (const el of els) {
                    if (!visible(el)) continue;
                    const txt = norm(el.textContent);
                    if (!(txt === wanted || txt.startsWith(wanted))) continue;
                    const target = el.closest('button,[role=\"button\"],[role=\"menuitem\"],[role=\"tab\"],[tabindex]') || el;
                    target.click();
                    return true;
                }
                return false;
            }""",
            wanted,
        )
        if clicked:
            await page.wait_for_timeout(300)
            return True
    except Exception:
        pass
    return False


async def _find_archived_entry(page: Page):
    # Prefer the chat-list pane so an unrelated message containing the word does not count.
    pane = page.locator("#pane-side")
    for root in (pane, page):
        for loc in (
            root.get_by_text(_ARCHIVED_RE),
            root.get_by_role("button", name=_ARCHIVED_RE),
        ):
            item = await _first_visible(loc)
            if item is not None:
                return item
    return None


async def _chat_rows(page: Page) -> list[Locator]:
    """Return visible WhatsApp chat rows, trying several current/legacy DOM shapes."""
    selectors = [
        "#pane-side [data-testid='cell-frame-container']",
        "#pane-side [role='listitem']",
        "#pane-side [role='row']",
    ]
    seen = set()
    rows: list[Locator] = []
    for selector in selectors:
        loc = page.locator(selector)
        try:
            count = await loc.count()
        except Exception:
            continue
        for idx in range(min(count, 250)):
            row = loc.nth(idx)
            try:
                if not await row.is_visible():
                    continue
                text = re.sub(r"\s+", " ", (await row.inner_text()).strip())
                if not text or _ARCHIVED_RE.fullmatch(text):
                    continue
                box = await row.bounding_box()
                if not box or box.get("height", 0) < 35:
                    continue
                # Ignore obvious header/info rows that are not chats.
                if text.lower() in {"archived chats are muted", "los chats archivados están silenciados"}:
                    continue
                key = (
                    round(box.get("x", 0)), round(box.get("y", 0)),
                    round(box.get("width", 0)), round(box.get("height", 0)),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
            except Exception:
                continue
        if rows:
            break
    return rows


async def _menu_is_visible(page: Page) -> bool:
    for selector in (
        "[role='menu']",
        "[data-testid='mi-archive']",
        "[data-testid='mi-unarchive']",
        "[data-testid*='menu']",
    ):
        item = await _first_visible(page.locator(selector))
        if item is not None:
            return True
    # Some WhatsApp versions expose menu items without role=menu.
    for pattern in (_ARCHIVE_CONTAINS_RE, _UNARCHIVE_CONTAINS_RE):
        if await _first_visible(page.get_by_text(pattern)) is not None:
            return True
    return False


async def _open_row_menu(page: Page, row: Locator) -> None:
    await row.hover()
    await page.wait_for_timeout(100)

    # Prefer WhatsApp's own dropdown. The exact data-icon/testid changes often,
    # especially inside Archivados, so cover current and legacy variants.
    for selector in (
        "[data-testid='cell-frame-dropdown']",
        "[data-testid*='dropdown' i]",
        "[data-icon='down-context']",
        "[data-icon*='down' i]",
        "[data-icon*='menu' i]",
        "button[aria-label*='menu' i]",
        "button[aria-label*='menú' i]",
        "[aria-label*='menu' i]",
        "[aria-label*='menú' i]",
        "[title*='menu' i]",
        "[title*='menú' i]",
    ):
        trigger = await _first_visible(row.locator(selector))
        if trigger is not None:
            try:
                await trigger.click(force=True, timeout=2000)
                await page.wait_for_timeout(220)
                if await _menu_is_visible(page):
                    return
            except Exception:
                pass

    # DOM fallback: after hover, locate any newly visible descendant whose icon/title
    # looks like WhatsApp's row chevron/menu and click its closest interactive wrapper.
    try:
        clicked = await row.evaluate(
            r"""el => {
                const vis = x => {
                    const r=x.getBoundingClientRect(), s=getComputedStyle(x);
                    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';
                };
                const nodes=[...el.querySelectorAll('[data-icon],[aria-label],[title],svg title,button,[role=button],[tabindex]')];
                for (const n of nodes) {
                    const data=((n.getAttribute?.('data-icon')||'')+' '+(n.getAttribute?.('aria-label')||'')+' '+(n.getAttribute?.('title')||'')+' '+(n.textContent||'')).toLowerCase();
                    if (!/(down|dropdown|chevron|menu|menú|context)/i.test(data)) continue;
                    const target=n.closest?.('button,[role=button],[tabindex]') || n.parentElement || n;
                    if (!vis(target)) continue;
                    target.click();
                    return true;
                }
                return false;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(250)
            if await _menu_is_visible(page):
                return
    except Exception:
        pass

    # Visual fallback: WhatsApp reveals the row dropdown at the far-right edge on
    # hover. Click that region directly instead of depending on generated classes.
    try:
        box = await row.bounding_box()
        if box:
            for x_ratio in (0.965, 0.93, 0.89):
                await page.mouse.click(box['x'] + box['width'] * x_ratio, box['y'] + box['height'] * 0.5)
                await page.wait_for_timeout(220)
                if await _menu_is_visible(page):
                    return
    except Exception:
        pass

    # Last fallback: dispatch a DOM contextmenu event. This avoids invoking the
    # browser's native context menu while still triggering WhatsApp listeners.
    try:
        await row.dispatch_event('contextmenu', {'button': 2, 'buttons': 2})
        await page.wait_for_timeout(220)
        if await _menu_is_visible(page):
            return
    except Exception:
        pass

    # Legacy physical right-click as a final attempt.
    try:
        await row.click(button="right", timeout=2500)
        await page.wait_for_timeout(220)
        if await _menu_is_visible(page):
            return
    except Exception:
        pass

    raise RuntimeError("No pude abrir el menú contextual de un chat de WhatsApp.")


async def _click_row_quick_action(row: Locator, *, unarchive: bool) -> bool:
    word = "desarchivar" if unarchive else "archivar"
    en_word = "unarchive" if unarchive else "archive"
    selectors = [
        f"[aria-label*='{word}' i]",
        f"[title*='{word}' i]",
        f"[aria-label*='{en_word}' i]",
        f"[title*='{en_word}' i]",
    ]
    # Some builds use data-icon attributes instead of accessible labels.
    if unarchive:
        selectors += ["[data-icon*='unarchive' i]"]
    else:
        selectors += ["[data-icon='archive']", "[data-icon*='archive' i]"]
    for selector in selectors:
        item = await _first_visible(row.locator(selector))
        if item is None:
            continue
        try:
            await item.click(force=True, timeout=1800)
            return True
        except Exception:
            continue
    return False


async def _click_page_quick_action_near_row(page: Page, row: Locator, *, unarchive: bool) -> bool:
    """Click a hover action rendered outside the row DOM.

    Recent WhatsApp builds sometimes portal the archive/unarchive action into an
    overlay/sibling, so searching only descendants of the chat row misses it.
    We collect visible candidates from the whole page and choose the one whose
    vertical centre is closest to the current row.
    """
    word = "desarchivar" if unarchive else "archivar"
    en_word = "unarchive" if unarchive else "archive"
    selectors = [
        f"[aria-label*='{word}' i]",
        f"[title*='{word}' i]",
        f"[aria-label*='{en_word}' i]",
        f"[title*='{en_word}' i]",
    ]
    if unarchive:
        selectors += ["[data-icon*='unarchive' i]"]
    else:
        selectors += ["[data-icon='archive']", "[data-icon*='archive' i]"]

    try:
        rbox = await row.bounding_box()
    except Exception:
        rbox = None
    if not rbox:
        return False
    ry = rbox["y"] + rbox["height"] / 2

    candidates = []
    for selector in selectors:
        loc = page.locator(selector)
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 80)):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
                box = await item.bounding_box()
                if not box:
                    continue
                cy = box["y"] + box["height"] / 2
                candidates.append((abs(cy - ry), item))
            except Exception:
                continue
    for _, item in sorted(candidates, key=lambda x: x[0]):
        try:
            await item.click(force=True, timeout=1800)
            return True
        except Exception:
            continue
    return False




async def _unarchive_via_open_chat_header(page: Page, row: Locator) -> bool:
    """Fallback for Archived when the row dropdown is not operable.

    Open the chat, then use the conversation header menu and choose Unarchive.
    This avoids WhatsApp's fragile per-row hover/menu control, which changes
    frequently and may not exist as a clickable descendant of the row.
    """
    try:
        await row.click(timeout=2500)
    except Exception:
        try:
            await row.click(force=True, timeout=1800)
        except Exception:
            return False
    await page.wait_for_timeout(450)

    # Open the menu from the active conversation header.  Keep selectors broad
    # because WhatsApp rotates data-testid/data-icon names between builds.
    header_roots = [page.locator("#main header"), page.locator("header")]
    menu_selectors = [
        "[data-testid='conversation-menu-button']",
        "[data-testid*='menu' i]",
        "[data-icon='menu']",
        "[data-icon*='menu' i]",
        "button[aria-label*='menu' i]",
        "button[aria-label*='menú' i]",
        "[aria-label*='menu' i]",
        "[aria-label*='menú' i]",
        "[title*='menu' i]",
        "[title*='menú' i]",
    ]
    opened = False
    for root in header_roots:
        try:
            if not await root.first.is_visible():
                continue
        except Exception:
            continue
        for selector in menu_selectors:
            trigger = await _first_visible(root.locator(selector))
            if trigger is None:
                continue
            for force in (False, True):
                try:
                    await trigger.click(timeout=1800, force=force)
                    await page.wait_for_timeout(220)
                    if await _menu_is_visible(page):
                        opened = True
                        break
                except Exception:
                    pass
            if opened:
                break
        if opened:
            break

    if not opened:
        # Visual fallback: in the conversation header the overflow button is
        # normally the right-most small button.  Click candidates from right to left.
        try:
            header = page.locator("#main header").first
            buttons = header.locator("button,[role='button'],[tabindex]")
            count = await buttons.count()
            visible = []
            for i in range(min(count, 40)):
                b = buttons.nth(i)
                try:
                    if not await b.is_visible():
                        continue
                    box = await b.bounding_box()
                    if box:
                        visible.append((box['x'], b))
                except Exception:
                    pass
            for _, b in sorted(visible, key=lambda x: x[0], reverse=True)[:6]:
                try:
                    await b.click(force=True, timeout=1200)
                    await page.wait_for_timeout(220)
                    if await _menu_is_visible(page):
                        opened = True
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if not opened:
        return False

    # Click the real Unarchive action from the conversation menu.
    for loc in (
        page.get_by_role("menuitem", name=_UNARCHIVE_RE),
        page.get_by_role("menuitem", name=_UNARCHIVE_CONTAINS_RE),
        page.get_by_text(_UNARCHIVE_RE),
        page.get_by_text(_UNARCHIVE_CONTAINS_RE),
    ):
        item = await _first_visible(loc)
        if item is None:
            continue
        try:
            await item.click(timeout=2200)
            await page.wait_for_timeout(350)
            return True
        except Exception:
            try:
                await item.click(force=True, timeout=1200)
                await page.wait_for_timeout(350)
                return True
            except Exception:
                pass

    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    return False

async def _visible_menu_labels(page: Page) -> list[str]:
    labels: list[str] = []
    for selector in ("[role='menuitem']", "[role='menu'] *", "[data-testid*='mi-']"):
        loc = page.locator(selector)
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 80)):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
                txt = re.sub(r"\s+", " ", (await item.inner_text()).strip())
                if txt and txt not in labels:
                    labels.append(txt[:120])
            except Exception:
                pass
    return labels[:30]


async def _apply_row_action(page: Page, row: Locator, *, unarchive: bool) -> None:
    await row.hover()
    if await _click_row_quick_action(row, unarchive=unarchive):
        return
    if await _click_page_quick_action_near_row(page, row, unarchive=unarchive):
        return

    # In Archivados, WhatsApp's per-row dropdown is especially unstable.
    # Prefer opening the chat and using the conversation-header menu before
    # attempting the old row context-menu fallback.
    if unarchive and await _unarchive_via_open_chat_header(page, row):
        return

    await _open_row_menu(page, row)
    exact = _UNARCHIVE_RE if unarchive else _ARCHIVE_RE
    contains = _UNARCHIVE_CONTAINS_RE if unarchive else _ARCHIVE_CONTAINS_RE
    menu_candidates = [
        page.get_by_role("menuitem", name=exact),
        page.get_by_role("menuitem", name=contains),
        page.get_by_text(exact),
        page.get_by_text(contains),
        page.locator("[aria-label]").filter(has=page.get_by_text(contains)),
    ]
    for loc in menu_candidates:
        item = await _first_visible(loc)
        if item is not None:
            try:
                await item.click(timeout=2500)
                return
            except Exception:
                try:
                    await item.click(force=True, timeout=1500)
                    return
                except Exception:
                    pass

    labels = await _visible_menu_labels(page)
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    action = "Desarchivar" if unarchive else "Archivar"
    suffix = f" Menú visible: {labels}" if labels else ""
    raise RuntimeError(f"No encontré la acción '{action}' en el menú contextual de WhatsApp.{suffix}")


async def _process_all_rows(page: Page, *, unarchive: bool, logger, max_chats: int = 250) -> int:
    done = 0
    stale_attempts = 0
    while done < max_chats:
        rows = await _chat_rows(page)
        if not rows:
            break
        row = rows[0]
        try:
            label = re.sub(r"\s+", " ", (await row.inner_text()).strip()).split("\n", 1)[0][:80]
        except Exception:
            label = f"chat {done + 1}"
        try:
            await _apply_row_action(page, row, unarchive=unarchive)
        except Exception:
            stale_attempts += 1
            if stale_attempts >= 2:
                raise
            await page.wait_for_timeout(350)
            continue
        stale_attempts = 0
        done += 1
        logger.info("[WHATSAPP CHATS] %s: %s", "Desarchivado" if unarchive else "Archivado", label)
        await page.wait_for_timeout(350)
    if done >= max_chats:
        raise RuntimeError(f"Se alcanzó el límite de seguridad de {max_chats} chats.")
    return done


async def _open_home(page: Page) -> None:
    await page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded")
    await wait_until_logged_in(page)
    await page.wait_for_timeout(700)


async def _ensure_live_page(context, page: Page | None) -> Page:
    """Return a usable page, recreating the tab if WhatsApp closed it."""
    try:
        if page is not None and not page.is_closed():
            return page
    except Exception:
        pass
    page = await context.new_page()
    return page


def _is_target_closed_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "targetclosed" in text or "target page, context or browser has been closed" in text


def _time_fallback_mode(now: datetime | None = None) -> str | None:
    """Operator-requested fallback only when UI state cannot be determined.

    17:00 <= time < 19:00 -> unarchive
    22:00 <= time or time < 01:00 -> archive
    Other times -> no time-based decision.
    """
    now = now or datetime.now()
    t = now.time()
    if time(17, 0) <= t < time(19, 0):
        return "unarchive"
    if t >= time(22, 0) or t < time(1, 0):
        return "archive"
    return None


async def _archive_from_company_list(page: Page, list_name: str, logger) -> dict:
    await _open_home(page)
    logger.info("[WHATSAPP CHATS] Abriendo lista '%s' para archivar…", list_name)
    if not await _open_company_list(page, list_name, logger):
        raise RuntimeError(
            f"No encontré la lista/filtro de chats '{list_name}' ni visible arriba ni dentro de 'Más listas'. "
            "No se archivó ningún chat."
        )
    await page.wait_for_timeout(550)
    count = await _process_all_rows(page, unarchive=False, logger=logger)
    return {"mode": "archive", "count": count, "list": list_name}


async def _unarchive_from_archived(page: Page, archived: Locator, logger) -> dict:
    logger.info("[WHATSAPP CHATS] Entrando a Archivados…")
    await archived.click(timeout=3000)
    await page.wait_for_timeout(600)
    rows = await _chat_rows(page)
    if not rows:
        return {"mode": "empty_archived", "count": 0, "list": "Archivados"}
    logger.info("[WHATSAPP CHATS] Hay %s chat(s) archivado(s) visibles. Desarchivando…", len(rows))
    count = await _process_all_rows(page, unarchive=True, logger=logger)
    return {"mode": "unarchive", "count": count, "list": "Archivados"}


async def _toggle_once(context, cfg: dict, logger) -> dict:
    wa_cfg = cfg.get("whatsapp") or {}
    list_name = str(wa_cfg.get("company_chat_list") or "Smart Post").strip() or "Smart Post"
    page = context.pages[0] if context.pages else await context.new_page()
    page = await _ensure_live_page(context, page)
    await _open_home(page)

    archived = await _find_archived_entry(page)
    if archived is not None:
        try:
            result = await _unarchive_from_archived(page, archived, logger)
            if result["mode"] == "unarchive":
                return result
            logger.info("[WHATSAPP CHATS] Archivados está vacío. Los chats están desarchivados.")
            return await _archive_from_company_list(page, list_name, logger)
        except Exception as exc:
            fallback = _time_fallback_mode()
            if fallback is None:
                raise
            logger.warning(
                "[WHATSAPP CHATS] No pude determinar/operar el estado por UI (%s). "
                "Aplico fallback horario: %s.", exc, fallback,
            )
            if fallback == "archive":
                page = await _ensure_live_page(context, page)
                return await _archive_from_company_list(page, list_name, logger)

            # Reintento de desarchivado. No navegamos sobre una pestaña cerrada:
            # si WhatsApp la cerró, creamos una nueva dentro del mismo perfil.
            page = await _ensure_live_page(context, page)
            await _open_home(page)
            archived2 = await _find_archived_entry(page)
            if archived2 is None:
                return {"mode": "unarchive", "count": 0, "list": "Archivados"}
            return await _unarchive_from_archived(page, archived2, logger)

    logger.info("[WHATSAPP CHATS] No hay entrada Archivados. Los chats están desarchivados.")
    return await _archive_from_company_list(page, list_name, logger)


async def toggle_company_chats(cfg: dict, logger) -> dict:
    """Archive/unarchive company chats with one automatic browser recovery.

    If WhatsApp unexpectedly closes the tab/context during a row action, relaunch
    the persistent profile once and resume the toggle instead of crashing with
    ``TargetClosedError``.
    """
    wa_cfg = cfg.get("whatsapp") or {}
    profile = resolve_path(cfg, "whatsapp_profile")
    profile.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser_type = getattr(p, str(wa_cfg.get("browser") or "chromium"))
        last_exc = None
        for attempt in (1, 2):
            context = await browser_type.launch_persistent_context(
                user_data_dir=str(profile), headless=False, viewport={"width": 1365, "height": 900}
            )
            try:
                if attempt == 2:
                    logger.warning("[WHATSAPP CHATS] WhatsApp cerró la pestaña/contexto. Reabriendo sesión y reintentando una vez…")
                return await _toggle_once(context, cfg, logger)
            except Exception as exc:
                last_exc = exc
                if not _is_target_closed_error(exc) or attempt == 2:
                    raise
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
        raise last_exc  # pragma: no cover
