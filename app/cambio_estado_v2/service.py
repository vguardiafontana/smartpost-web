from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path
from app.cambio_estado.service import _filter_guide, _resolve_one
from app.cambio_estado.states import STATE_BY_ID
from app.descarga.epresis_api import EpresisAPI
from app.core.dates import business_now, operation_date
from app.core.async_utils import ordered_map


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", _s(value))


def _dist_code(value: Any) -> str:
    """Normaliza el código de perfil del distribuidor sin perder sufijos APP/P/etc."""
    return re.sub(r"[^A-Z0-9]", "", _s(value).upper())


def _dist_base_dni(value: Any) -> str:
    """DNI base compartido por perfiles como 37424493APP y 37424493P."""
    m = re.match(r"(\d{7,8})", _dist_code(value))
    return m.group(1) if m else _digits(value)


def _find_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("rows", "data", "results", "items", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


async def _post_form(context, url: str, form: dict[str, str], referer: str, timeout_ms: int, label: str):
    response = await context.request.post(
        url,
        form=form,
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        },
        timeout=timeout_ms,
    )
    if response.status in (401, 403, 419):
        raise RuntimeError(f"Sesión/CSRF inválido en {label} (HTTP {response.status}).")
    if not response.ok:
        text = (await response.text())[:500]
        raise RuntimeError(f"HTTP {response.status} en {label}: {text}")
    try:
        return await response.json()
    except Exception as exc:
        text = (await response.text())[:500]
        raise RuntimeError(f"Respuesta no JSON en {label}: {text}") from exc


async def _post_form_raw(context, url: str, form: dict[str, str], referer: str, timeout_ms: int):
    """POST que conserva body/status aun cuando Epresis responde HTTP 500.

    Se usa exclusivamente para el fallback de Rendición: Epresis informa en el
    mensaje de error el recorrido real de una guía cuando se intenta confirmar
    contra otra planilla.
    """
    response = await context.request.post(
        url,
        form=form,
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        },
        timeout=timeout_ms,
    )
    text = await response.text()
    try:
        data = json.loads(text)
    except Exception:
        data = None
    return response.status, data, text[:1000]


def _route_from_rendition_error(data: Any, text: str = "") -> int | None:
    """Extrae `recorrido: 98149` del error real de confirmarRecepcionados."""
    message = ""
    if isinstance(data, dict):
        message = _s(data.get("message"))
    haystack = message or _s(text)
    m = re.search(r"(?:recorrido|planilla)\s*:\s*(\d+)", haystack, flags=re.I)
    return int(m.group(1)) if m else None


def _confirm_payload(csrf: str, planilla_id: int, retiro_ids: list[int], state_id: int,
                     nro_rendicion: int, fecha: str, hora: str) -> dict[str, str]:
    return {
        "_token": csrf,
        "planilla_id": str(planilla_id),
        "seleccion": json.dumps([{"retiro_id": str(int(rid))} for rid in retiro_ids], separators=(",", ":")),
        "estado_id": str(int(state_id)),
        "estado_filter": "",
        "cheque": "",
        "efectivo": "",
        "bultos_retirados": "",
        "observaciones": "",
        "nro_rendicion_chofer": str(nro_rendicion),
        "receptor_fecha_hora": fecha,
        "receptor_fecha_hora_hora": hora,
        "tipo_operacion_id": "",
    }


async def _extract_distributor_from_guide_show(page, base: str, retiro_id: int, timeout_ms: int) -> dict[str, str]:
    """Obtiene el distribuidor exacto enlazado en el show de una guía.

    El ID de /distribuidores/show/<id> es el distribuidor_id que usa Recorridos.
    También extraemos texto/DNI para auditoría y para un fallback por combo.
    """
    url = base.rstrip("/") + f"/guias/editar-guia-v2/show/{retiro_id}"
    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    if response is not None and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} al abrir el detalle de la guía {retiro_id}.")
    data = await page.evaluate(
        r"""() => {
          const clean = s => (s || '').toString().replace(/\s+/g, ' ').trim();
          const anchors = [...document.querySelectorAll('a[href*="/distribuidores/show/"]')];
          let a = anchors.find(x => {
            const root = x.closest('tr,.form-group,.row,td,div') || x.parentElement;
            return /distribuidor/i.test(clean(root?.innerText || root?.textContent));
          }) || anchors[0];
          if (!a) return {};
          const href = a.href || a.getAttribute('href') || '';
          const m = href.match(/\/distribuidores\/show\/(\d+)/i);
          const text = clean(a.innerText || a.textContent || '');
          let rootText = '';
          const root = a.closest('tr,.form-group,.row,td,div') || a.parentElement;
          if (root) rootText = clean(root.innerText || root.textContent || '');
          const cm = (rootText + ' ' + text).match(/(?<![A-Z0-9])(\d{7,8}[A-Z]{0,6})(?![A-Z0-9])/i);
          const code = cm ? cm[1] : '';
          const dm = code.match(/^(\d{7,8})/);
          return {id: m ? m[1] : '', name: text, code, dni: dm ? dm[1] : '', url: href};
        }"""
    )
    return {str(k): _s(v) for k, v in (data or {}).items()}


