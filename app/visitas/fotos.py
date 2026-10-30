"""Consulta de visitas de hoy. No cambia estados ni genera reportes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

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
VISIT_NUMBER_BY_STATE = {127: 1, 119: 2, 183: 3}


def required_visit_photos(row, details=None):
    """Each completed visit needs one photo, including subsequent visits."""
    state = row.get('estado')
    state_id = state.get('id') if isinstance(state, dict) else row.get('estado_id')
    try:
        if int(state_id) in VISIT_NUMBER_BY_STATE:
            return VISIT_NUMBER_BY_STATE[int(state_id)]
    except (TypeError, ValueError):
        pass
    text = ' '.join(str(value or '') for value in (
        (details or {}).get('estado'), state, row.get('estado_nombre'), row.get('estado_codigo'),
    ))
    text = ''.join(c for c in unicodedata.normalize('NFD', text.upper()) if not unicodedata.combining(c))
    match = re.search(r'(\d+)\s*(?:[°ºª.]|RA|DA|TA|ERA|ER|RO|DO)?\s*VISITA|\b(\d+)RVT\b', text)
    if match:
        return max(1, int(match.group(1) or match.group(2)))
    for word, count in (('PRIMERA', 1), ('SEGUNDA', 2), ('TERCERA', 3), ('CUARTA', 4)):
        if re.search(r'\b' + word + r'\s+VISITA\b', text):
            return count
    # Reprogramación does not specify an additional completed visit.
    return 1


def photo_count_from_payload(payload):
    """A conservative lower bound; duplicate links/metadata count only once.

    A photo flag is not an exact count. It can avoid a request for visit one,
    but cannot establish that visit two or three has all its evidence.
    """
    urls, lower_bounds = set(), [0]
    photo = re.compile(r'foto|photo|imagen|image|evidencia|proof', re.I)
    excluded = re.compile(r'distribuidor|chofer|perfil|avatar|logo|cliente|placeholder|no[-_ ]?image|sin[-_ ]?foto|default', re.I)

    def walk(value, path='', evidence=False):
        if excluded.search(path):
            return
        if isinstance(value, dict):
            if evidence:
                # One evidence object may expose both original and thumbnail.
                for key in ('url', 'href', 'archivo', 'path', 'src', 'original', 'thumbnail'):
                    if isinstance(value.get(key), str) and value[key].strip():
                        walk(value[key], path + ' ' + key, True)
                        return
            for key, child in value.items():
                walk(child, path + ' ' + str(key), evidence or bool(photo.search(str(key))))
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child, path, evidence)
        elif evidence and value:
            if isinstance(value, bool):
                lower_bounds.append(int(value))
            elif isinstance(value, (int, float)):
                if value > 0 and re.search(r'cantidad|count|total', path, re.I):
                    lower_bounds.append(int(value))
                elif value > 0:
                    lower_bounds.append(1)
            else:
                value = str(value).strip()
                if excluded.search(value):
                    return
                if re.search(r'\.(jpe?g|png|webp|gif)(?:[?#]|$)', value, re.I) or value.startswith(('http://', 'https://', '/', 'data:image/')):
                    parts = urlsplit(value)
                    params = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in ('w', 'h', 'width', 'height', 'quality', 'thumbnail', 'thumb', 'resize', 'token', 'signature', 'expires')]
                    urls.add(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), '')))
                elif value.isdigit() and re.search(r'cantidad|count|total', path, re.I):
                    lower_bounds.append(int(value))
                elif value.lower() in ('true', 'si', 'sí', 'yes'):
                    lower_bounds.append(1)

    walk(payload)
    return max(len(urls), *lower_bounds)


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


async def photo_count_from_guide_page(page) -> int:
    """Cuenta imágenes o enlaces de evidencia; no botones vacíos para cargar fotos.

    Usa el mismo show de Búsqueda de guías. Los errores se propagan para no
    convertir fallas de consulta en un resultado 'No'.
    """
    return int(await page.evaluate(r'''() => {
      const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
      const excluded=/(logo|avatar|perfil|distribuidor|chofer|placeholder|no[-_ ]?image|sin[-_ ]?foto|default)/i;
      const photo=/(foto|photo|imagen|image|evidencia|proof)/i;
      const valid=s=>!!s && s!=='#' && !/^(javascript:|about:)/i.test(s);
      const photos=new Set();
      for(const el of document.querySelectorAll('img[src],a[href],[data-lightbox],[data-fancybox]')) {
        const anchor=el.tagName==='IMG'?el.closest('a[href]'):null;
        const linked=anchor?.getAttribute('href');
        const src=(valid(linked)&&!excluded.test(linked)?linked:null)||el.getAttribute('href')||el.getAttribute('src')||'';
        if(!valid(src)) continue;
        const context=norm(src+' '+(el.getAttribute('alt')||'')+' '+(el.getAttribute('title')||'')+' '+(el.closest('tr,.form-group,.card,.panel')?.textContent||''));
        if(excluded.test(norm(src+' '+(el.getAttribute('alt')||'')))) continue;
        const imageFile=/\.(jpe?g|png|webp|gif)(?:[?#]|$)/i.test(src)||/^data:image\//i.test(src);
        if((imageFile && photo.test(context)) || el.hasAttribute('data-lightbox') || el.hasAttribute('data-fancybox') ||
           (el.tagName==='IMG' && photo.test(context))) {
          try {
            const url=new URL(src,document.baseURI);url.hash='';
            for(const key of [...url.searchParams.keys()]) if(['w','h','width','height','quality','thumbnail','thumb','resize','token','signature','expires'].includes(key.toLowerCase())) url.searchParams.delete(key);
            photos.add(url.href);
          }
          catch { photos.add(src); }
        }
      }
      return photos.size;
    }'''))


async def photo_from_guide_page(page) -> bool:
    return await photo_count_from_guide_page(page) > 0


def _classify(details, count, required):
    details.update(foto='Sí' if count >= required else 'No',
                   fotos_cargadas=count, fotos_requeridas=required,
                   fotos_pendientes=max(0, required - count),
                   fotos_resumen=f'{count} / {required}')
    return details


async def inspect_visit(page, row: dict, settings: dict) -> dict:
    guide = str(row.get('id') or row.get('retiro_id'))
    details = _details_from_row(row, guide)
    details['show_url'] = settings['base_url'].rstrip('/') + f'/guias/editar-guia-v2/show/{guide}'
    required = required_visit_photos(row, details)
    count = photo_count_from_payload(row)
    if count >= required:
        return _classify(details, count, required)
    try:
        response = await page.goto(details['show_url'], wait_until='networkidle', timeout=settings['request_timeout_ms'])
        if response is None or not response.ok or page.url.rstrip('/') != details['show_url'].rstrip('/'):
            raise RuntimeError('No se pudo abrir la ficha de la guía.')
        labeled = await _scrape_labeled_values(page)
        if not labeled:
            raise RuntimeError('La ficha no devolvió datos verificables.')
        details = _merge_show(details, labeled)
        required = required_visit_photos(row, details)
        # The grid and guide page can expose the same photos: never add them.
        count = max(count, await photo_count_from_guide_page(page))
        return _classify(details, count, required)
    except Exception:
        details['foto'] = 'Sin verificar'
        details['photo_error'] = 'No se pudo verificar la foto. Volvé a consultar o abrí la guía.'
        details['fotos_requeridas'] = required
        details['fotos_resumen'] = f'Sin verificar / {required}'
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
