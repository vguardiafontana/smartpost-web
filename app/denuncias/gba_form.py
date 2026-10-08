from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.config import resolve_path


async def _first_visible(locators):
    for loc in locators:
        try:
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if await item.is_visible():
                    return item
        except Exception:
            pass
    return None


async def _visible_field_in_scope(scope, label_re: str, placeholders: list[str] | None = None):
    """Find a visible input/textarea even when the site does not wire <label for=...> correctly.

    The Provincia form is an Angular/Material SPA and some deployments render floating labels
    that Playwright's get_by_label() cannot associate with the real input. Keep several semantic
    fallbacks so small frontend changes do not break the automation.
    """
    rx = re.compile(label_re, re.I)
    candidates = [scope.get_by_label(rx)]
    for ph in placeholders or []:
        candidates.append(scope.get_by_placeholder(re.compile(ph, re.I)))

    # Angular Material / Bootstrap style wrappers where the visible text is inside the field box.
    for wrapper in ("mat-form-field", ".mat-mdc-form-field", ".mat-form-field", ".form-group", ".input-group"):
        try:
            candidates.append(scope.locator(wrapper).filter(has_text=rx).locator("input, textarea"))
        except Exception:
            pass

    # Native labels that are visually present but are not correctly associated with the input.
    try:
        labels = scope.locator("label").filter(has_text=rx)
        count = await labels.count()
        for i in range(min(count, 8)):
            lab = labels.nth(i)
            candidates.extend([
                lab.locator("xpath=following::input[1]"),
                lab.locator("xpath=following::textarea[1]"),
                lab.locator("xpath=../input"),
                lab.locator("xpath=../textarea"),
                lab.locator("xpath=../../input"),
                lab.locator("xpath=../../textarea"),
            ])
    except Exception:
        pass

    # Last semantic fallback: common Angular attributes often contain the field name.
    token = re.sub(r"[^a-z0-9]+", "", re.sub(r"\|.*", "", label_re).lower())
    if token:
        try:
            all_fields = scope.locator("input, textarea")
            count = await all_fields.count()
            for i in range(min(count, 80)):
                field = all_fields.nth(i)
                attrs = []
                for attr in ("name", "id", "formcontrolname", "aria-label", "placeholder"):
                    try:
                        attrs.append((await field.get_attribute(attr)) or "")
                    except Exception:
                        attrs.append("")
                normalized = re.sub(r"[^a-z0-9]+", "", " ".join(attrs).lower())
                if token and token in normalized:
                    candidates.append(field)
        except Exception:
            pass

    return await _first_visible(candidates)


async def _fill_named(page, label_re: str, value: str, placeholders: list[str] | None = None, required: bool = True):
    if not str(value or "").strip() and not required:
        return None

    # SPA hydration/route transitions can leave the field unavailable for a short time.
    # Retry on the main document and every child frame before declaring a selector failure.
    item = None
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline and item is None:
        scopes = [page]
        try:
            scopes.extend([f for f in page.frames if f != page.main_frame])
        except Exception:
            pass
        for scope in scopes:
            item = await _visible_field_in_scope(scope, label_re, placeholders)
            if item is not None:
                break
        if item is None:
            await page.wait_for_timeout(300)

    if item is None:
        if required:
            try:
                title = await page.title()
            except Exception:
                title = ""
            try:
                body = (await page.locator("body").inner_text(timeout=1500)).strip().replace("\n", " | ")[:700]
            except Exception:
                body = ""
            raise RuntimeError(
                f"No encontré el campo '{label_re}' en la web de denuncias. "
                f"URL actual: {page.url}. Título: {title!r}. Texto visible: {body!r}"
            )
        return None

    text = str(value)
    try:
        input_type = (await item.get_attribute("type") or "").lower()
    except Exception:
        input_type = ""
    if input_type == "date" and re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        day, month, year = text.split("/")
        text = f"{year}-{month}-{day}"
    elif input_type == "time" and re.fullmatch(r"\d{1,2}:\d{2}", text):
        hh, mm = text.split(":")
        text = f"{int(hh):02d}:{mm}"

    try:
        await item.fill(text)
    except Exception:
        await item.click()
        try:
            await item.press("Control+A")
        except Exception:
            pass
        await item.type(text)
    return item


async def _click_text(page, pattern: str, required: bool = True):
    candidates = [
        page.get_by_role("button", name=re.compile(pattern, re.I)),
        page.get_by_text(re.compile(pattern, re.I), exact=True),
    ]
    item = await _first_visible(candidates)
    if item is None:
        if required:
            raise RuntimeError(f"No encontré el botón/opción '{pattern}'.")
        return False
    await item.click()
    return True


async def _wait_recaptcha_solved(page, logger, timeout_seconds: int = 300):
    logger.info("[DENUNCIAS] Esperando que completes manualmente el CAPTCHA…")
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            token = await page.locator("textarea[name='g-recaptcha-response']").first.input_value(timeout=500)
            if token and token.strip():
                logger.info("[DENUNCIAS] CAPTCHA validado. Continuando…")
                return
        except Exception:
            pass
        # Some implementations only expose aria-checked inside the iframe.
        try:
            for frame in page.frames:
                cb = frame.locator("#recaptcha-anchor")
                if await cb.count():
                    checked = await cb.get_attribute("aria-checked")
                    if checked == "true":
                        logger.info("[DENUNCIAS] CAPTCHA validado. Continuando…")
                        return
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("No se completó el CAPTCHA dentro del tiempo configurado.")


async def _select_partido(page, value: str):
    if not value.strip():
        raise RuntimeError("Falta el partido del hecho.")
    field = await _first_visible([
        page.get_by_label(re.compile(r"^Partido", re.I)),
        page.get_by_placeholder(re.compile(r"Partido", re.I)),
    ])
    if field is None:
        raise RuntimeError("No encontré el campo Partido.")
    try:
        await field.fill(value)
    except Exception:
        await field.click()
        await page.keyboard.type(value)
    await page.wait_for_timeout(250)
    option = await _first_visible([
        page.get_by_role("option", name=re.compile(re.escape(value), re.I)),
        page.get_by_text(re.compile(rf"^{re.escape(value)}$", re.I), exact=True),
    ])
    if option is not None:
        await option.click()
    else:
        await field.press("Enter")


