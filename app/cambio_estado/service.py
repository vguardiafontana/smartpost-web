from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path
from app.descarga.epresis_api import EpresisAPI, FILTER_FIELDS
from .states import STATE_BY_ID


@dataclass
class ResolvedGuide:
    input_value: str
    detected_type: str = ""
    retiro_id: int | None = None
    guia: str = ""
    remito: str = ""
    guia_agente: str = ""
    current_state_id: int | None = None
    current_state: str = ""
    seller: str = ""
    resolution_status: str = "resolved"  # resolved | duplicate | unresolved | error
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_identifiers(text: str) -> list[str]:
    """Extrae números pegados con texto, preservando orden y quitando repetidos exactos."""
    values = re.findall(r"(?<!\d)\d{5,20}(?!\d)", str(text or ""))
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _find_rows(obj: Any) -> list[dict]:
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return list(obj)
        for value in obj:
            rows = _find_rows(value)
            if rows:
                return rows
    elif isinstance(obj, dict):
        for key in ("rows", "data", "results", "items", "records", "guias"):
            value = obj.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # Some Epresis endpoints return a guide object directly.
        if "id" in obj and any(k in obj for k in ("remito", "estado", "datos_envios", "cliente")):
            return [obj]
        for value in obj.values():
            rows = _find_rows(value)
            if rows:
                return rows
    elif isinstance(obj, str):
        t = obj.strip()
        if t[:1] in "[{" and t[-1:] in "]}":
            try:
                return _find_rows(json.loads(t))
            except Exception:
                pass
    return []


def _get_nested(row: dict, *paths: tuple[str, ...]):
    for path in paths:
        cur: Any = row
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return cur
    return ""


def _guide_info(row: dict, input_value: str, detected_type: str) -> ResolvedGuide:
    retiro = row.get("id") or row.get("retiro_id")
    try:
        retiro_id = int(retiro)
    except Exception:
        retiro_id = None

    estado_obj = row.get("estado") if isinstance(row.get("estado"), dict) else {}
    current_state_id = estado_obj.get("id") or row.get("estado_id")
    try:
        current_state_id = int(current_state_id) if current_state_id not in (None, "") else None
    except Exception:
        current_state_id = None
    current_state = str(estado_obj.get("nombre") or row.get("estado_nombre") or "").strip()
    if not current_state and current_state_id in STATE_BY_ID:
        current_state = STATE_BY_ID[current_state_id]

    remito = str(row.get("remito") or _get_nested(row, ("dato_flex", "shipping_id")) or "").strip()
    guia_agente = str(
        _get_nested(row, ("datos_envios", "guiaAgente"), ("dato_flex", "orden_id"))
        or row.get("guiaAgente") or row.get("guia_agente") or ""
    ).strip()
    seller = str(
        _get_nested(row, ("cliente", "empresa"), ("dato_flex", "tienda"))
        or row.get("cliente") or row.get("empresa") or ""
    ).strip()
    if isinstance(row.get("cliente"), dict):
        seller = str(row["cliente"].get("empresa") or row["cliente"].get("nombre_fantasia") or seller).strip()

    return ResolvedGuide(
        input_value=input_value,
        detected_type=detected_type,
        retiro_id=retiro_id,
        guia=str(retiro_id or ""),
        remito=remito,
        guia_agente=guia_agente,
        current_state_id=current_state_id,
        current_state=current_state,
        seller=seller,
    )


async def _post_form(context, url: str, form: dict[str, str], referer: str, timeout_ms: int, context_name: str):
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
        raise RuntimeError(f"Sesión/CSRF inválido en {context_name} (HTTP {response.status}).")
    if not response.ok:
        text = (await response.text())[:500]
        raise RuntimeError(f"HTTP {response.status} en {context_name}: {text}")
    try:
        return await response.json()
    except Exception as exc:
        text = (await response.text())[:500]
        raise RuntimeError(f"Respuesta no JSON en {context_name}: {text}") from exc


