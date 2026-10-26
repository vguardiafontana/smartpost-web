"""Desarchivar todo desde la lista Archivados, sin filtros de empresa."""
from __future__ import annotations

import asyncio
import re

from app.delivery.chat_archive import (
    _ARCHIVED_RE, _UNARCHIVE_RE, _UNARCHIVE_CONTAINS_RE,
    _first_visible, _find_archived_entry, _row_identity,
    _click_row_quick_action, _open_row_menu,
)


ROW_SELECTORS = ("[data-testid='cell-frame-container']", "[role='row']", "[role='listitem']", "[data-id]")
EMPTY_RE = re.compile(r"(no (?:hay|ten[eé]s|tienes) chats archivados|(?:you have )?no archived chats|tus chats archivados aparecer[aá]n aqu[ií]|archived chats will appear here)", re.I)
BACK_SELECTOR = "[aria-label='Back' i],[aria-label='Volver' i],[aria-label='Atrás' i],[data-icon='back'],[data-icon*='arrow-back'],button:has(svg title:text-is('ic-arrow-back'))"


async def _archived_pane(page):
    # The archived drawer may be a sibling of #pane-side. Never fall back to
    # reading the normal list when the archived drawer is visible.
    for selector in (
        "[data-testid='archived-chats']", "[data-testid='archived-drawer']",
        "[role='grid'][aria-label*='archiv' i]",
        "[role='list'][aria-label*='archiv' i]",
        "[role='region'][aria-label*='archiv' i]",
    ):
        pane = await _first_visible(page.locator(selector))
        if pane is not None:
            return pane
    labels = page.get_by_text(_ARCHIVED_RE)
    for index in range(min(await labels.count(), 12)):
        label = labels.nth(index)
        if not await label.is_visible():
            continue
        parent = label
        for _ in range(7):
            parent = parent.locator("xpath=..")
            if await parent.evaluate("el => ['HTML','BODY'].includes(el.tagName) || ['app','main'].includes(el.id)"):
                break
            if await _first_visible(parent.locator(BACK_SELECTOR)) is not None:
                if await parent.locator("[role='grid'],[role='list'],[data-testid='chat-list'],[role='row'],[role='listitem']").count() or EMPTY_RE.search(await parent.inner_text()):
                    return parent
    return None


async def _enter_archived(page):
    pane = await _archived_pane(page)
    if pane is not None:
        return pane
    entry = await _find_archived_entry(page)
    if entry is None:
        if await _first_visible(page.get_by_text(EMPTY_RE)) is not None:
            return None
        raise RuntimeError("No encontré Archivados en WhatsApp. No se realizó ninguna otra acción.")
    target = entry.locator("xpath=ancestor-or-self::*[self::button or @role='button' or @tabindex][1]")
    await (target if await target.count() else entry).click(timeout=5000)
    for _ in range(75):
        pane = await _archived_pane(page)
        if pane is not None:
            return pane
        await page.wait_for_timeout(200)
    raise RuntimeError("WhatsApp no abrió la lista Archivados.")


async def _snapshot(pane):
    """One browser read per DOM shape, instead of several reads per chat."""
    for selector in ROW_SELECTORS:
        locator = pane.locator(selector)
        rows = await locator.evaluate_all(r"""(elements, patterns) => {
            const empty = new RegExp(patterns.empty,'i'), archived = new RegExp(patterns.archived,'i');
            const seen = new Set();
            return elements.flatMap((el,index) => {
                const box=el.getBoundingClientRect(), style=getComputedStyle(el);
                if (!box.width || box.height<30 || style.display==='none' || style.visibility==='hidden') return [];
                const text=(el.innerText||'').replace(/\s+/g,' ').trim();
                if (!text || archived.test(text) || empty.test(text) || ['archived chats are muted','los chats archivados están silenciados'].includes(text.toLowerCase())) return [];
                const identified=el.closest('[data-id]')||el.querySelector('[data-id]'), title=el.querySelector('span[title]');
                const identity=identified?'id:'+identified.getAttribute('data-id'):(title?'title:'+title.getAttribute('title'):'text:'+el.innerText.trim());
                if(seen.has(identity))return [];
                seen.add(identity);return [{index,identity}];
            });
        }""", {'empty': EMPTY_RE.pattern, 'archived': _ARCHIVED_RE.pattern})
        if rows:
            return locator, rows
    return None, []


async def _rows(pane):
    locator, rows = await _snapshot(pane)
    return [locator.nth(row['index']) for row in rows]


async def _contains(pane, identity):
    _, rows = await _snapshot(pane)
    return any(row['identity'] == identity for row in rows)