async def _ensure_characteristics_step(page, logger):
    """Advance from step 2 to step 3 and verify that the panel really changed.

    The Provincia stepper always renders the labels for steps 3/4/5 in the DOM,
    even while step 2 is active.  Therefore seeing the text "Características del
    hecho" is not enough; the violence question must become visible.
    """
    violence_re = re.compile(r"violencia\s+f[ií]sica|daños?\s+materiales", re.I)

    async def visible_question():
        loc = page.get_by_text(violence_re)
        try:
            count = await loc.count()
        except Exception:
            return False
        for i in range(min(count, 12)):
            try:
                if await loc.nth(i).is_visible():
                    return True
            except Exception:
                pass
        return False

    async def click_visible_next():
        """Click the real visible Siguiente button from the active panel."""
        # First use normal Playwright click so Angular receives the full event chain.
        locators = [
            page.get_by_role("button", name=re.compile(r"^\s*Siguiente\s*$", re.I)),
            page.locator("button").filter(has_text=re.compile(r"^\s*Siguiente\s*$", re.I)),
            page.locator("[role='button']").filter(has_text=re.compile(r"^\s*Siguiente\s*$", re.I)),
        ]
        for loc in locators:
            try:
                count = await loc.count()
                # The active panel's footer is normally the last visible Siguiente.
                for i in range(count - 1, -1, -1):
                    b = loc.nth(i)
                    if not await b.is_visible():
                        continue
                    try:
                        await b.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    try:
                        if await b.is_enabled():
                            await b.click(timeout=3000)
                            return True
                    except Exception:
                        # A Material button can occasionally reject a regular click
                        # during an animation; force the pointer event as fallback.
                        try:
                            await b.click(timeout=2000, force=True)
                            return True
                        except Exception:
                            pass
            except Exception:
                pass

        # Last DOM fallback: click the visible native button whose text is exactly
        # Siguiente. This avoids accidentally clicking the step header text.
        try:
            return bool(await page.evaluate("""() => {
                const norm = s => (s || '').replace(/\s+/g,' ').trim().toLowerCase();
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                };
                const items = [...document.querySelectorAll('button,[role="button"]')]
                  .filter(el => visible(el) && norm(el.innerText || el.textContent) === 'siguiente');
                const el = items[items.length - 1];
                if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
                el.click();
                return true;
            }"""))
        except Exception:
            return False

    # If the previous click already worked, return immediately.
    for _ in range(8):
        if await visible_question():
            return
        await page.wait_for_timeout(200)

    logger.info("[DENUNCIAS] Avanzando de 'Datos del hecho' a 'Características del hecho'…")

    # Provincia sometimes finishes address validation a little after the green
    # verified mark appears. Retry the actual footer button for a few seconds.
    for attempt in range(4):
        # The address verification dialog can appear late and block Siguiente.
        # Always clear it immediately before trying to advance.
        await _ignore_address_verification_if_present(page, logger, timeout_ms=2500)
        clicked = await click_visible_next()
        if clicked:
            logger.info("[DENUNCIAS] Siguiente (Datos del hecho) pulsado. Esperando paso 3…")
        for _ in range(15):
            if await visible_question():
                logger.info("[DENUNCIAS] Paso 'Características del hecho' abierto.")
                return
            await page.wait_for_timeout(200)
        await page.wait_for_timeout(400)

    # Do not click the step-3 header: this is a linear Material stepper and the
    # header text is present even when step 3 is not yet reachable.
    try:
        diag = await page.evaluate("""() => {
            const norm = s => (s || '').replace(/\s+/g,' ').trim();
            const buttons = [...document.querySelectorAll('button,[role="button"]')]
              .filter(el => norm(el.innerText || el.textContent).toLowerCase() === 'siguiente')
              .map(el => ({
                text: norm(el.innerText || el.textContent),
                disabled: !!el.disabled,
                ariaDisabled: el.getAttribute('aria-disabled'),
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
              }));
            const invalid = [...document.querySelectorAll('input:invalid, textarea:invalid, select:invalid')]
              .map(el => ({name: el.name || el.id || el.getAttribute('formcontrolname') || '', value: el.value || ''}));
            return {buttons, invalid};
        }""")
    except Exception:
        diag = {}
    try:
        body = (await page.locator("body").inner_text(timeout=1500)).replace("\n", " | ")[:1800]
    except Exception:
        body = ""
    raise RuntimeError(
        "No se pudo avanzar de 'Datos del hecho' a 'Características del hecho'. "
        f"Diagnóstico: {diag!r}. Texto visible: {body!r}"
    )