def _norm_name(value: Any) -> str:
    text = _s(value).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _row_distributor_hint(row: Any) -> dict[str, str]:
    """Extrae ID/DNI/nombre del distribuidor desde cualquier estructura de la guía.

    Epresis no devuelve siempre el distribuidor del mismo modo: algunas guías traen
    un objeto distribuidor, otras sólo un texto visible y otras exponen *_id.
    """
    best: dict[str, str] = {}

    def visit(obj: Any, parent_key: str = "") -> None:
        nonlocal best
        if isinstance(obj, dict):
            # Objetos cuyo nombre de clave indica que son del distribuidor.
            if "distrib" in parent_key.lower():
                did = _s(obj.get("id") or obj.get("distribuidor_id"))
                code = _s(obj.get("codigo") or obj.get("dni") or obj.get("documento"))
                dni = _dist_base_dni(code)
                name = _s(obj.get("full_name") or obj.get("CodeFullName"))
                if not name:
                    ap = _s(obj.get("apellido"))
                    no = _s(obj.get("nombre"))
                    name = ", ".join(x for x in (ap, no) if x)
                if did and not best.get("id"):
                    best["id"] = did
                if code and not best.get("code"):
                    best["code"] = code
                if dni and not best.get("dni"):
                    best["dni"] = dni
                if name and not best.get("name"):
                    best["name"] = name

            for key, value in obj.items():
                lk = str(key).lower()
                if lk in ("distribuidor_id", "distribuidorid", "id_distribuidor") and not best.get("id"):
                    best["id"] = _s(value)
                elif lk in ("distribuidor_dni", "dni_distribuidor", "documento_distribuidor", "distribuidor_codigo"):
                    code = _s(value)
                    if code and not best.get("code"):
                        best["code"] = code
                    if code and not best.get("dni"):
                        best["dni"] = _dist_base_dni(code)
                elif "distrib" in lk and isinstance(value, str):
                    text = _s(value)
                    cm = re.search(r"(?<![A-Z0-9])(\d{7,8}[A-Z]{0,6})(?![A-Z0-9])", text, flags=re.I)
                    if cm and not best.get("code"):
                        best["code"] = cm.group(1)
                    if cm and not best.get("dni"):
                        best["dni"] = _dist_base_dni(cm.group(1))
                    if text and not best.get("name"):
                        # Quita el DNI inicial habitual: 45573374 - APELLIDO, NOMBRE
                        best["name"] = re.sub(r"^\s*\d{7,8}[A-Z]?\s*-\s*", "", text, flags=re.I).strip()
                visit(value, str(key))
        elif isinstance(obj, list):
            for value in obj:
                visit(value, parent_key)

    visit(row)
    return best


async def _extract_distributor_labeled_from_show(page) -> dict[str, str]:
    """Fallback DOM para guías donde el distribuidor no viene como enlace <a>."""
    data = await page.evaluate(
        r"""() => {
          const clean = s => (s || '').toString().replace(/\s+/g, ' ').trim();
          const norm = s => clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
          const els = [...document.querySelectorAll('label,th,td,strong,b,dt,span,div,p')];
          for (const el of els) {
            const label = norm(el.innerText || el.textContent).replace(/[:*]+$/,'').trim();
            if (!(label === 'distribuidor' || label === 'distribuidor recorrido' || label.startsWith('distribuidor:'))) continue;
            const root = el.closest('tr,.form-group,.row') || el.parentElement;
            if (!root) continue;
            const a = root.querySelector('a[href*="/distribuidores/show/"]');
            const href = a ? (a.href || a.getAttribute('href') || '') : '';
            const hm = href.match(/\/distribuidores\/show\/(\d+)/i);
            let text = '';
            const ctl = root.querySelector('input,select,textarea');
            if (ctl) text = clean(ctl.value || ctl.options?.[ctl.selectedIndex]?.textContent || '');
            if (!text && a) text = clean(a.innerText || a.textContent);
            if (!text) {
              const clone = root.cloneNode(true);
              clone.querySelectorAll('label').forEach(x => x.remove());
              text = clean(clone.innerText || clone.textContent);
            }
            const cm = text.match(/(?<![A-Z0-9])(\d{7,8}[A-Z]{0,6})(?![A-Z0-9])/i);
            const code = cm ? cm[1] : '';
            const dm = code.match(/^(\d{7,8})/);
            const name = text.replace(/^\s*\d{7,8}[A-Z]{0,6}\s*-\s*/i,'').trim();
            return {id: hm ? hm[1] : '', code, dni: dm ? dm[1] : '', name, url: href};
          }
          return {};
        }"""
    )
    return {str(k): _s(v) for k, v in (data or {}).items()}


