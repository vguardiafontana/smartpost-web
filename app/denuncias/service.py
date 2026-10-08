from __future__ import annotations

import asyncio
import csv
import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path, seller_map
from app.core.runtime_paths import ensure_data_dirs
from app.descarga.auth import ensure_authenticated, extract_csrf_token, navigate_to_guide_search
from app.descarga.epresis_api import FILTER_FIELDS, EpresisAPI
from app.denuncias.models import Shipment, Driver
from app.denuncias.input_parser import query_field_order


def _norm(value: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def _pick(mapping: dict[str, str], *names: str) -> str:
    nm = {_norm(k): str(v or "").strip() for k, v in mapping.items()}
    for name in names:
        target = _norm(name)
        if target in nm and nm[target]:
            return nm[target]
    for name in names:
        target = _norm(name)
        for k, v in nm.items():
            if target and target in k and v:
                return v
    return ""


def _unwrap_excel(value: str) -> str:
    s = str(value or "").strip()
    m = re.fullmatch(r'=\"(.*)\"', s, flags=re.S)
    return m.group(1) if m else s


def _driver_from_distributor_text(value: str) -> Driver:
    text = str(value or "").strip()
    # Common Epresis form: 37119820P - MAIZ PR PM, ANGEL
    m = re.match(r"\s*(\d{6,10})[A-Z]?\s*-\s*(.+?)\s*,\s*(.+?)\s*$", text, flags=re.I)
    if m:
        return Driver(dni=m.group(1), surname=m.group(2).strip(), name=m.group(3).strip())
    return Driver()


def _find_rows(obj):
    if isinstance(obj, dict):
        for key in ("rows", "data", "results", "items", "records", "guias"):
            value = obj.get(key)
            if isinstance(value, list) and value:
                return value
        for value in obj.values():
            found = _find_rows(value)
            if found:
                return found
    elif isinstance(obj, list) and obj:
        if all(isinstance(x, dict) for x in obj):
            return obj
        for value in obj:
            found = _find_rows(value)
            if found:
                return found
    elif isinstance(obj, str):
        t = obj.strip()
        if t[:1] in "[{" and t[-1:] in "]}":
            try:
                return _find_rows(json.loads(t))
            except Exception:
                return None
    return None


async def _scrape_labeled_values(page) -> dict[str, str]:
    """Best-effort extraction of labels and adjacent form controls from show/{guia}."""
    data = await page.evaluate(
        """() => {
          const out = {};
          const textOf = el => (el && (el.value ?? el.innerText ?? el.textContent) || '').toString().trim();
          document.querySelectorAll('label').forEach(label => {
            const key = (label.innerText || label.textContent || '').replace(/\s*\*\s*$/, '').trim();
            if (!key) return;
            let ctl = null;
            if (label.htmlFor) ctl = document.getElementById(label.htmlFor);
            if (!ctl) {
              let root = label.parentElement;
              for (let i=0; root && i<4 && !ctl; i++, root=root.parentElement) {
                ctl = root.querySelector('input,select,textarea');
              }
            }
            const val = textOf(ctl);
            if (val) out[key] = val;
          });
          document.querySelectorAll('input,select,textarea').forEach(el => {
            const key = (el.getAttribute('name') || el.getAttribute('id') || el.getAttribute('placeholder') || '').trim();
            const val = textOf(el);
            if (key && val && !out[key]) out[key] = val;
          });
          return out;
        }"""
    )
    return {str(k): str(v) for k, v in (data or {}).items()}


async def _filter_by_field(api: EpresisAPI, query: str, field: str):
    payload = {name: "" for name in FILTER_FIELDS}
    payload["_token"] = api.csrf
    q = str(query).strip()
    if field == "nroGuia":
        payload["nroGuia_desde"] = q
        payload["nroGuia_hasta"] = q
    elif field == "rto_cliente":
        payload["rto_cliente"] = q
    elif field == "guia_agente":
        payload["guia_agente"] = q
    else:
        raise ValueError(f"Campo de búsqueda desconocido: {field}")
    payload.update({"sort": "id", "order": "desc", "limit": "10", "offset": "0"})
    async with api.sem:
        response = await api.request.post(
            api._url(api.settings["filter_path"]),
            form=payload,
            headers={"Accept":"application/json","X-Requested-With":"XMLHttpRequest","Referer":api.referer},
            timeout=api.settings["request_timeout_ms"],
        )
    return await api._json_response(response, f"buscar {field} para denuncia")


async def _resolve_query(api: EpresisAPI, query: str, seller_hint: str = "") -> Shipment | None:
    """Try guide, remito and Guia Agente until Epresis confirms the shipment."""
    for field in query_field_order(query):
        data = await _filter_by_field(api, query, field)
        rows = _find_rows(data) or []
        candidates = [_shipment_from_row(query, row, seller_hint) for row in rows if isinstance(row, dict)]
        if not candidates:
            continue

        # Prefer an exact match in the field that was actually searched.
        for item in candidates:
            exact = {
                "nroGuia": item.guia,
                "rto_cliente": item.remito,
                "guia_agente": item.sale_number,
            }.get(field, "")
            if str(exact).strip() == str(query).strip():
                return item
        if len(candidates) == 1:
            return candidates[0]
    return None


def _shipment_from_row(query: str, row: dict, seller_hint: str = "") -> Shipment:
    flat = {str(k): v for k, v in row.items()}
    return Shipment(
        query=query,
        guia=str(_pick(flat, "Nro Guia", "nro_guia", "guia", "id")),
        seller=seller_hint or _pick(flat, "Cliente", "Empresa", "Nombre Fantasia"),
        remito=_unwrap_excel(_pick(flat, "Remito", "rto_cliente", "Rto Cliente")),
        sale_number=_unwrap_excel(_pick(flat, "Guia Agente", "guia_agente")),
        distributor=_pick(flat, "Distribuidor Recorrido", "Distribuidor", "distribuidor_nombre"),
        address=_pick(flat, "Domicilio", "Calle", "direccion"),
        locality=_pick(flat, "Localidad", "Localidad Destino"),
        province=_pick(flat, "Provincia"),
        postal_code=_pick(flat, "CP", "Codigo postal"),
    )


async def _search_distributor_same_endpoint(context, settings: dict, csrf: str, surname: str, logger):
    path = str(settings.get("distributor_search_path") or "/distribuidores/lista-distribuidores")
    payload = {
        "limit": "10", "offset": "0", "_token": csrf, "estado": "1",
        "filter": json.dumps({"apellido": surname}, ensure_ascii=False),
    }
    response = await context.request.post(
        settings["base_url"].rstrip("/") + path,
        form=payload,
        headers={"Accept":"application/json","X-Requested-With":"XMLHttpRequest","Referer":settings["base_url"].rstrip("/") + path},
        timeout=settings["request_timeout_ms"],
    )
    if not response.ok:
        raise RuntimeError(f"Distribuidores devolvió HTTP {response.status}")
    try:
        data = await response.json()
    except Exception as exc:
        raise RuntimeError("La búsqueda de Distribuidores no devolvió JSON") from exc
    rows = (data or {}).get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    return rows


async def resolve_shipments_and_driver(cfg: dict, entries: list[dict], logger) -> tuple[list[Shipment], Driver]:
    """Resolve shipment and driver data using the existing authenticated Epresis profile.

    Entries: [{"query": "5983983", "seller": "DABRA"}, ...]. Seller is kept as
    the user's explicit hint and is never silently replaced by a guessed mapping.
    """
    settings = epresis_settings(cfg)
    settings["distributor_search_path"] = (cfg.get("denuncias") or {}).get(
        "distributor_search_path", "/distribuidores/lista-distribuidores"
    )
    shipments: list[Shipment] = []
    detected_driver = Driver()

    async with async_playwright() as p:
        profile = resolve_path(cfg, "epresis_profile")
        profile.mkdir(parents=True, exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=bool(settings.get("headless", True)), accept_downloads=False
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_authenticated(page, settings, logger)
            guide_search_url = await navigate_to_guide_search(page, settings, logger)
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger, referer=guide_search_url)

            for entry in entries:
                query = str(entry.get("query", "")).strip()
                seller_hint = str(entry.get("seller", "")).strip()
                if not query:
                    continue
                shipment = Shipment(query=query, seller=seller_hint)
                try:
                    resolved = await _resolve_query(api, query, seller_hint)
                    if resolved is not None:
                        shipment = resolved
                        logger.info(
                            "[DENUNCIAS] %s resuelto: guía=%s remito=%s guía_agente=%s seller=%s",
                            query, shipment.guia, shipment.remito, shipment.sale_number, shipment.seller,
                        )
                    else:
                        logger.warning("[DENUNCIAS] No encontré %s como guía, remito ni Guía Agente", query)
                except Exception as exc:
                    logger.warning("[DENUNCIAS] /guias/filter no resolvió %s: %s", query, exc)

                guide_no = shipment.guia or (query if re.fullmatch(r"\d{5,9}", query) else "")
                if guide_no:
                    try:
                        show_url = settings["base_url"].rstrip("/") + f"/guias/editar-guia-v2/show/{guide_no}"
                        await page.goto(show_url, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
                        labeled = await _scrape_labeled_values(page)
                        shipment.guia = shipment.guia or guide_no
                        shipment.distributor = shipment.distributor or _pick(labeled, "Distribuidor")
                        shipment.remito = shipment.remito or _unwrap_excel(_pick(labeled, "Rto. Cliente", "Remito"))
                        shipment.sale_number = shipment.sale_number or _unwrap_excel(_pick(labeled, "Guía Agente", "Guia Agente"))
                        shipment.address = shipment.address or " ".join(x for x in [
                            _pick(labeled, "Calle"), _pick(labeled, "Altura")
                        ] if x).strip()
                        shipment.locality = shipment.locality or _pick(labeled, "Localidad", "Localidad/Barrio")
                        shipment.province = shipment.province or _pick(labeled, "Provincia")
                        shipment.postal_code = shipment.postal_code or _pick(labeled, "CP", "Código postal", "Codigo postal")
                        shipment.seller = shipment.seller or _pick(labeled, "Cliente", "Empresa")
                    except Exception as exc:
                        logger.warning("[DENUNCIAS] show/%s no pudo leerse: %s", guide_no, exc)

                if not detected_driver.dni and shipment.distributor:
                    detected_driver = _driver_from_distributor_text(shipment.distributor)
                shipments.append(shipment)

            # If the operator pasted two or three identifiers belonging to the
            # same shipment (guide + remito + Guia Agente), keep it only once.
            deduped: list[Shipment] = []
            seen_keys: set[str] = set()
            for item in shipments:
                key = item.guia or item.remito or item.sale_number or item.query
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                deduped.append(item)
            shipments = deduped

            # Best-effort distributor enrichment from the observed endpoint.
            if detected_driver.surname:
                try:
                    rows = await _search_distributor_same_endpoint(
                        context, settings, csrf, detected_driver.surname.split()[0], logger
                    )
                    if rows:
                        exact = [r for r in rows if str(r.get("dni", "")) == detected_driver.dni]
                        row = exact[0] if exact else rows[0]
                        detected_driver.name = str(row.get("nombre") or detected_driver.name).strip()
                        detected_driver.surname = str(row.get("apellido") or detected_driver.surname).strip()
                        detected_driver.dni = str(row.get("dni") or detected_driver.dni).strip()
                        phone = str(row.get("telefono") or row.get("celular") or "").strip()
                        if phone:
                            # Argentina-friendly split; user may edit it before submission.
                            digits = re.sub(r"\D", "", phone)
                            detected_driver.phone_prefix = digits[:3] if len(digits) > 7 else ""
                            detected_driver.phone_number = digits[3:] if detected_driver.phone_prefix else digits
                        detected_driver.email = str(row.get("email") or "").strip()
                        raw_birth = str(row.get("fecha_nacimiento") or "").strip()
                        if raw_birth:
                            try:
                                detected_driver.birth_date = datetime.fromisoformat(raw_birth[:10]).strftime("%d/%m/%Y")
                            except Exception:
                                detected_driver.birth_date = raw_birth
                except Exception as exc:
                    logger.warning("[DENUNCIAS] No pude enriquecer Distribuidor; se podrá completar manualmente: %s", exc)
        finally:
            await context.close()

    return shipments, detected_driver


def save_driver_profile(cfg: dict, driver: Driver) -> None:
    """Persist non-secret operator-entered driver fields in config for reuse."""
    from app.core.config import load_config, save_config
    if not driver.dni:
        return
    current = load_config()
    dcfg = current.setdefault("denuncias", {})
    profiles = dcfg.setdefault("driver_profiles", {})
    profiles[str(driver.dni)] = asdict(driver)
    save_config(current)


def apply_saved_driver_profile(cfg: dict, driver: Driver) -> Driver:
    if not driver.dni:
        return driver
    saved = ((cfg.get("denuncias") or {}).get("driver_profiles") or {}).get(str(driver.dni)) or {}
    for key in ("name","surname","birth_date","gender","phone_prefix","phone_number","email"):
        if not getattr(driver, key) and saved.get(key):
            setattr(driver, key, str(saved[key]))
    return driver