async def _set_radio(page, question: str, answer: str):
    """Select a radio without Playwright auto-scroll loops.

    Provincia changes the Angular/Material markup frequently. We therefore use
    an accent-insensitive DOM search, score radio candidates by their distance
    to the question text, click the closest matching option and verify that it
    actually became selected.
    """
    raw = str(answer or "").strip()
    low = raw.lower()
    if low in {"si", "sí", "s", "yes", "y"}:
        target = "Sí"
    elif low in {"no", "n"}:
        target = "No"
    else:
        target = raw
    if not target:
        raise RuntimeError(f"Falta seleccionar una opción para '{question}'.")

    result = await page.evaluate(
        """({question, target}) => {
            const norm = s => (s || '')
              .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
              .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
            const q = norm(question);
            const t = norm(target);
            const text = el => norm(el && (el.innerText || el.textContent || ''));

            const all = Array.from(document.querySelectorAll('body *'));
            const qEls = all.filter(el => q && text(el).includes(q));
            qEls.sort((a,b) => text(a).length - text(b).length);
            const qEl = qEls[0] || null;

            const ancestry = el => {
              const out=[]; let n=el;
              while(n && out.length < 25){ out.push(n); n=n.parentElement; }
              return out;
            };
            const qa = qEl ? ancestry(qEl) : [];
            const domDistance = el => {
              if (!qEl) return 999;
              const ea=ancestry(el);
              for (let i=0;i<ea.length;i++) {
                const j=qa.indexOf(ea[i]);
                if (j >= 0) return i+j;
              }
              return 999;
            };

            const radios = Array.from(document.querySelectorAll(
              'input[type="radio"], [role="radio"], mat-radio-button, .mat-radio-button, .mat-mdc-radio-button'
            ));
            const optionText = el => {
              let parts=[text(el), norm(el.getAttribute && el.getAttribute('aria-label')), norm(el.getAttribute && el.getAttribute('value'))];
              const input = el.matches && el.matches('input[type="radio"]') ? el : (el.querySelector && el.querySelector('input[type="radio"]'));
              if (input) {
                parts.push(norm(input.value), norm(input.getAttribute('aria-label')));
                if (input.id) {
                  try {
                    const lab=document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
                    parts.push(text(lab));
                  } catch (_) {}
                }
                let n=input.parentElement;
                for(let i=0;n && i<3;i++,n=n.parentElement) parts.push(text(n));
              }
              if (el.tagName === 'LABEL') parts.push(text(el));
              return parts.filter(Boolean).join(' ');
            };
            const targetMatch = (txt, el) => {
              const n=norm(txt);
              if (n.split(' ').includes(t)) return true;
              if (n === t || n.startsWith(t+' ')) return true;
              const val=norm(el && el.value);
              if (t === 'si' && ['si','s','yes','true','1'].includes(val)) return true;
              if (t === 'no' && ['no','n','false','0'].includes(val)) return true;
              return false;
            };

            let candidates=[];
            for (const el of radios) {
              const input = el.matches && el.matches('input[type="radio"]') ? el : (el.querySelector && el.querySelector('input[type="radio"]'));
              const clickable = input || el;
              if (!targetMatch(optionText(el), input || el)) continue;
              let score = domDistance(el) * 10;
              // Strong bonus when a nearby ancestor contains the question.
              let n=el; let near=false;
              for(let d=0;n && d<10;d++,n=n.parentElement){
                if(q && text(n).includes(q)){ score -= (120-d); near=true; break; }
              }
              if (!near && (t==='si' || t==='no')) score += 200;
              candidates.push({el, clickable, score});
            }
            candidates.sort((a,b)=>a.score-b.score);
            const chosen=candidates[0];
            if (!chosen) return {ok:false, reason:'no-candidate', qFound:!!qEl, radios:radios.length};

            try { chosen.clickable.click(); }
            catch (_) { chosen.clickable.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window})); }
            const input = chosen.clickable.matches && chosen.clickable.matches('input[type="radio"]')
              ? chosen.clickable : (chosen.el.querySelector && chosen.el.querySelector('input[type="radio"]'));
            if (input && !input.checked) {
              try { input.checked=true; } catch (_) {}
              input.dispatchEvent(new Event('input',{bubbles:true}));
              input.dispatchEvent(new Event('change',{bubbles:true}));
            }
            const selected = input ? !!input.checked : (chosen.el.getAttribute('aria-checked') === 'true');
            return {ok:true, selected, score:chosen.score, qFound:!!qEl, radios:radios.length};
        }""",
        {"question": question, "target": target},
    )
    if result and result.get("ok"):
        await page.wait_for_timeout(150)
        return

    # Diagnostic fallback: direct exact text. Kept last to avoid Playwright's
    # normal auto-scroll behaviour unless the DOM structure is truly unusual.
    exact = re.compile(rf"^{re.escape(target)}$", re.I)
    fallback = await _first_visible([
        page.get_by_role("radio", name=exact),
        page.get_by_label(exact),
        page.get_by_text(exact, exact=True),
    ])
    if fallback is not None:
        try:
            await fallback.evaluate("el => el.click()")
            await page.wait_for_timeout(150)
            return
        except Exception:
            pass

    try:
        body = (await page.locator("body").inner_text(timeout=1200)).replace("\n", " | ")[:1200]
    except Exception:
        body = ""
    raise RuntimeError(
        f"No encontré la opción '{target}' para '{question}'. "
        f"Diagnóstico DOM: {result!r}. Texto visible: {body!r}"
    )




async def _choose_first_locality_suggestion(page, logger) -> bool:
    """If Provincia shows autocomplete alternatives for Localidad/Barrio,
    accept the first visible suggestion. The site can render these as Angular
    Material options or plain list items depending on the deployed version.
    """
    await page.wait_for_timeout(350)
    candidates = [
        page.get_by_role("option"),
        page.locator("mat-option"),
        page.locator(".mat-mdc-option"),
        page.locator(".mat-option"),
        page.locator("[role='listbox'] [role='option']"),
        page.locator(".autocomplete-container .suggestions li"),
        page.locator("ngb-typeahead-window button"),
    ]
    for group in candidates:
        try:
            count = min(await group.count(), 12)
        except Exception:
            continue
        for i in range(count):
            item = group.nth(i)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip().replace("\n", " ")
                if not text:
                    continue
                try:
                    await item.click(timeout=2500)
                except Exception:
                    await item.evaluate("el => el.click()")
                logger.info("[DENUNCIAS] Localidad/Barrio: elegí la sugerencia '%s'.", text[:120])
                await page.wait_for_timeout(250)
                return True
            except Exception:
                continue
    return False




