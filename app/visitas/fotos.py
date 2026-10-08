"""Consulta de visitas de hoy. No cambia estados ni genera reportes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from playwright.async_api import async_playwright

from app.busqueda_guias.service import (
    _details_from_row, _photo_from_payload, _scrape_labeled_values, _merge_show,
)
from app.cambio_estado.service import _find_rows
from app.core.config import epresis_settings, resolve_path
from app.descarga.auth import ensure_authenticated, extract_csrf_token, navigate_to_guide_search
from app.descarga.epresis_api import EpresisAPI

# IDs existentes en config.default.yaml. Los demás estados de VISITAS no aplican.
VISIT_STATE_IDS = (127, 119, 183, 117)


def today_visits() -> str:
    # Uruguay: UTC-3. Independiente de la zona horaria de Windows o Render.
    return datetime.now(timezone(timedelta(hours=-3))).date().isoformat()


def _total(data):
    if isinstance(data, str):
        try:
            return _total(json.loads(data))
        except (ValueError, TypeError):
            return None
    if isinstance(data, dict):
        for key in ('total', 'recordsFiltered', 'totalRows', 'recordsTotal'):
            value = data.get(key)
            if value is not None and str(value).isdigit():
                return int(value)
        for key in ('data', 'result', 'results'):
            found = _total(data.get(key))
            if found is not None:
                return found
    return None


async def collect_visit_rows(api, date: str) -> list[dict]:
    """Recorre toda la grilla, incluso si Epresis impone su propio tamaño de página."""
    offset, seen, rows = 0, set(), []
    while True:
        pairs = api.make_visits_payload(datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y'), list(VISIT_STATE_IDS), False)
        pairs = [(k, str(offset) if k == 'offset' else '100' if k == 'limit' else v) for k, v in pairs]
        data = await api._post_pairs(api.settings['filter_path'], pairs, 'consultar visitas con foto')
        batch = _find_rows(data)
        total = _total(data)
        if not batch:
            if (total is None and api.filter_result_count(data) != 0) or (total is not None and offset < total):
                raise RuntimeError('No se pudo verificar que la lista de visitas esté completa. Reintentá la consulta.')
            break
        previous = len(seen)
        for row in batch:
            guide = str(row.get('id') or row.get('retiro_id') or '').strip()
            if not guide.isdigit():
                raise RuntimeError('Epresis devolvió una visita sin número de guía válido.')
            if guide not in seen:
                seen.add(guide)
                rows.append(row)
        if len(seen) == previous:
            raise RuntimeError('Epresis repitió una página de visitas. Reintentá para obtener la lista completa.')
        offset += len(batch)
        if total is not None and offset >= total:
            if len(seen) < total:
                raise RuntimeError('La lista cambió durante la consulta. Reintentá para verificar todas las visitas.')
            break
    return rows


async def photo_from_guide_page(page) -> bool:
    """Cuenta imágenes o enlaces de evidencia; no botones vacíos para cargar fotos.

    Usa el mismo show de Búsqueda de guías. Los errores se propagan para no
    convertir fallas de consulta en un resultado 'No'.
    """
    return bool(await page.evaluate(r'''() => {
      const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
      const excluded=/(logo|avatar|perfil|distribuidor|chofer|placeholder|no[-_ ]?image|sin[-_ ]?foto|default)/i;
      const photo=/(foto|photo|imagen|image|evidencia|proof)/i;
      const valid=s=>!!s && s!=='#' && !/^(javascript:|about:)/i.test(s);
      for(const el of document.querySelectorAll('img[src],a[href],[data-lightbox],[data-fancybox]')) {
        const src=el.getAttribute('href')||el.getAttribute('src')||'';
        if(!valid(src)) continue;
        const context=norm(src+' '+(el.getAttribute('alt')||'')+' '+(el.getAttribute('title')||'')+' '+(el.closest('tr,.form-group,.card,.panel')?.textContent||''));
        if(excluded.test(norm(src+' '+(el.getAttribute('alt')||'')))) continue;
        const imageFile=/\.(jpe?g|png|webp|gif)(?:[?#]|$)/i.test(src)||/^data:image\//i.test(src);
        if(imageFile && (photo.test(context)||el.hasAttribute('data-lightbox')||el.hasAttribute('data-fancybox'))) return true;
        if(el.tagName==='IMG' && photo.test(context)) return true;
      }
      return false;
    }'''))


async def inspect_visit(page, row: dict, settings: dict) -> dict:
    guide = str(row.get('id') or row.get('retiro_id'))
    details = _details_from_row(row, guide)
    details['show_url'] = settings['base_url'].rstrip('/') + f'/guias/editar-guia-v2/show/{guide}'
    if _photo_from_payload(row):
        details['foto'] = 'Sí'
        return details
    try:
        response = await page.goto(details['show_url'], wait_until='networkidle', timeout=settings['request_timeout_ms'])
        if response is None or not response.ok or page.url.rstrip('/') != details['show_url'].rstrip('/'):
            raise RuntimeError('No se pudo abrir la ficha de la guía.')
        labeled = await _scrape_labeled_values(page)
        if not labeled:
            raise RuntimeError('La ficha no devolvió datos verificables.')
        details = _merge_show(details, labeled)
        details['foto'] = 'Sí' if await photo_from_guide_page(page) else 'No'
    except Exception:
        details['foto'] = 'Sin verificar'
        details['photo_error'] = 'No se pudo verificar la foto. Volvé a consultar o abrí la guía.'
    return details


async def search_visit_photos(cfg: dict, logger, *, date: str | None = None, progress=None) -> dict:
    date = date or today_visits()
    settings = epresis_settings(cfg)
    async with async_playwright() as p:
        profile = resolve_path(cfg, 'epresis_profile')
        profile.mkdir(parents=True, exist_ok=True)
        context = await p.chromium.launch_persistent_context(user_data_dir=str(profile), headless=bool(settings.get('headless', True)), accept_downloads=False)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_authenticated(page, settings, logger)
            url = await navigate_to_guide_search(page, settings, logger)
            api = EpresisAPI(context.request, settings, await extract_csrf_token(page), logger, referer=url)
            rows = await collect_visit_rows(api, date)
            result = []
            for index, row in enumerate(rows, 1):
                if progress:
                    progress(f'Verificando fotos: {index} de {len(rows)}')
                result.append(await inspect_visit(page, row, settings))
            return {'date': date, 'rows': result, 'total': len(result), 'unverified': sum(r['foto'] == 'Sin verificar' for r in result)}
        finally:
            await context.close()