async def _filter_guide(api: EpresisAPI, guide: str):
    payload = {name: "" for name in FILTER_FIELDS}
    payload["_token"] = api.csrf
    payload["nroGuia_desde"] = str(guide)
    payload["nroGuia_hasta"] = str(guide)
    payload.update({"sort": "id", "order": "desc", "limit": "10", "offset": "0"})
    async with api.sem:
        response = await api.request.post(
            api._url(api.settings["filter_path"]),
            form=payload,
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": api.referer},
            timeout=api.settings["request_timeout_ms"],
        )
    data = await api._json_response(response, f"validar guía {guide}")
    rows = _find_rows(data)
    for row in rows:
        rid = str(row.get("id") or row.get("retiro_id") or "").strip()
        if rid == str(guide).strip():
            return row
    return rows[0] if len(rows) == 1 else None


async def _resolve_one(context, api: EpresisAPI, csrf: str, settings: dict, arrival_url: str, value: str, logger) -> ResolvedGuide:
    # 1) Guía normal. En la pantalla de Arribo el input se llama retiro_id; validamos
    # el número con /guias/filter para que ANALIZAR nunca haga un cambio destructivo.
    try:
        row = await _filter_guide(api, value)
        if row is not None:
            return _guide_info(row, value, "Guía")
    except Exception as exc:
        logger.info("[CAMBIO ESTADO] %s no resolvió como guía: %s", value, exc)

    base = settings["base_url"].rstrip("/")
    timeout = int(settings.get("request_timeout_ms", 30000))

    # 2) Remito: endpoint observado en Arribo de Paquetes.
    try:
        data = await _post_form(
            context,
            base + str(settings.get("remito_search_path") or "/tracker/searchByRemitoCliente"),
            {"id": value, "_token": csrf}, arrival_url, timeout,
            f"buscar remito {value}",
        )
        rows = _find_rows(data)
        exact = [r for r in rows if str(r.get("remito") or _get_nested(r, ("dato_flex", "shipping_id")) or "").strip() == value]
        row = exact[0] if exact else (rows[0] if len(rows) == 1 else None)
        if row is not None:
            info = _guide_info(row, value, "Remito")
            if info.retiro_id:
                enriched = await _filter_guide(api, str(info.retiro_id))
                return _guide_info(enriched or row, value, "Remito")
    except Exception as exc:
        logger.info("[CAMBIO ESTADO] %s no resolvió como remito: %s", value, exc)

    # 3) Guía Agente: devuelve al menos id y guiaAgente. Enriquecemos por guía.
    try:
        data = await _post_form(
            context,
            base + str(settings.get("guia_agente_search_path") or "/tracker/searchByGuiaAgente"),
            {"id": value, "_token": csrf}, arrival_url, timeout,
            f"buscar guía agente {value}",
        )
        rows = _find_rows(data)
        exact = [r for r in rows if str(r.get("guiaAgente") or r.get("guia_agente") or "").strip() == value]
        row = exact[0] if exact else (rows[0] if len(rows) == 1 else None)
        if row is not None:
            retiro_id = row.get("id") or row.get("retiro_id")
            if retiro_id:
                enriched = await _filter_guide(api, str(retiro_id))
                if enriched is not None:
                    return _guide_info(enriched, value, "Guía Agente")
                info = _guide_info(row, value, "Guía Agente")
                info.guia_agente = info.guia_agente or value
                return info
    except Exception as exc:
        logger.info("[CAMBIO ESTADO] %s no resolvió como Guía Agente: %s", value, exc)

    return ResolvedGuide(
        input_value=value,
        resolution_status="unresolved",
        message="No se encontró como guía, remito ni Guía Agente.",
    )