async def _ignore_address_verification_if_present(page, logger, timeout_ms: int = 8000) -> bool:
    """Resolve Provincia's address ambiguity/verification flow.

    Provincia currently shows address alternatives INLINE inside
    ``app-form-datos-domicilio`` as ``ul > li > a`` after pressing
    "Validar dirección".  Only after choosing one of those links can a
    secondary verification dialog appear with "Ignorar y continuar".

    Flow:
      1. If the inline warning says that more than one option was found,
         click the first visible address link.
      2. If the verification dialog appears, press "Ignorar y continuar".
      3. Return once the ambiguity/dialog is gone.
    """
    deadline = asyncio.get_running_loop().time() + max(1000, timeout_ms) / 1000
    saw_any = False

    async def _body_text() -> str:
        try:
            return (await page.locator("body").inner_text(timeout=1000)).strip()
        except Exception:
            return ""

    async def _inline_ambiguity_visible() -> bool:
        body = await _body_text()
        return bool(re.search(r"se\s+encontr[oó]\s+m[aá]s\s+de\s+una\s+opci[oó]n", body, re.I))

    async def _dialog_visible() -> bool:
        # Do not infer a modal from generic page text: Provincia keeps labels and
        # step content in the DOM even when no verification dialog is open.  Only
        # treat a *visible* dialog/overlay as address verification.
        selectors = [
            '[role="dialog"]',
            'mat-dialog-container',
            '.mat-dialog-container',
            '.mat-mdc-dialog-container',
            '.cdk-overlay-pane',
        ]
        for sel in selectors:
            loc = page.locator(sel)
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(count):
                node = loc.nth(i)
                try:
                    if not await node.is_visible():
                        continue
                    txt = (await node.inner_text()).strip()
                except Exception:
                    continue
                if re.search(
                    r"por\s+favor\s+verifique\s+si\s+la\s+direcci[oó]n\s+es\s+correcta|"
                    r"ignorar\s+y\s+continuar|verificaci[oó]n",
                    txt, re.I | re.S
                ):
                    return True
        return False

    async def _pick_inline_alternative() -> str | None:
        """Click one of Provincia's inline address links (first visible one)."""
        # Exact structure observed on Provincia (v1.12.2): the red warning is a
        # <mat-error> and the alternatives are links rendered immediately after
        # it inside app-paso-hecho.  Resolve from the warning itself so we do not
        # depend on Angular's generated ids/classes.
        try:
            picked = await page.evaluate("""() => {
                const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'')
                    .replace(/\s+/g,' ').trim().toLowerCase();
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' &&
                           st.visibility !== 'hidden' && st.opacity !== '0';
                };
                const root = document.querySelector('app-paso-hecho') || document.body;
                const warnings = [...root.querySelectorAll('mat-error, .mat-error, [role="alert"]')];
                const warning = warnings.find(el => visible(el) && /se encontro mas de una opcion/.test(norm(el.textContent)));
                if (!warning) return null;

                // Search forward in DOM order from the warning, stopping before
                // the map controls / next form section.
                const all = [...root.querySelectorAll('a')].filter(visible);
                const wr = warning.getBoundingClientRect();
                const candidates = all.filter(a => {
                    const r = a.getBoundingClientRect();
                    const t = (a.innerText || a.textContent || '').replace(/\s+/g,' ').trim();
                    if (!t || /^([+−-]|leaflet)$/i.test(t)) return false;
                    if (r.top < wr.bottom - 2) return false;
                    return /\d/.test(t) || /provincia|buenos aires|calle|\bC\.|av\.|ruta|tolosa|&/i.test(t);
                });
                const target = candidates[0];
                if (!target) return null;
                const text = (target.innerText || target.textContent || '').replace(/\s+/g,' ').trim();
                target.scrollIntoView({block:'center', inline:'center'});
                // This is the same anchor the user clicks manually.
                target.click();
                return text;
            }""")
            if picked:
                return picked
        except Exception:
            pass

        selectors = [
            # Provincia renders the alternatives as a sibling list under
            # app-paso-hecho (not always inside app-form-datos-domicilio).
            "app-paso-hecho ul li a",
            "app-paso-hecho ul li",
            "app-paso-hecho ul a",
            "app-form-datos-domicilio ul li a",
            "app-form-datos-domicilio ul li",
            "app-form-datos-domicilio ul a",
            "app-form-datos-domicilio li a",
            "app-form-datos-domicilio a",
        ]
        for sel in selectors:
            loc = page.locator(sel)
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(count):
                node = loc.nth(i)
                try:
                    if not await node.is_visible():
                        continue
                    txt = (await node.inner_text()).strip()
                    if not txt:
                        continue
                    # These links are the alternatives shown immediately below
                    # the red warning. Avoid unrelated navigation anchors.
                    if not (
                        re.search(r"\d", txt)
                        or re.search(r"provincia|buenos\s+aires|calle|\bC\.|av\.|ruta|tolosa|&", txt, re.I)
                    ):
                        continue
                    try:
                        await node.click(timeout=2500)
                    except Exception:
                        await node.evaluate("el => el.click()")
                    return txt
                except Exception:
                    continue

        # DOM fallback matching the structure from DevTools.  The warning and
        # alternatives can be siblings of app-form-datos-domicilio under
        # app-paso-hecho, so start there and locate the UL that follows the
        # warning instead of assuming the list lives inside the address form.
        try:
            picked = await page.evaluate("""() => {
                const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'')
                    .replace(/\s+/g,' ').trim().toLowerCase();
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' &&
                           st.visibility !== 'hidden' && st.opacity !== '0';
                };
                const root = document.querySelector('app-paso-hecho') ||
                             document.querySelector('app-form-datos-domicilio') || document.body;
                const all = [...root.querySelectorAll('*')];
                const warning = all.find(el => visible(el) &&
                    /se encontro mas de una opcion/.test(norm(el.textContent)));

                let candidates = [];
                if (warning) {
                    // Prefer the first visible UL after the warning in document order.
                    const nodes = [...root.querySelectorAll('ul')].filter(visible);
                    const wr = warning.getBoundingClientRect();
                    const ul = nodes.find(x => x.getBoundingClientRect().top >= wr.top - 5);
                    if (ul) candidates = [...ul.querySelectorAll('li a, li')].filter(visible);
                }
                if (!candidates.length) {
                    candidates = [...root.querySelectorAll('ul li a, ul li')].filter(visible);
                }

                const candidate = candidates.find(el => {
                    const t = (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
                    return t && !/^([+−-]|leaflet)$/i.test(t) &&
                        (/\d/.test(t) || /provincia|buenos aires|calle|\bC\.|av\.|ruta|tolosa|&/i.test(t));
                });
                if (!candidate) return null;

                const target = candidate.matches('a,button,[role="button"]')
                    ? candidate
                    : (candidate.querySelector('a,button,[role="button"]') || candidate);
                const text = (candidate.innerText || candidate.textContent || '').replace(/\s+/g,' ').trim();
                target.scrollIntoView({block:'center', inline:'center'});
                // Native click first. If Angular attached the handler to the LI,
                // dispatch a real mouse event as a second signal.
                if (target instanceof HTMLElement) target.click();
                target.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
                return text;
            }""")
            return picked or None
        except Exception:
            return None

    async def _click_ignore() -> bool:
        text_candidates = [
            page.get_by_text(re.compile(r"^\s*Ignorar\s+y\s+continuar\s*$", re.I), exact=True),
            page.locator("text=/^\\s*Ignorar\\s+y\\s+continuar\\s*$/i"),
            page.get_by_role("button", name=re.compile(r"Ignorar\s+y\s+continuar", re.I)),
            page.locator("button").filter(has_text=re.compile(r"Ignorar\s+y\s+continuar", re.I)),
        ]
        for loc in text_candidates:
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(count - 1, -1, -1):
                node = loc.nth(i)
                try:
                    if not await node.is_visible():
                        continue
                    try:
                        await node.click(timeout=1800, force=True)
                    except Exception:
                        await node.evaluate("el => (el.closest('button,[role=button],a') || el).click()")
                    return True
                except Exception:
                    continue

        # Last resort: locate exact visible text and click its nearest clickable ancestor.
        try:
            return bool(await page.evaluate("""() => {
                const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'')
                    .replace(/\s+/g,' ').trim().toLowerCase();
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && st.display !== 'none' &&
                           st.visibility !== 'hidden' && st.opacity !== '0';
                };
                const all = [...document.querySelectorAll('body *')];
                const leaf = all.find(el => visible(el) && norm(el.textContent) === 'ignorar y continuar');
                if (!leaf) return false;
                const target = leaf.closest('button,[role="button"],a,.mat-mdc-button,.mat-button,.mdc-button') || leaf;
                target.scrollIntoView({block:'center', inline:'center'});
                if (target instanceof HTMLElement) target.click();
                return true;
            }"""))
        except Exception:
            return False

    while asyncio.get_running_loop().time() < deadline:
        if page.is_closed():
            return False

        ambiguity = await _inline_ambiguity_visible()
        dialog = await _dialog_visible()

        if not ambiguity and not dialog:
            if saw_any:
                logger.info("[DENUNCIAS] Verificación/ambigüedad de dirección resuelta; continúo.")
                return True
            await page.wait_for_timeout(200)
            continue

        saw_any = True

        # IMPORTANT: the current Provincia site renders the alternatives inline,
        # not in a Material dialog. Pick one before trying to dismiss verification.
        if ambiguity:
            picked = await _pick_inline_alternative()
            if picked:
                logger.info("[DENUNCIAS] Dirección ambigua: elegí la primera alternativa visible: %s", picked[:180])
                await page.wait_for_timeout(900)
                # After choosing an address, Provincia may either accept it
                # immediately or open the verification dialog. Loop to detect
                # either state.
                continue

        if dialog:
            if await _click_ignore():
                logger.info("[DENUNCIAS] Verificación de dirección: pulsé 'Ignorar y continuar'.")
                await page.wait_for_timeout(500)
                continue

        await page.wait_for_timeout(250)

    if saw_any:
        try:
            diag = await page.evaluate("""() => {
                const root = document.querySelector('app-paso-hecho') || document.querySelector('app-form-datos-domicilio') || document.body;
                const visible = el => { const r=el.getBoundingClientRect(); return r.width>0 && r.height>0; };
                return [...root.querySelectorAll('a,button,[role="button"],li')]
                    .filter(visible)
                    .map(el => ({tag:el.tagName, text:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim()}))
                    .filter(x => x.text).slice(-40);
            }""")
        except Exception:
            diag = []
        raise RuntimeError(
            "No pude resolver la verificación/ambigüedad de dirección. "
            f"Elementos visibles en el bloque de domicilio: {diag!r}"
        )
    return False