async def _scroll_top(pane):
    return await pane.evaluate("""el => {
        const candidates = [el,...el.querySelectorAll('div,[role=grid],[role=list]')];
        // Some builds put the scrollbar around the labelled archived grid.
        let parent = el.parentElement;
        for (let i=0; parent && i<4 && !['app','main'].includes(parent.id) && !['BODY','HTML'].includes(parent.tagName); i++, parent=parent.parentElement) candidates.push(parent);
        const scroller = candidates.filter(n => n.scrollHeight > n.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(n).overflowY))
          .sort((a,b) => (b.scrollHeight-b.clientHeight)-(a.scrollHeight-a.clientHeight))[0];
        if (!scroller || !scroller.scrollTop) return false;
        scroller.scrollTop = 0;
        scroller.dispatchEvent(new Event('scroll', {bubbles:true}));
        return true;
    }""")


async def _ready_rows(page, pane):
    empty_since = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 15
    while loop.time() < deadline:
        rows = await _rows(pane)
        if rows:
            return rows
        loading = await _first_visible(pane.locator("[role='progressbar'],[aria-busy='true'],[data-testid*='spinner']"))
        if loading is not None or await pane.get_attribute('aria-busy') == 'true':
            empty_since = None
        elif await _first_visible(pane.get_by_text(EMPTY_RE)) is not None:
            return []
        else:
            empty_since = empty_since or loop.time()
            if loop.time() - empty_since >= 2:
                titles = await pane.locator('span[title]').evaluate_all("els => els.filter(el => el.getBoundingClientRect().height>0).map(el => el.getAttribute('title'))")
                if any(title and not _ARCHIVED_RE.fullmatch(title) for title in titles):
                    raise RuntimeError("Hay chats visibles, pero no pude reconocer sus filas en Archivados. No se informó la lista como vacía.")
                return []
        await page.wait_for_timeout(150)
    raise RuntimeError("Archivados sigue cargando. No se dio la lista por vacía.")


async def _unarchive_row(page, row):
    await row.hover()
    if await _click_row_quick_action(row, unarchive=True):
        return
    # Only the selected archived row's own menu; never open a conversation or
    # use the header menu, which can navigate away from Archivados.
    await _open_row_menu(page, row)
    for locator in (
        page.get_by_role("menuitem", name=_UNARCHIVE_RE),
        page.get_by_role("menuitem", name=_UNARCHIVE_CONTAINS_RE),
        page.get_by_text(_UNARCHIVE_RE),
    ):
        action = await _first_visible(locator)
        if action is not None:
            await action.click(timeout=3000)
            return
    await page.keyboard.press("Escape")
    raise RuntimeError("No encontré Desarchivar en el menú del chat archivado.")


async def _removed(page, identity, pane=None):
    for _ in range(40):
        if pane is None or not await pane.is_visible():
            pane = await _archived_pane(page)
        if pane is not None and not await _contains(pane, identity):
            await page.wait_for_timeout(70)
            if not await _contains(pane, identity):
                return True
        await page.wait_for_timeout(100)
    return False


async def unarchive_all(page, logger):
    """Enter Archivados once and drain it, including virtualized/lazy rows."""
    pane = await _enter_archived(page)
    done = 0
    seen = set()
    while pane is not None:
        if await _scroll_top(pane):
            await page.wait_for_timeout(150)
        rows = await _ready_rows(page, pane)
        if not rows:
            break
        row = rows[0]
        identity = await _row_identity(row)
        if identity in seen:
            raise RuntimeError(f"WhatsApp volvió a mostrar un chat ya procesado. Se desarchivaron {done} chats antes de detenerse.")
        for attempt in range(2):
            try:
                await _unarchive_row(page, row)
                if not await _removed(page, identity, pane=pane):
                    raise RuntimeError("El chat sigue en Archivados después de tocar Desarchivar.")
                break
            except Exception:
                if attempt:
                    raise
                await page.keyboard.press("Escape")
                pane = await _enter_archived(page)
                if pane is None:
                    raise RuntimeError("No se pudo verificar el último chat desarchivado.")
                matches = [r for r in await _rows(pane) if await _row_identity(r) == identity]
                if not matches:
                    raise RuntimeError("El chat cambió mientras se intentaba desarchivar. Revisá Archivados.")
                row = matches[0]
        seen.add(identity)
        done += 1
        logger.info("[WHATSAPP CHATS] Desarchivados: %s", done)
        if not await pane.is_visible():
            pane = await _enter_archived(page)
    return {"mode": "unarchive", "count": done, "list": "Archivados"}