async def _combo_distributor_candidates(context, base: str, referer: str, query: str, timeout_ms: int) -> list[dict[str, str]]:
    """Devuelve todos los perfiles candidatos del distribuidor, preservando `codigo`."""
    q = _s(query)
    if not q:
        return []
    from copy import deepcopy
    cache = getattr(context, "_smartpost_distributor_cache", None)
    if cache is None:
        cache = context._smartpost_distributor_cache = {}
    cache_key = (base, q)
    if cache_key in cache:
        return deepcopy(cache[cache_key])
    url = base.rstrip("/") + "/distribuidores/distribuidores/combo"
    response = await context.request.get(
        url,
        params={"search": q, "page": "1", "per_page": "50"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": referer},
        timeout=timeout_ms,
    )
    if not response.ok:
        return []
    try:
        rows = _find_rows(await response.json())
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for r in rows:
        code = _s(r.get("codigo") or r.get("dni"))
        out.append({
            "id": _s(r.get("id")),
            "code": code,
            "dni": _dist_base_dni(code),
            "name": _s(r.get("full_name") or r.get("CodeFullName") or f"{_s(r.get('apellido'))}, {_s(r.get('nombre'))}"),
        })
    result = [x for x in out if x.get("id")]
    cache[cache_key] = deepcopy(result)
    return result


async def _combo_distributor(context, base: str, csrf: str, referer: str, query: str, timeout_ms: int, expected_name: str = "", expected_code: str = "") -> dict[str, str]:
    """Busca distribuidor priorizando SIEMPRE el código exacto del perfil de la guía."""
    rows = await _combo_distributor_candidates(context, base, referer, query, timeout_ms)
    if not rows:
        return {}
    wanted_code = _dist_code(expected_code or query)
    # Un código con sufijo (APP/P/etc.) identifica inequívocamente el perfil y gana sobre el link/DNI.
    if wanted_code:
        exact_code = [r for r in rows if _dist_code(r.get("code")) == wanted_code]
        if exact_code:
            return exact_code[0]
    wanted_dni = _dist_base_dni(expected_code or query)
    if wanted_dni:
        exact_dni = [r for r in rows if _dist_base_dni(r.get("code") or r.get("dni")) == wanted_dni]
        if len(exact_dni) == 1:
            return exact_dni[0]
    wanted = _norm_name(expected_name or query)
    if wanted:
        named = [r for r in rows if (_norm_name(r.get("name")) == wanted or wanted in _norm_name(r.get("name")) or _norm_name(r.get("name")) in wanted)]
        if len(named) == 1:
            return named[0]
    if len(rows) == 1:
        return rows[0]
    return {}


def _route_payload(csrf: str, distributor_id: str, date_text: str) -> dict[str, str]:
    return {
        "id": "",
        # list-route-json usa el parámetro `sort` para construir el ORDER BY.
        # Si no se envía, Epresis termina ejecutando `order by `` desc` y devuelve HTTP 500.
        "sort": "id",
        "order": "desc",
        "limit": "100",
        "offset": "0",
        "_token": csrf,
        "recorrido_id": "",
        "fecha_recorrido": f"{date_text} - {date_text}",
        "expreso_id": "",
        "colectora": "",
        "nro_recorrido_id": "",
        "sucursal_id": "",
        "distribuidor_id": str(distributor_id),
        "cerrada": "TODAS",
        "guias_pendientes": "TODAS",
        "turno": "",
        "tipo_recorrido_id": "",
        "liquidadas": "TODAS",
    }


def _rendition_list_payload(csrf: str, planilla_id: int, state_id: int | None = None, limit: int = 1000) -> dict[str, str]:
    return {
        "fDesde": "",
        "fHasta": "",
        "planilla": str(planilla_id),
        "retiro": "",
        "lote": "",
        "rendida": "",
        "distribuidor": "",
        "offset": "0",
        "limit": str(limit),
        "order": "asc",
        "sort": "id",
        "efectivo": "",
        "cheque": "",
        "estado": "" if state_id is None else str(state_id),
        "cliente_id": "",
        "_token": csrf,
        "estado_filter": "",
        "sucursal_id": "",
    }


async def _load_planilla_rows(context, base: str, csrf: str, referer: str, planilla_id: int, timeout_ms: int) -> list[dict[str, Any]]:
    data = await _post_form(
        context,
        base.rstrip("/") + "/rendicion/getRendicionChoferesListJson",
        _rendition_list_payload(csrf, planilla_id),
        referer,
        timeout_ms,
        f"consultar planilla {planilla_id}",
    )
    return _find_rows(data)


def _rendition_number_from_text(text: str) -> int | None:
    """Extrae el número de una rendición ya abierta desde el encabezado de Epresis."""
    haystack = _s(text)
    if not haystack:
        return None
    patterns = (
        r"Nro\.?\s*de\s*Rendici[oó]n\s*[:#-]?\s*(\d+)",
        r"Nro\.?\s*Rendici[oó]n\s*[:#-]?\s*(\d+)",
        r"Rendici[oó]n\s*(?:Nro\.?|N[uú]mero)?\s*[:#-]?\s*(\d+)",
    )
    for pattern in patterns:
        m = re.search(pattern, haystack, flags=re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


async def _current_rendition_number(page) -> int | None:
    """Lee la rendición abierta en la pantalla, si existe."""
    try:
        text = await page.locator("body").inner_text(timeout=5000)
        number = _rendition_number_from_text(text)
        if number:
            return number
    except Exception:
        pass

    # Respaldo por si Epresis guarda el número en un input/hidden en alguna versión.
    try:
        values = await page.locator(
            'input[name*="rendicion" i], input[id*="rendicion" i], [data-rendicion]'
        ).evaluate_all(
            "els => els.map(e => e.value || e.getAttribute('data-rendicion') || e.textContent || '')"
        )
        for value in values or []:
            digits = _digits(value)
            if digits:
                return int(digits)
    except Exception:
        pass
    return None


async def _enable_rendition(context, base: str, csrf: str, referer: str, timeout_ms: int, page=None) -> int:
    # Si ya hay una rendición abierta, reutilizarla. Abrir otra devuelve
    # "Existe una rendicion abierta, por favor cierre la misma".
    if page is not None:
        current = await _current_rendition_number(page)
        if current:
            return current

    data = await _post_form(
        context,
        base.rstrip("/") + "/rendicion/habilitarNroRendicion",
        {"_token": csrf},
        referer,
        timeout_ms,
        "habilitar rendición de chofer",
    )
    if isinstance(data, dict) and _s(data.get("status")).lower() == "ok":
        try:
            return int(data.get("message"))
        except Exception as exc:
            raise RuntimeError(f"Epresis no devolvió un Nro. de Rendición válido: {data}") from exc

    message = _s(data.get("message")) if isinstance(data, dict) else ""
    if page is not None and "rendicion abierta" in message.lower():
        # Epresis confirma que existe una abierta: recargar la pantalla y leer
        # el encabezado, por ejemplo "Nro de Rendicion: 248 - Usuario: ...".
        try:
            await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        current = await _current_rendition_number(page)
        if current:
            return current
        raise RuntimeError(
            "Epresis indica que existe una rendición abierta, pero no pude leer su número en la pantalla."
        )

    raise RuntimeError(f"Epresis no pudo habilitar la rendición: {data}")


async def change_state_v2(cfg: dict, identifiers: list[str], state_id: int, logger, selected_date=None) -> list[dict[str, Any]]:
    """Cambio de estado por Rendición de Chofer, agrupado por planilla.

    Seguridad operativa:
    - resuelve cada entrada a retiro_id y deduplica;
    - identifica el distribuidor exacto desde el show de la guía;
    - busca recorridos del distribuidor para la fecha seleccionada;
    - valida que el retiro_id esté realmente dentro de la planilla antes de tocarlo;
    - agrupa y confirma en una sola request todos los retiros de la misma planilla;
    - un error en un pedido/planilla no impide continuar con los demás.
    """
    from app.descarga.auth import ensure_authenticated, extract_csrf_token

    if int(state_id) not in STATE_BY_ID:
        raise RuntimeError(f"Estado no permitido/desconocido: {state_id}")

    settings = epresis_settings(cfg)
    ce = cfg.get("cambio_estado") or {}
    base = settings["base_url"].rstrip("/")
    timeout_ms = int(settings.get("request_timeout_ms", 30000))
    arrival_url = base + str(ce.get("arrival_path") or "/guias/arribo_paquetes")
    rendition_url = base + "/rendicion/rendicion_chofer"
    selected = operation_date(selected_date)
    date_text = selected.strftime("%d/%m/%Y")
    logger.info("[CAMBIO ESTADO V2] Fecha seleccionada: %s (America/Montevideo)", date_text)

    results: list[dict[str, Any]] = []

    async with async_playwright() as p:
        profile = resolve_path(cfg, "epresis_profile")
        profile.mkdir(parents=True, exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=bool(settings.get("headless", True)),
            accept_downloads=False,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_authenticated(page, settings, logger)

            # Token fresco desde una pantalla autenticada conocida.
            response = await page.goto(arrival_url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir Arribo de Paquetes.")
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger, referer=arrival_url)
            settings["remito_search_path"] = str(ce.get("remito_search_path") or "/tracker/searchByRemitoCliente")
            settings["guia_agente_search_path"] = str(ce.get("guia_agente_search_path") or "/tracker/searchByGuiaAgente")

            # 1. Resolver y deduplicar entradas.
            seen: set[int] = set()
            resolved: list[dict[str, Any]] = []
            async def resolve_input(entry):
                idx, value = entry
                logger.info("[CAMBIO ESTADO V2] Resolviendo %s/%s: %s", idx, len(identifiers), value)
                return await _resolve_one(context, api, csrf, settings, arrival_url, _s(value), logger)
            resolved_inputs = await ordered_map(
                enumerate(identifiers, start=1), resolve_input
            )
            for idx, raw in enumerate(identifiers, start=1):
                value = _s(raw)
                try:
                    info = resolved_inputs[idx - 1]
                    if isinstance(info, BaseException):
                        raise info
                    item = info.to_dict()
                except Exception as exc:
                    item = {"input_value": value, "resolution_status": "error", "message": str(exc)}
                rid = item.get("retiro_id")
                if item.get("resolution_status") == "resolved" and rid:
                    rid = int(rid)
                    if rid in seen:
                        item["resolution_status"] = "duplicate"
                        item["message"] = "La misma guía ya fue incluida en este lote."
                    else:
                        seen.add(rid)
                        current_state_id = item.get("current_state_id")
                        current_state = _s(item.get("current_state"))
                        target_state = _s(STATE_BY_ID[int(state_id)])
                        same_state = False
                        try:
                            same_state = current_state_id not in (None, "") and int(current_state_id) == int(state_id)
                        except Exception:
                            same_state = False
                        if not same_state and current_state:
                            same_state = current_state.casefold() == target_state.casefold()
                        if same_state:
                            item["change_status"] = "already_assigned"
                            item["change_message"] = "Estado ya asignado."
                            logger.info(
                                "[CAMBIO ESTADO V2] guía %s: el estado %s ya estaba asignado; no se realiza ningún cambio.",
                                rid, target_state,
                            )
                        else:
                            resolved.append(item)
                item["selected_date"] = selected.isoformat()
                results.append(item)

            if not resolved:
                return results

            # 2. Obtener distribuidor exacto de cada guía y agrupar por distribuidor_id.
            # Si no puede resolverse, no abortamos: Rendición puede revelar el recorrido
            # real en su mensaje de error al confirmar contra otra planilla.
            by_distributor: dict[str, list[dict[str, Any]]] = defaultdict(list)
            route_probe_items: list[dict[str, Any]] = []
            for item in resolved:
                rid = int(item["retiro_id"])
                try:
                    dist = await _extract_distributor_from_guide_show(page, base, rid, timeout_ms)
                    row = None
                    if not dist.get("id"):
                        # Algunas guías muestran el distribuidor como texto/select y no como enlace.
                        labeled_dist = await _extract_distributor_labeled_from_show(page)
                        if labeled_dist:
                            dist = {**dist, **{k: v for k, v in labeled_dist.items() if v}}

                    # Leemos también la estructura de la guía aunque el show tenga link: el `codigo`
                    # visible/estructurado (ej. 37424493APP) es la fuente autoritativa para distinguir
                    # perfiles duplicados de la misma persona.
                    row = await _filter_guide(api, str(rid)) or {}
                    hint = _row_distributor_hint(row)
                    guide_code = hint.get("code") or dist.get("code") or ""
                    if guide_code:
                        exact = await _combo_distributor(
                            context, base, csrf, arrival_url, guide_code, timeout_ms,
                            expected_name=hint.get("name") or dist.get("name", ""), expected_code=guide_code,
                        )
                        if exact:
                            # El código exacto de la guía pisa un link ambiguo hacia otro perfil.
                            dist = {**dist, **exact}

                    if not dist.get("id"):
                        # Fallback estructurado: el endpoint de búsqueda de guía puede traer
                        # distribuidor_id, un objeto distribuidor o sólo "DNI - APELLIDO, NOMBRE".
                        if hint.get("id"):
                            dist = {**dist, **hint}
                        else:
                            query = hint.get("dni") or hint.get("name")
                            if query:
                                combo = await _combo_distributor(
                                    context, base, csrf, arrival_url, query, timeout_ms, expected_name=hint.get("name", ""), expected_code=hint.get("code", "")
                                )
                                if combo:
                                    dist = {**dist, **combo}

                    if not dist.get("id"):
                        # Último intento: combinar cualquier texto visible de distribuidor
                        # que haya quedado en el show con el combo oficial de Epresis.
                        query = dist.get("dni") or dist.get("name")
                        if query:
                            combo = await _combo_distributor(
                                context, base, csrf, arrival_url, query, timeout_ms, expected_name=dist.get("name", ""), expected_code=dist.get("code", "")
                            )
                            if combo:
                                dist = {**dist, **combo}

                    if not dist.get("id"):
                        item["distribuidor_dni"] = dist.get("dni", "")
                        item["distribuidor_nombre"] = dist.get("name", "")
                        item["route_resolution"] = "fallback_rendicion"
                        route_probe_items.append(item)
                        logger.warning(
                            "[CAMBIO ESTADO V2] guía %s: distribuidor no resuelto; "
                            "usaré fallback de Rendición para detectar su recorrido.",
                            rid,
                        )
                        continue
                    item["distribuidor_id"] = dist.get("id", "")
                    item["distribuidor_codigo"] = dist.get("code", "") or hint.get("code", "")
                    item["distribuidor_dni"] = dist.get("dni", "") or _dist_base_dni(item.get("distribuidor_codigo"))
                    item["distribuidor_nombre"] = dist.get("name", "")
                    by_distributor[str(dist["id"])].append(item)
                    logger.info(
                        "[CAMBIO ESTADO V2] guía %s → distribuidor %s %s",
                        rid, dist.get("id"), dist.get("name") or dist.get("dni") or "",
                    )
                except Exception as exc:
                    item["change_status"] = "error"
                    item["change_message"] = str(exc)
                    logger.warning("[CAMBIO ESTADO V2] guía %s: %s", rid, exc)

            # 3. Buscar planillas de cada distribuidor y validar pertenencia de cada retiro.
            by_planilla: dict[int, list[dict[str, Any]]] = defaultdict(list)
            route_url = base + "/recorridos/list-route-json"
            route_referer = base + "/recorridos/list-route"
            for distributor_id, items in by_distributor.items():
                pending = {int(x["retiro_id"]): x for x in items if not x.get("change_status")}
                if not pending:
                    continue
                try:
                    route_data = await _post_form(
                        context,
                        route_url,
                        _route_payload(csrf, distributor_id, date_text),
                        route_referer,
                        timeout_ms,
                        f"buscar recorridos distribuidor {distributor_id}",
                    )
                    routes = _find_rows(route_data)
                    # Más nueva primero, como la pantalla (order desc). Si el retiro no está, seguimos con la siguiente.
                    routes.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
                    logger.info(
                        "[CAMBIO ESTADO V2] distribuidor %s: %s planilla(s) del %s.",
                        distributor_id, len(routes), date_text,
                    )
                    for route in routes:
                        if not pending:
                            break
                        try:
                            planilla_id = int(route.get("id"))
                        except Exception:
                            continue
                        rows = await _load_planilla_rows(context, base, csrf, rendition_url, planilla_id, timeout_ms)
                        present = {int(r["retiro_id"]) for r in rows if _s(r.get("retiro_id")).isdigit()}
                        matched = [rid for rid in list(pending) if rid in present]
                        if matched:
                            logger.info(
                                "[CAMBIO ESTADO V2] planilla %s: %s pedido(s) del lote encontrado(s).",
                                planilla_id, len(matched),
                            )
                        for rid in matched:
                            item = pending.pop(rid)
                            item["planilla_id"] = planilla_id
                            by_planilla[planilla_id].append(item)
                    # Si el perfil exacto no tiene la guía, probar los demás perfiles con el mismo DNI.
                    # Ej.: 37424493APP y 37424493P pertenecen a la misma persona.
                    if pending:
                        sample = next(iter(pending.values()))
                        base_dni = _dist_base_dni(sample.get("distribuidor_codigo") or sample.get("distribuidor_dni"))
                        siblings = await _combo_distributor_candidates(context, base, route_referer, base_dni, timeout_ms) if base_dni else []
                        siblings = [c for c in siblings if c.get("id") != str(distributor_id) and _dist_base_dni(c.get("code")) == base_dni]
                        if siblings:
                            logger.info(
                                "[CAMBIO ESTADO V2] distribuidor %s sin coincidencia; probando %s perfil(es) alternativo(s) del DNI %s.",
                                distributor_id, len(siblings), base_dni,
                            )
                        for cand in siblings:
                            if not pending:
                                break
                            try:
                                alt_data = await _post_form(
                                    context, route_url, _route_payload(csrf, cand["id"], date_text),
                                    route_referer, timeout_ms, f"buscar recorridos perfil alternativo {cand['id']}",
                                )
                                alt_routes = _find_rows(alt_data)
                                alt_routes.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
                                logger.info(
                                    "[CAMBIO ESTADO V2] perfil alternativo %s (%s): %s planilla(s).",
                                    cand.get("id"), cand.get("code"), len(alt_routes),
                                )
                                for route in alt_routes:
                                    if not pending:
                                        break
                                    try:
                                        planilla_id = int(route.get("id"))
                                    except Exception:
                                        continue
                                    rows = await _load_planilla_rows(context, base, csrf, rendition_url, planilla_id, timeout_ms)
                                    present = {int(r["retiro_id"]) for r in rows if _s(r.get("retiro_id")).isdigit()}
                                    matched = [rid for rid in list(pending) if rid in present]
                                    for rid in matched:
                                        item = pending.pop(rid)
                                        item["planilla_id"] = planilla_id
                                        item["distribuidor_id_usado"] = cand.get("id")
                                        item["distribuidor_codigo_usado"] = cand.get("code")
                                        item["route_resolution"] = "alternate_profile_same_dni"
                                        by_planilla[planilla_id].append(item)
                                        logger.info(
                                            "[CAMBIO ESTADO V2] guía %s encontrada en perfil alternativo %s (%s), planilla %s.",
                                            rid, cand.get("id"), cand.get("code"), planilla_id,
                                        )
                            except Exception as alt_exc:
                                logger.warning(
                                    "[CAMBIO ESTADO V2] perfil alternativo %s: %s", cand.get("id"), alt_exc
                                )

                    # Si ningún perfil del DNI la contiene, recién ahí usar el fallback de Rendición.
                    for rid, item in list(pending.items()):
                        item["route_resolution"] = "fallback_rendicion_after_all_profiles"
                        route_probe_items.append(item)
                        logger.warning(
                            "[CAMBIO ESTADO V2] guía %s no apareció en ningún perfil del DNI; usaré fallback de Rendición.", rid
                        )
                except Exception as exc:
                    for item in pending.values():
                        item["change_status"] = "error"
                        item["change_message"] = f"No pude consultar las planillas: {exc}"
                    logger.warning("[CAMBIO ESTADO V2] distribuidor %s: %s", distributor_id, exc)

            if not by_planilla and not route_probe_items:
                return results

            # 4. Entrar en Rendición y habilitar un Nro. de Rendición para este lote.
            response = await page.goto(rendition_url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir Generar rendición de chofer.")
            csrf = await extract_csrf_token(page)
            nro_rendicion = await _enable_rendition(context, base, csrf, rendition_url, timeout_ms, page=page)
            logger.info("[CAMBIO ESTADO V2] Rendición activa: %s", nro_rendicion)

            confirm_url = base + "/rendicion/confirmarRecepcionados"
            now = business_now()
            fecha = date_text
            hora = now.strftime("%H:%M")

            # 4b. Fallback sin distribuidor: usar una planilla real del día como sonda.
            # Si no es la correcta, confirmarRecepcionados devuelve HTTP 500 con:
            #   "La guía: X está en el recorrido: 98149 ..."
            # y usamos ese recorrido exacto. Si casualmente la sonda es la planilla
            # correcta, Epresis confirma el cambio y lo registramos como OK.
            if route_probe_items:
                try:
                    seed_data = await _post_form(
                        context,
                        route_url,
                        _route_payload(csrf, "", date_text),
                        route_referer,
                        timeout_ms,
                        "buscar planilla sonda del día",
                    )
                    seed_routes = _find_rows(seed_data)
                    seed_routes.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
                    seed_planilla = next((int(r.get("id")) for r in seed_routes if _s(r.get("id")).isdigit()), None)
                    if not seed_planilla:
                        raise RuntimeError(f"No encontré ninguna planilla del {date_text} para usar como sonda.")

                    logger.info("[CAMBIO ESTADO V2] Fallback Rendición: planilla sonda %s.", seed_planilla)
                    for item in route_probe_items:
                        rid = int(item["retiro_id"])
                        payload = _confirm_payload(
                            csrf, seed_planilla, [rid], int(state_id), nro_rendicion, fecha, hora
                        )
                        status, data, raw_text = await _post_form_raw(
                            context, confirm_url, payload, rendition_url, timeout_ms
                        )
                        ok = status < 400 and isinstance(data, dict) and _s(data.get("status")).lower() == "ok"
                        if ok:
                            item["planilla_id"] = seed_planilla
                            item["nro_rendicion"] = nro_rendicion
                            item["route_resolution"] = "fallback_probe_confirmed"
                            item["change_status"] = "ok"
                            item["change_message"] = _s(data.get("message")) or "Recepcionado Correctamente."
                            logger.info(
                                "[CAMBIO ESTADO V2] guía %s: la planilla sonda %s era la correcta; cambio confirmado.",
                                rid, seed_planilla,
                            )
                            continue

                        actual_planilla = _route_from_rendition_error(data, raw_text)
                        if actual_planilla:
                            item["planilla_id"] = actual_planilla
                            item["route_resolution"] = "fallback_error_message"
                            by_planilla[actual_planilla].append(item)
                            logger.info(
                                "[CAMBIO ESTADO V2] guía %s → recorrido %s detectado por mensaje de Rendición.",
                                rid, actual_planilla,
                            )
                        else:
                            message = _s(data.get("message")) if isinstance(data, dict) else raw_text
                            item["change_status"] = "error"
                            item["change_message"] = (
                                f"No pude detectar la planilla desde Rendición (HTTP {status}): "
                                f"{message or 'respuesta sin detalle'}"
                            )
                            logger.warning("[CAMBIO ESTADO V2] guía %s: %s", rid, item["change_message"])
                except Exception as exc:
                    for item in route_probe_items:
                        if not item.get("change_status") and not item.get("planilla_id"):
                            item["change_status"] = "error"
                            item["change_message"] = f"Fallback de Rendición falló: {exc}"
                    logger.warning("[CAMBIO ESTADO V2] Fallback Rendición: %s", exc)

            # 5. Confirmar una request masiva por planilla.
            for planilla_id, items in by_planilla.items():
                valid_items = [x for x in items if not x.get("change_status")]
                if not valid_items:
                    continue
                retiro_ids = [int(x["retiro_id"]) for x in valid_items]
                logger.info(
                    "[CAMBIO ESTADO V2] Planilla %s: confirmando %s pedido(s) → %s",
                    planilla_id, len(retiro_ids), STATE_BY_ID[int(state_id)],
                )
                payload = _confirm_payload(
                    csrf, planilla_id, retiro_ids, int(state_id), nro_rendicion, fecha, hora
                )
                try:
                    data = await _post_form(
                        context, confirm_url, payload, rendition_url, timeout_ms,
                        f"confirmar planilla {planilla_id}",
                    )
                    ok = isinstance(data, dict) and _s(data.get("status")).lower() == "ok"
                    message = _s(data.get("message")) if isinstance(data, dict) else ""
                    if not ok:
                        raise RuntimeError(message or f"Respuesta inesperada: {data}")

                    # Verificación posterior: el retiro debe figurar rendido SI.
                    verify_rows = await _load_planilla_rows(context, base, csrf, rendition_url, planilla_id, timeout_ms)
                    verify = {int(r["retiro_id"]): r for r in verify_rows if _s(r.get("retiro_id")).isdigit()}
                    for item in valid_items:
                        rid = int(item["retiro_id"])
                        row = verify.get(rid, {})
                        item["nro_rendicion"] = nro_rendicion
                        if _s(row.get("rendido")).upper() == "SI":
                            item["change_status"] = "ok"
                            item["change_message"] = message or "Recepcionado Correctamente."
                            item["verified_rendido"] = "SI"
                        else:
                            item["change_status"] = "warning"
                            item["change_message"] = (
                                (message or "Epresis respondió OK")
                                + " (no pude verificar todavía 'rendido=SI' en la recarga de la planilla)"
                            )
                            item["verified_rendido"] = _s(row.get("rendido"))
                    logger.info("[CAMBIO ESTADO V2] Planilla %s: %s", planilla_id, message or "OK")
                except Exception as exc:
                    for item in valid_items:
                        item["nro_rendicion"] = nro_rendicion
                        item["change_status"] = "error"
                        item["change_message"] = str(exc)
                    logger.warning("[CAMBIO ESTADO V2] Planilla %s: ERROR - %s", planilla_id, exc)

        finally:
            await context.close()

    # Auditoría local sin cookies/CSRF.
    try:
        log_dir = resolve_path(cfg, "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "cambio_estado_v2_rendicion_chofer",
            "state_id": int(state_id),
            "selected_date": selected.isoformat(),
            "state": STATE_BY_ID[int(state_id)],
            "results": results,
        }
        (log_dir / f"cambio_estado_v2_{stamp}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("[CAMBIO ESTADO V2] No pude escribir auditoría local: %s", exc)

    return results


__all__ = ["change_state_v2"]