async def _advance_to_send(page, logger) -> None:
    """Advance through Evidencias/Resumen and press ENVIAR once.

    CAPTCHA remains manual. This helper only navigates the ordinary form steps
    after all complaint data has already been filled.
    """
    for _ in range(6):
        if page.is_closed():
            raise RuntimeError("Provincia cerró la página antes de poder tocar ENVIAR.")

        send_btn = await _first_visible([
            page.get_by_role("button", name=re.compile(r"^\s*ENVIAR\s*$", re.I)),
            page.locator("button").filter(has_text=re.compile(r"^\s*ENVIAR\s*$", re.I)),
            page.get_by_text(re.compile(r"^\s*ENVIAR\s*$", re.I), exact=True),
        ])
        if send_btn is not None:
            try:
                await send_btn.click(timeout=5000)
            except Exception:
                await send_btn.evaluate("el => el.click()")
            logger.info("[DENUNCIAS] Resumen completo. Pulsé ENVIAR.")
            await page.wait_for_timeout(500)
            return

        next_btn = await _first_visible([
            page.get_by_role("button", name=re.compile(r"^\s*Siguiente\s*$", re.I)),
            page.locator("button").filter(has_text=re.compile(r"^\s*Siguiente\s*$", re.I)),
        ])
        if next_btn is None:
            try:
                text=(await page.locator("body").inner_text(timeout=1000)).replace("\n", " | ")[:1200]
            except Exception:
                text=""
            raise RuntimeError(
                "No encontré Siguiente ni ENVIAR al avanzar hacia el resumen. "
                f"Texto visible: {text!r}"
            )
        try:
            await next_btn.click(timeout=5000)
        except Exception:
            await next_btn.evaluate("el => el.click()")
        await page.wait_for_timeout(700)

    raise RuntimeError("No pude llegar al botón ENVIAR después de completar la denuncia.")

