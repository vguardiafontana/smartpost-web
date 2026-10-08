"""Consulta de visitas con memoria acotada para Render; Desktop no usa este módulo."""
from __future__ import annotations

from datetime import datetime

from playwright.async_api import async_playwright

from app.cambio_estado.service import _find_rows
from app.core.config import epresis_settings
from app.descarga.auth import ensure_authenticated, extract_csrf_token, navigate_to_guide_search
from app.descarga.epresis_api import EpresisAPI
from app.visitas.fotos import VISIT_STATE_IDS, _total, inspect_visit, today_visits


PAGE_SIZE = 50
# Destruye también el proceso Chromium y el contexto de peticiones, no sólo el DOM.
BROWSER_BATCH_SIZE = 25


class ReleasedResponseAPI(EpresisAPI):
    async def _json_response(self, response, context):
        try:
            return await super()._json_response(response, context)
        finally:
            # Playwright retiene los cuerpos de APIResponse hasta dispose/close.
            await response.dispose()


async def skip_heavy_resources(route):
    # Sólo interesa el enlace/elemento de la foto. Nunca sus píxeles.
    # CSS, HTML, JS y XHR siguen disponibles para mantener los mismos datos.
    if route.request.resource_type in {'image', 'media', 'font'}:
        await route.abort()
    else:
        await route.continue_()


class VisitBrowser:
    def __init__(self, playwright, settings, logger):
        self.playwright = playwright
        self.settings = settings
        self.logger = logger
        self.browser = self.context = self.page = self.api = None
        self.storage = None
        self.guides_url = None

    async def open(self):
        # El contexto temporal evita acumular caché/historial del perfil persistente.
        self.browser = await self.playwright.chromium.launch(
            headless=True, args=['--disable-dev-shm-usage', '--disable-gpu'],
        )
        self.context = await self.browser.new_context(
            storage_state=self.storage, service_workers='block', accept_downloads=False,
        )
        await self.context.route('**/*', skip_heavy_resources)
        self.page = await self.context.new_page()
        await ensure_authenticated(self.page, self.settings, self.logger)
        self.guides_url = await navigate_to_guide_search(self.page, self.settings, self.logger)
        self.api = ReleasedResponseAPI(self.context.request, self.settings,
                                       await extract_csrf_token(self.page), self.logger,
                                       referer=self.guides_url)

    async def close(self):
        try:
            if self.browser is not None:
                await self.browser.close()
        finally:
            self.browser = self.context = self.page = self.api = None

    async def recycle(self):
        self.storage = await self.context.storage_state()
        await self.close()
        self.logger.info('[VISITAS_FOTOS_WEB] Navegador anterior cerrado; renovando recursos de la consulta.')
        await self.open()

    async def fetch_page(self, date, offset):
        pairs = self.api.make_visits_payload(
            datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y'), list(VISIT_STATE_IDS), False,
        )
        pairs = [(k, str(offset) if k == 'offset' else str(PAGE_SIZE) if k == 'limit' else v) for k, v in pairs]
        return await self.api._post_pairs(self.settings['filter_path'], pairs, 'consultar visitas con foto')


async def iter_visit_pages(session, date):
    """Conserva sólo una página de datos crudos, no todas las guías de Epresis."""
    offset, seen = 0, set()
    while True:
        data = await session.fetch_page(date, offset)
        batch, total = _find_rows(data), _total(data)
        if not batch:
            if (total is None and EpresisAPI.filter_result_count(data) != 0) or (total is not None and offset < total):
                raise RuntimeError('La lista de visitas está incompleta. Volvé a consultar.')
            return
        fresh = []
        for row in batch:
            guide = str(row.get('id') or row.get('retiro_id') or '').strip()
            if not guide.isdigit():
                raise RuntimeError('Epresis devolvió una guía inválida.')
            if guide not in seen:
                seen.add(guide)
                fresh.append(row)
        if not fresh:
            raise RuntimeError('Epresis repitió una página. Volvé a consultar.')
        offset += len(batch)
        if total is not None and offset >= total and len(seen) < total:
            raise RuntimeError('La lista cambió durante la consulta. Volvé a consultar.')
        del data, batch
        yield fresh, total
        del fresh
        if total is not None and offset >= total:
            return


async def search_visit_photos_web(cfg, logger, *, date=None, progress=None):
    date = date or today_visits()
    settings = epresis_settings(cfg)
    results, since_restart = [], 0
    async with async_playwright() as playwright:
        session = VisitBrowser(playwright, settings, logger)
        try:
            await session.open()
            async for batch, total in iter_visit_pages(session, date):
                for row in batch:
                    if since_restart >= BROWSER_BATCH_SIZE:
                        await session.recycle()
                        since_restart = 0
                    if progress:
                        progress(f'Verificando fotos: {len(results) + 1}' + (f' de {total}' if total is not None else ''))
                    # Mismo lector y misma clasificación que el Desktop validado.
                    results.append(await inspect_visit(session.page, row, settings))
                    since_restart += 1
                # Evita retener una página anterior durante la siguiente petición.
                del batch, row
                logger.info('[VISITAS_FOTOS_WEB] %d guías revisadas.', len(results))
            return {'date': date, 'rows': results, 'total': len(results),
                    'unverified': sum(r['foto'] == 'Sin verificar' for r in results)}
        finally:
            await session.close()
