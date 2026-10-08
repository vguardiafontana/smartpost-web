from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from playwright.async_api import Page

from .credentials import get_credentials


async def _first_visible(page: Page, selectors: list[str]):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if await item.is_visible():
                    return item
        except Exception:
            continue
    return None


async def looks_logged_out(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "iniciar" in url:
        return True
    pwd = await _first_visible(page, ['input[type="password"]'])
    return pwd is not None


async def _goto_checked(page: Page, url: str, settings: dict):
    response = await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=settings["request_timeout_ms"],
    )
    # page.goto puede devolver None en algunos casos de navegación especial.
    if response is not None and response.status >= 400:
        raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir {url}")
    return response


async def perform_login(page: Page, settings: dict, logger) -> None:
    user, password = get_credentials()
    if not user or not password:
        raise RuntimeError(
            "No hay credenciales guardadas. Ejecutá CONFIGURAR_CREDENCIALES.bat una vez."
        )

    login_url = settings.get("login_url") or settings["base_url"]
    await _goto_checked(page, login_url, settings)

    user_loc = await _first_visible(
        page,
        [
            'input[name="email"]',
            'input[name="username"]',
            'input[name="usuario"]',
            'input[name="user"]',
            'input[type="email"]',
            'input[autocomplete="username"]',
            'input[type="text"]',
        ],
    )
    pwd_loc = await _first_visible(page, ['input[name="password"]', 'input[type="password"]'])
    if user_loc is None or pwd_loc is None:
        raise RuntimeError(
            "No pude localizar usuario/contraseña en el login. Ejecutá PROBAR_VISIBLE.bat y revisamos los selectores."
        )

    await user_loc.fill(user)
    await pwd_loc.fill(password)
    submit = await _first_visible(
        page,
        [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Ingresar")',
            'button:has-text("Iniciar")',
            'button:has-text("Login")',
            'button:has-text("Entrar")',
        ],
    )
    if submit is None:
        await pwd_loc.press("Enter")
    else:
        await submit.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=settings["request_timeout_ms"])
    except Exception:
        pass
    await asyncio.sleep(0.4)

    # Volver al home, no a una ruta de guías supuesta.
    await _goto_checked(page, settings["base_url"], settings)
    if await looks_logged_out(page):
        raise RuntimeError("El login no fue aceptado. Revisá usuario/contraseña o selectores.")
    logger.info("Sesión Epresis iniciada correctamente.")


async def ensure_authenticated(page: Page, settings: dict, logger) -> None:
    # El home es la única ruta que damos por segura. No asumimos /guias.
    try:
        await _goto_checked(page, settings["base_url"], settings)
    except Exception:
        # Si el home redirige de una forma rara, probar directamente el login.
        await page.goto(settings.get("login_url") or settings["base_url"], wait_until="domcontentloaded")

    if await looks_logged_out(page):
        logger.info("Sesión vencida o inexistente. Iniciando sesión...")
        await perform_login(page, settings, logger)
    else:
        logger.info("Sesión Epresis válida.")


async def navigate_to_guide_search(page: Page, settings: dict, logger) -> str:
    """Encuentra la pantalla real de BÚSQUEDA DE GUÍA desde el menú.

    No dependemos de una ruta hardcodeada porque /guias puede devolver 404.
    Devuelve la URL real que luego se usa como Referer y para extraer _token.
    """
    # Si el usuario/config ya tiene una URL conocida, probarla primero, pero solo si no da 404.
    configured = str(settings.get("guias_url") or "").strip()
    if configured:
        try:
            response = await page.goto(configured, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
            if response is None or response.status < 400:
                if not await looks_logged_out(page):
                    # No aceptar una página que claramente sea 404 renderizado con HTTP 200.
                    body = (await page.locator("body").inner_text()).strip().lower()
                    if not re.search(r"\b404\b|not found|página no encontrada|pagina no encontrada", body[:2000]):
                        logger.info("Pantalla BÚSQUEDA DE GUÍA: %s", page.url)
                        return page.url
        except Exception:
            pass

    # Regresar al home y esperar a que el menú JS termine de cargar.
    await _goto_checked(page, settings["base_url"], settings)
    await asyncio.sleep(0.7)

    # Extraer todos los enlaces, incluso si el menú está colapsado/oculto.
    links = await page.locator("a").evaluate_all(
        """els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.getAttribute('href') || ''
        }))"""
    )

    def norm(s: str) -> str:
        s = (s or "").upper()
        s = s.replace("Ú", "U").replace("Í", "I").replace("Ó", "O").replace("Á", "A").replace("É", "E")
        return re.sub(r"\s+", " ", s).strip()

    ranked: list[tuple[int, str, str]] = []
    for item in links:
        text = norm(str(item.get("text", "")))
        href = str(item.get("href", "") or "").strip()
        if not href or href.lower().startswith(("javascript:", "#")):
            continue
        score = 0
        if "BUSQUEDA" in text and "GUIA" in text:
            score += 100
        if "GUIA" in text:
            score += 20
        if "busqueda" in href.lower() or "buscar" in href.lower():
            score += 10
        if "guia" in href.lower():
            score += 5
        # Evitar endpoints API/acciones conocidas.
        if any(x in href.lower() for x in ("exportarexcel", "/filter", "/combo")):
            score -= 100
        if score > 0:
            ranked.append((score, text, href))

    ranked.sort(reverse=True, key=lambda x: x[0])
    tried = []
    for score, text, href in ranked:
        target = urljoin(settings["base_url"].rstrip("/") + "/", href)
        if target in tried:
            continue
        tried.append(target)
        try:
            response = await page.goto(target, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
            if response is not None and response.status >= 400:
                continue
            if await looks_logged_out(page):
                continue
            body = (await page.locator("body").inner_text()).strip().lower()
            if re.search(r"\b404\b|not found|página no encontrada|pagina no encontrada", body[:2000]):
                continue
            # Debe contener al menos alguna pista de la pantalla de guías o un token de formulario.
            has_token = await page.locator('input[name="_token"], meta[name="csrf-token"]').count() > 0
            upper_body = norm(body[:12000])
            if has_token or ("GUIA" in upper_body and ("CLIENTE" in upper_body or "EXPORTAR" in upper_body)):
                logger.info("Pantalla BÚSQUEDA DE GUÍA detectada: %s", page.url)
                return page.url
        except Exception:
            continue

    raise RuntimeError(
        "No pude encontrar automáticamente la pantalla BÚSQUEDA DE GUÍA en el menú. "
        "Abrila manualmente en Chrome y copiame la URL completa de la barra de direcciones."
    )


async def extract_csrf_token(page: Page) -> str:
    candidates = [
        'meta[name="csrf-token"]',
        'input[name="_token"]',
    ]
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            if await loc.count():
                value = await loc.get_attribute("content" if sel.startswith("meta") else "value")
                if value:
                    return value
        except Exception:
            pass

    # Fallback: buscar token en el HTML sin depender de la estructura exacta del DOM.
    html = await page.content()
    patterns = [
        r'name=["\']_token["\'][^>]*value=["\']([^"\']+)',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']',
        r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    raise RuntimeError(
        f"No pude obtener el CSRF token (_token) desde la pantalla {page.url}. "
        "La sesión está abierta, pero esa página no contiene el formulario esperado."
    )