async def analyze_identifiers(cfg: dict, identifiers: list[str], logger) -> list[dict[str, Any]]:
    """Resuelve identificadores sin modificar ningún estado en Epresis."""
    from app.descarga.auth import ensure_authenticated, extract_csrf_token
    settings = epresis_settings(cfg)
    ce = cfg.get("cambio_estado") or {}
    settings["remito_search_path"] = str(ce.get("remito_search_path") or "/tracker/searchByRemitoCliente")
    settings["guia_agente_search_path"] = str(ce.get("guia_agente_search_path") or "/tracker/searchByGuiaAgente")
    arrival_path = str(ce.get("arrival_path") or "/guias/arribo_paquetes")
    arrival_url = settings["base_url"].rstrip("/") + arrival_path

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
            response = await page.goto(arrival_url, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir Arribo de Paquetes.")
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger, referer=arrival_url)

            out: list[ResolvedGuide] = []
            seen_retiros: dict[int, str] = {}
            for idx, value in enumerate(identifiers, start=1):
                logger.info("[CAMBIO ESTADO] Analizando %s/%s: %s", idx, len(identifiers), value)
                try:
                    item = await _resolve_one(context, api, csrf, settings, arrival_url, value, logger)
                except Exception as exc:
                    item = ResolvedGuide(input_value=value, resolution_status="error", message=str(exc))
                if item.retiro_id is not None and item.resolution_status == "resolved":
                    if item.retiro_id in seen_retiros:
                        item.resolution_status = "duplicate"
                        item.message = f"Misma guía que {seen_retiros[item.retiro_id]}; no se procesará dos veces."
                    else:
                        seen_retiros[item.retiro_id] = item.input_value
                out.append(item)
            return [x.to_dict() for x in out]
        finally:
            await context.close()


async def apply_state_change(cfg: dict, analyzed_rows: list[dict[str, Any]], state_id: int, logger) -> list[dict[str, Any]]:
    """Aplica secuencialmente un estado a las filas previamente analizadas.

    Solo procesa filas resolution_status=resolved. Un response result=ERROR se registra
    y el lote continúa, tal como funciona el uso operativo de Arribo de Paquetes.
    """
    from app.descarga.auth import ensure_authenticated, extract_csrf_token
    if int(state_id) not in STATE_BY_ID:
        raise RuntimeError(f"Estado no permitido/desconocido: {state_id}")

    settings = epresis_settings(cfg)
    ce = cfg.get("cambio_estado") or {}
    arrival_path = str(ce.get("arrival_path") or "/guias/arribo_paquetes")
    change_path = str(ce.get("change_path") or "/guias/arribo_paquetes-cambio-estado")
    arrival_url = settings["base_url"].rstrip("/") + arrival_path
    change_url = settings["base_url"].rstrip("/") + change_path

    candidates = [r for r in analyzed_rows if r.get("resolution_status") == "resolved" and r.get("retiro_id")]
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
            response = await page.goto(arrival_url, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir Arribo de Paquetes.")
            csrf = await extract_csrf_token(page)

            for index, row in enumerate(candidates, start=1):
                retiro_id = int(row["retiro_id"])
                result = dict(row)
                logger.info("[CAMBIO ESTADO] %s/%s guía %s → estado %s", index, len(candidates), retiro_id, state_id)
                try:
                    data = await _post_form(
                        context,
                        change_url,
                        {"_token": csrf, "retiro_id": str(retiro_id), "estado_id": str(int(state_id))},
                        arrival_url,
                        int(settings.get("request_timeout_ms", 30000)),
                        f"cambiar estado de guía {retiro_id}",
                    )
                    result_code = str(data.get("result") if isinstance(data, dict) else "").upper()
                    if result_code == "OK":
                        result["change_status"] = "ok"
                        result["change_message"] = "Cambio realizado"
                        logger.info("[CAMBIO ESTADO] guía %s: OK", retiro_id)
                    else:
                        message = str((data or {}).get("message") or "Epresis respondió ERROR").strip() if isinstance(data, dict) else "Epresis respondió ERROR"
                        result["change_status"] = "error"
                        result["change_message"] = message
                        logger.warning("[CAMBIO ESTADO] guía %s: ERROR - %s", retiro_id, message)
                except Exception as exc:
                    result["change_status"] = "error"
                    result["change_message"] = str(exc)
                    logger.warning("[CAMBIO ESTADO] guía %s: excepción - %s", retiro_id, exc)
                results.append(result)
        finally:
            await context.close()

    # Auditoría local: no contiene cookies ni CSRF.
    try:
        log_dir = resolve_path(cfg, "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "state_id": int(state_id),
            "state": STATE_BY_ID[int(state_id)],
            "results": results,
        }
        (log_dir / f"cambio_estado_{stamp}.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[CAMBIO ESTADO] No pude escribir auditoría local: %s", exc)

    return results