async def _save_pdf_from_final_page(page, output_dir: Path, logger, timeout_ms: int = 600000, download_spool: Path | None = None) -> Path:
    """Wait for Provincia's official PDF after ENVIAR/final CAPTCHA.

    New popup tabs can download and close almost instantly, so listeners are
    attached at context level before waiting. This avoids missing a PDF merely
    because the popup disappears before the polling loop sees it.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_path = output_dir / f"DENUNCIA_{stamp}.pdf"
    context = page.context
    loop = asyncio.get_running_loop()
    downloads = asyncio.Queue()
    pdf_urls = asyncio.Queue()
    attached = set()
    saved_pdf = loop.create_future()

    async def _persist_download_immediately(dl):
        """Persist the download as soon as Playwright emits it.

        Provincia can close the popup/window immediately after starting the PDF
        download. If we only queue the Download object and call save_as later,
        the underlying artifact may already be gone and Playwright raises
        TargetClosedError. Saving in the event turn minimizes that race.
        """
        try:
            suggested = dl.suggested_filename or default_path.name
            if not suggested.lower().endswith(".pdf"):
                suggested = default_path.name
            path = output_dir / suggested
            await dl.save_as(str(path))
            if not saved_pdf.done():
                saved_pdf.set_result(path)
            logger.info("[DENUNCIAS] PDF persistido inmediatamente: %s", path)
        except Exception as exc:
            logger.warning("[DENUNCIAS] No pude persistir inmediatamente la descarga: %s", exc)

    def on_download(dl):
        try:
            downloads.put_nowait(dl)
            loop.create_task(_persist_download_immediately(dl))
        except Exception:
            pass

    def on_response(resp):
        try:
            url = str(resp.url or "")
            headers = resp.headers or {}
            ctype = str(headers.get("content-type", "")).lower()
            dispo = str(headers.get("content-disposition", "")).lower()
            if "application/pdf" in ctype or ".pdf" in url.lower() or "pdf" in dispo:
                pdf_urls.put_nowait(url)
        except Exception:
            pass

    def attach(pg):
        if pg in attached:
            return
        attached.add(pg)
        try:
            pg.on("download", on_download)
            pg.on("response", on_response)
        except Exception:
            pass

    for pg in list(context.pages):
        attach(pg)
    context.on("page", attach)

    async def save_download(dl):
        # The event handler above may already have persisted this download.
        if saved_pdf.done():
            return saved_pdf.result()
        suggested = dl.suggested_filename or default_path.name
        if not suggested.lower().endswith(".pdf"):
            suggested = default_path.name
        path = output_dir / suggested
        try:
            await dl.save_as(str(path))
            logger.info("[DENUNCIAS] PDF descargado: %s", path)
            return path
        except Exception as exc:
            # If Provincia closed the browser between the download event and
            # save_as(), fall back to the browser downloads spool on disk.
            logger.warning("[DENUNCIAS] save_as falló (%s). Buscando PDF en spool…", exc)
            spool_pdf = _copy_pdf_from_spool(download_spool, default_path)
            if spool_pdf is not None:
                logger.info("[DENUNCIAS] PDF recuperado desde spool: %s", spool_pdf)
                return spool_pdf
            raise

    def _copy_pdf_from_spool(spool: Path | None, destination: Path) -> Path | None:
        if spool is None or not spool.exists():
            return None
        try:
            candidates = sorted(
                (x for x in spool.iterdir() if x.is_file()),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return None
        for src in candidates:
            try:
                data = src.read_bytes()
                if len(data) >= 4 and data[:4] == b"%PDF":
                    destination.write_bytes(data)
                    return destination
            except Exception:
                continue
        return None

    logger.info(
        "[DENUNCIAS] Si aparece el CAPTCHA final, completalo manualmente. "
        "SmartPost esperará el PDF aunque Provincia abra y cierre una pestaña."
    )

    deadline = loop.time() + timeout_ms / 1000
    no_pages_since = None
    while loop.time() < deadline:
        if saved_pdf.done():
            return saved_pdf.result()

        spool_pdf = _copy_pdf_from_spool(download_spool, default_path)
        if spool_pdf is not None:
            logger.info("[DENUNCIAS] PDF detectado directamente en spool: %s", spool_pdf)
            return spool_pdf

        # A popup may have emitted download before it closed. Always drain these
        # queues BEFORE deciding that all tabs being closed is an error.
        try:
            dl = downloads.get_nowait()
            return await save_download(dl)
        except asyncio.QueueEmpty:
            pass

        try:
            pdf_url = pdf_urls.get_nowait()
        except asyncio.QueueEmpty:
            pdf_url = None
        if pdf_url:
            try:
                response = await context.request.get(pdf_url)
                if response.ok:
                    body = await response.body()
                    if body[:4] == b"%PDF" or len(body) > 500:
                        default_path.write_bytes(body)
                        logger.info("[DENUNCIAS] PDF recuperado desde respuesta web: %s", default_path)
                        return default_path
            except Exception:
                pass

        open_pages = [pg for pg in context.pages if not pg.is_closed()]
        for pg in open_pages:
            attach(pg)
            try:
                link = await _first_visible([
                    pg.get_by_role("link", name=re.compile(r"pdf|descargar|imprimir", re.I)),
                    pg.get_by_role("button", name=re.compile(r"pdf|descargar|imprimir", re.I)),
                    pg.locator("a[href*='.pdf' i]"),
                ])
            except Exception:
                link = None
            if link is not None:
                try:
                    href = await link.get_attribute("href")
                except Exception:
                    href = None
                if href and ".pdf" in href.lower():
                    try:
                        response = await context.request.get(href)
                        if response.ok:
                            default_path.write_bytes(await response.body())
                            logger.info("[DENUNCIAS] PDF descargado: %s", default_path)
                            return default_path
                    except Exception:
                        pass
                try:
                    await link.click(timeout=2500)
                except Exception:
                    try:
                        await link.evaluate("el => el.click()")
                    except Exception:
                        pass

        if not open_pages:
            if no_pages_since is None:
                no_pages_since = loop.time()
            elif loop.time() - no_pages_since > 20.0:
                # One last drain: very fast popup/download events can arrive just
                # after the page closes.
                try:
                    dl = await asyncio.wait_for(downloads.get(), timeout=1.0)
                    return await save_download(dl)
                except Exception:
                    spool_pdf = _copy_pdf_from_spool(download_spool, default_path)
                    if spool_pdf is not None:
                        logger.info("[DENUNCIAS] PDF recuperado tras cierre del navegador: %s", spool_pdf)
                        return spool_pdf
                    raise RuntimeError(
                        "Provincia cerró todas las pestañas y no emitió una descarga PDF detectable. "
                        "La denuncia pudo haberse enviado, pero SmartPost no recibió el archivo oficial."
                    )
        else:
            no_pages_since = None

        await asyncio.sleep(0.25)

    raise RuntimeError(
        "No pude obtener el PDF oficial dentro del tiempo de espera. "
        "Completá el CAPTCHA final y, si aparece, tocá Descargar PDF; SmartPost seguirá escuchando la descarga."
    )


async def _has_first_form(page) -> bool:
    """Return True when the first denunciante step is actually rendered."""
    try:
        item = await _visible_field_in_scope(page, r"Apellido", ["Apellido"])
        if item is not None:
            return True
    except Exception:
        pass
    try:
        return await page.get_by_text(re.compile(r"Datos del denunciante", re.I)).first.is_visible()
    except Exception:
        return False



async def _accept_terms_if_present(page, logger):
    """Accept Provincia's Terms & Conditions gate when the deep link opens it.

    The official site can show a TÉRMINOS Y CONDICIONES screen before rendering
    the complainant form. Clicking ACEPTO is part of the normal user flow; this
    helper only advances that gate and does not touch CAPTCHA challenges.
    """
    try:
        body_text = (await page.locator("body").inner_text(timeout=1500)).strip()
    except Exception:
        body_text = ""

    if not re.search(r"T[ÉE]RMINOS\s+Y\s+CONDICIONES", body_text, re.I):
        return False

    logger.info("[DENUNCIAS] Términos y condiciones detectados. Pulsando ACEPTO…")
    candidates = [
        page.get_by_role("button", name=re.compile(r"^\s*ACEPTO\s*$", re.I)),
        page.locator("button").filter(has_text=re.compile(r"^\s*ACEPTO\s*$", re.I)),
        page.locator("[role='button']").filter(has_text=re.compile(r"^\s*ACEPTO\s*$", re.I)),
        page.get_by_text(re.compile(r"^\s*ACEPTO\s*$", re.I), exact=True),
    ]
    button = await _first_visible(candidates)
    if button is None:
        raise RuntimeError("Aparecieron los Términos y Condiciones, pero no encontré el botón 'ACEPTO'.")

    try:
        await button.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    try:
        await button.click(timeout=5000)
    except Exception:
        # Angular/Material can occasionally intercept the normal Playwright click.
        await button.evaluate("el => el.click()")

    await page.wait_for_timeout(900)
    logger.info("[DENUNCIAS] Términos aceptados. Continuando al formulario…")
    return True


async def _ensure_robo_otros_form(page, logger, captcha_timeout_seconds: int = 600):
    """Open the official Robo/Hurto - OTROS deep link directly.

    The Denuncias module must use the exact URL requested by operations:
    https://seguridad.gba.gob.ar/#/robo-otros

    We do not navigate through the home/category menu. If the SPA initially
    redirects to #/home while bootstrapping, retry the exact deep link a few
    times and wait for the first form. CAPTCHA, if presented, remains manual.
    """
    target = "https://seguridad.gba.gob.ar/#/robo-otros"
    if await _has_first_form(page):
        return

    for attempt in range(3):
        logger.info("[DENUNCIAS] Abriendo acceso directo Robo/Hurto - OTROS (%s/3)…", attempt + 1)
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        await page.wait_for_timeout(1200)

        # Fresh sessions often stop at the official Terms & Conditions gate.
        # Advance it before looking for the first form fields.
        await _accept_terms_if_present(page, logger)

        if await _has_first_form(page):
            return

        # If the site presents a verifier before rendering the form, let the
        # operator solve it and retry the same direct URL afterwards.
        try:
            recaptcha_present = False
            for frame in page.frames:
                if await frame.locator("#recaptcha-anchor").count():
                    recaptcha_present = True
                    break
            if await page.locator("textarea[name='g-recaptcha-response']").count():
                recaptcha_present = True
            if recaptcha_present:
                await _wait_recaptcha_solved(page, logger, captcha_timeout_seconds)
                await page.wait_for_timeout(600)
                await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1000)
                await _accept_terms_if_present(page, logger)
                if await _has_first_form(page):
                    return
        except TimeoutError:
            raise
        except Exception:
            pass

    try:
        body = (await page.locator("body").inner_text(timeout=1500)).strip().replace("\n", " | ")[:900]
    except Exception:
        body = ""
    raise RuntimeError(
        "No pude abrir el formulario directo Robo/Hurto - OTROS en "
        f"{target}. La web quedó en {page.url}. Texto visible: {body!r}"
    )


async def submit_gba_denuncia(
    cfg: dict,
    driver: dict,
    incident: dict,
    narrative: str,
    logger,
    dry_run: bool = False,
) -> Path | None:
    """Fill the official Buenos Aires form. CAPTCHA remains manual.

    In dry_run mode the function stops before the final submission and does not
    produce/send a complaint.
    """
    dcfg = cfg.get("denuncias") or {}
    url = str(dcfg.get("gba_url") or "https://seguridad.gba.gob.ar/#/robo-otros")
    output_dir = resolve_path(cfg, "denuncias_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    download_spool = output_dir / (".pw_download_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    download_spool.mkdir(parents=True, exist_ok=True)

    # Reuse a dedicated Provincia profile when possible. Besides preserving the
    # normal browser state, this tends to make the manual reCAPTCHA less tedious
    # than launching a brand-new incognito-style context on every complaint.
    # If the profile is locked/corrupt after an interrupted run, fall back to a
    # fresh browser automatically instead of freezing the workflow.
    async with async_playwright() as p:
        logger.info("[DENUNCIAS] Abriendo navegador de Provincia…")
        profile = resolve_path(cfg, "denuncias_profile")
        profile.mkdir(parents=True, exist_ok=True)
        browser = None
        persistent = False
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                downloads_path=str(download_spool),
                accept_downloads=True,
                viewport={"width": 1365, "height": 900},
                timeout=30000,
            )
            persistent = True
            logger.info("[DENUNCIAS] Perfil de Provincia reutilizado.")
        except Exception as exc:
            logger.warning("[DENUNCIAS] No pude reutilizar el perfil (%s). Uso navegador temporal.", exc)
            browser = await p.chromium.launch(headless=False, downloads_path=str(download_spool), timeout=30000)
            context = await browser.new_context(
                accept_downloads=True, viewport={"width": 1365, "height": 900}
            )
        try:
            pages = list(context.pages)
            page = pages[0] if pages else await context.new_page()
            logger.info("[DENUNCIAS] Navegador abierto. Cargando formulario…")
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # The site may redirect a fresh/deep-linked session to #/home. Navigate the
            # real UI to DENUNCIÁ -> Robo/Hurto -> OTROS before trying to fill fields.
            await _ensure_robo_otros_form(
                page, logger, int(dcfg.get("captcha_timeout_seconds", 600))
            )

            await _fill_named(page, r"Apellido", driver.get("surname", ""), ["Apellido"])
            await _fill_named(page, r"Nombre", driver.get("name", ""), ["Nombre"])
            await _fill_named(page, r"Número de Documento|Numero de Documento", driver.get("dni", ""), ["Número de Documento", "Numero de Documento"])
            await _fill_named(page, r"Fecha de nacimiento", driver.get("birth_date", ""), ["Fecha de nacimiento"])
            gender = str(driver.get("gender", "")).strip()
            if not gender:
                raise RuntimeError("Falta seleccionar el género real del denunciante.")
            await _set_radio(page, "Género", gender)
            await _fill_named(page, r"Prefijo Teléfono|Prefijo Telefono", driver.get("phone_prefix", ""), ["Prefijo Teléfono", "Prefijo Telefono"], required=False)
            await _fill_named(page, r"Número Teléfono|Numero Telefono", driver.get("phone_number", ""), ["Número Teléfono", "Numero Telefono"], required=False)
            await _fill_named(page, r"Correo Electrónico|Correo Electronico", driver.get("email", ""), ["Correo Electrónico", "Correo Electronico"], required=False)
            if not any(str(driver.get(k, "")).strip() for k in ("phone_number", "email")):
                raise RuntimeError("La web exige al menos una vía de contacto real (teléfono o email).")

            await _click_text(page, r"Siguiente")
            await _wait_recaptcha_solved(page, logger, int(dcfg.get("captcha_timeout_seconds", 600)))

            await _fill_named(page, r"Fecha del hecho", incident.get("date", ""), ["Fecha del hecho"])
            await _fill_named(page, r"Hora del hecho", incident.get("time", ""), ["Hora del hecho"])
            await _select_partido(page, str(incident.get("partido", "")))
            await _fill_named(page, r"Localidad/Barrio", incident.get("locality", ""), ["Localidad/Barrio"], required=False)
            # Provincia puede ofrecer barrios/localidades alternativos. Cuando
            # aparezca ese autocomplete, aceptar automáticamente la primera opción.
            await _choose_first_locality_suggestion(page, logger)
            await _fill_named(page, r"Calle", incident.get("street", ""), ["Calle"])
            await _fill_named(page, r"Número|Numero", incident.get("number", ""), ["Número", "Numero"])
            await _fill_named(page, r"Esquina más cercana|Esquina mas cercana", incident.get("corner", ""), ["Esquina más cercana", "Esquina mas cercana"], required=False)
            await _fill_named(page, r"Detalle de la ubicación|Detalle de la ubicacion", incident.get("location_detail", ""), ["Detalle de la ubicación", "Detalle de la ubicacion"], required=False)
            await _click_text(page, r"Validar dirección|Validar direccion", required=False)
            # Provincia puede tardar unos segundos en mostrar la verificación.
            # Si aparece, siempre elegir "Ignorar y continuar" y esperar a que
            # el modal desaparezca antes de tocar Siguiente.
            await _ignore_address_verification_if_present(page, logger, timeout_ms=8000)
            await page.wait_for_timeout(300)
            await _click_text(page, r"Siguiente", required=False)
            await _ensure_characteristics_step(page, logger)

            violence = str(incident.get("violence", "")).strip()
            if violence not in {"Sí", "Si", "No"}:
                raise RuntimeError("Seleccioná si existió violencia física o daños materiales antes de continuar.")
            await _set_radio(page, "violencia física o daños materiales", violence)
            detail = await _first_visible([
                page.get_by_label(re.compile(r"Detalle de los hechos ocurridos", re.I)),
                page.get_by_placeholder(re.compile(r"Detalle de los hechos ocurridos", re.I)),
                page.locator("textarea").filter(has=page.locator("xpath=..")),
            ])
            if detail is None:
                detail = page.locator("textarea").first
            await detail.fill(narrative)

            if dry_run:
                logger.info("[DENUNCIAS] PRUEBA: formulario preparado. No se finaliza la denuncia ni se envía WhatsApp.")
                # Keep the browser visible briefly so the user can review it.
                await page.wait_for_timeout(int(dcfg.get("dry_run_review_ms", 15000)))
                return None

            # Avanzar Evidencias -> Resumen y tocar ENVIAR. El CAPTCHA final
            # sigue siendo manual; a partir de ahí solo esperamos el PDF oficial.
            await _click_text(page, r"Siguiente")
            await _advance_to_send(page, logger)
            return await _save_pdf_from_final_page(
                page, output_dir, logger,
                int(dcfg.get("final_pdf_timeout_seconds", 600)) * 1000,
                download_spool=download_spool,
            )
        finally:
            try:
                await context.close()
            finally:
                if browser is not None:
                    await browser.close()
