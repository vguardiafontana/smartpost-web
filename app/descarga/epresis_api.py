from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urljoin

from app.core.utils import normalize_text, safe_filename

FILTER_FIELDS = [
    "cliente_id", "sucursal_id", "tipo_operacion_id", "ceco_id", "is_urgente",
    "nro_prestador", "nroGuia_desde", "nroGuia_hasta", "rto_cliente", "guia_agente",
    "nroPlanilla_desde", "nroPlanilla_hasta", "fecha_remito", "fecha_ultima_planilla",
    "nro_constancia", "fecha_ultimo_estado", "fecha_facturacion", "fecha_pactada",
    "fecha_hora_entrega", "distribuidor_id", "sector", "deposito_id",
    "con_contrareembolso", "fecha_repactacion", "fecha_confirmacion", "trabajo", "lote",
    "servicio_id", "is_facturada", "cordonOrigen", "cordonDestino", "zonaOrigen",
    "zonaDestino", "subZonaOrigen", "subZonaDestino", "prestador_id",
    "fecha_ingreso_planta", "rendida", "planilla_rendicion", "fecha_rendicion",
    "empresa_comprador", "nombre_comprador", "calle", "cuit", "dni", "nroSocio",
    "provincia", "localidad", "cp_comprador", "celular", "contrareembolso",
    "nro_precinto", "sucursal_empresa_origen_id", "sucursal_empresa_destino_id",
    "username", "last_user", "codigo_bolsin", "numero_bolsin", "fecha_vencimiento",
    "fecha_servicio", "nro_factura_desde", "nro_factura_hasta", "canal", "nro_pedido",
    "impreso", "id_consulta"
]


@dataclass
class SellerResult:
    seller: str
    cliente_id: int | None = None
    empresa: str | None = None
    status: str = "pending"  # downloaded | no_data | error
    job_id: int | None = None
    remote_file: str | None = None
    local_file: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    error: str | None = None


class SessionExpired(RuntimeError):
    pass


class NoDataDetected(RuntimeError):
    """La búsqueda para ese seller/fecha no contiene guías."""
    pass


class EpresisAPI:
    def __init__(self, request, settings: dict, csrf_token: str, logger, referer: str | None = None):
        self.request = request
        self.settings = settings
        self.csrf = csrf_token
        self.logger = logger
        self.base = settings["base_url"].rstrip("/") + "/"
        self.referer = referer or settings.get("guias_url") or settings["base_url"]
        self.sem = asyncio.Semaphore(int(settings.get("max_concurrent_requests", 4)))
        # /guias/exportarExcel tiene un rate limit propio. Todas las llamadas a ese
        # endpoint (programación y polling) pasan por una única compuerta global.
        self._export_lock = asyncio.Lock()
        self._last_export_call_at = 0.0

    def _url(self, path: str) -> str:
        return urljoin(self.base, path.lstrip("/"))

    async def _json_response(self, response, context: str):
        if response.status in (401, 403, 419):
            raise SessionExpired(f"Sesión/CSRF inválido en {context} (HTTP {response.status}).")
        if response.status == 429:
            raise RuntimeError(f"Rate limit de Epresis en {context} (HTTP 429).")
        if not response.ok:
            text = (await response.text())[:500]
            raise RuntimeError(f"HTTP {response.status} en {context}: {text}")
        try:
            return await response.json()
        except Exception:
            text = (await response.text())[:500]
            if "login" in text.lower() and "password" in text.lower():
                raise SessionExpired(f"Epresis devolvió login durante {context}.")
            raise RuntimeError(f"Respuesta no JSON en {context}: {text}")

    async def search_clients(self, term: str) -> list[dict]:
        async with self.sem:
            response = await self.request.get(
                self._url(self.settings["client_search_path"]),
                params={"search": term, "page": "1", "per_page": "15"},
                headers={"Accept": "application/json", "Referer": self.referer},
                timeout=self.settings["request_timeout_ms"],
            )
        data = await self._json_response(response, f"buscar cliente {term}")
        return list(data.get("data") or [])

    async def resolve_client(self, cfg: dict, cache: dict) -> tuple[int, str]:
        seller = cfg["seller"]
        # Config explícita tiene prioridad, luego cache.
        if cfg.get("cliente_id"):
            return int(cfg["cliente_id"]), cfg.get("expected_empresa") or seller
        cached = cache.get(seller)
        if cached and cached.get("cliente_id"):
            return int(cached["cliente_id"]), cached.get("empresa") or seller

        expected_exact = normalize_text(cfg.get("expected_empresa", ""))
        expected_contains = [normalize_text(x) for x in cfg.get("expected_empresa_contains", []) if x]
        all_candidates: dict[int, dict] = {}
        for term in cfg.get("search_terms") or [seller]:
            for item in await self.search_clients(term):
                if "id" in item:
                    all_candidates[int(item["id"])] = item
            if len(all_candidates) == 1:
                only = next(iter(all_candidates.values()))
                empresa = str(only.get("empresa", ""))
                n = normalize_text(empresa)
                if (expected_exact and n == expected_exact) or (
                    expected_contains and all(x in n for x in expected_contains)
                ):
                    return int(only["id"]), empresa

        candidates = list(all_candidates.values())
        # Exact match esperado.
        if expected_exact:
            exact = [c for c in candidates if normalize_text(c.get("empresa", "")) == expected_exact]
            if len(exact) == 1:
                return int(exact[0]["id"]), str(exact[0].get("empresa", ""))
        # Match por tokens esperados.
        if expected_contains:
            matches = [
                c for c in candidates
                if all(t in normalize_text(c.get("empresa", "")) for t in expected_contains)
            ]
            if len(matches) == 1:
                return int(matches[0]["id"]), str(matches[0].get("empresa", ""))
        # Un solo candidato total: aceptable.
        if len(candidates) == 1:
            return int(candidates[0]["id"]), str(candidates[0].get("empresa", ""))
        raise RuntimeError(
            f"No pude resolver cliente para {seller}. Candidatos: "
            + json.dumps(candidates, ensure_ascii=False)
        )

    @staticmethod
    def _date_range(date_text: str) -> str:
        if " - " in date_text:
            return date_text
        return f"{date_text} - {date_text}"

    def make_payload(self, cliente_id: int, date_text: str, export: bool) -> dict[str, str]:
        payload = {field: "" for field in FILTER_FIELDS}
        payload["_token"] = self.csrf
        payload["cliente_id"] = str(cliente_id)
        # ``date_text`` puede ser una fecha única (compatibilidad) o un rango
        # ya armado, por ejemplo APOLLO: 01/09/2026 - 17/09/2026.
        payload["fecha_ingreso_planta"] = self._date_range(date_text)
        if export:
            payload["type"] = "xls"
        else:
            payload.update({"sort": "id", "order": "desc", "limit": "10", "offset": "0"})
        return payload

    def make_visits_payload(self, date_text: str, state_ids: list[int], export: bool) -> list[tuple[str, str]]:
        """Build the exact form used by Epresis for the global VISITAS export.

        Unlike seller exports, VISITAS has no cliente_id and repeats the form
        key ``estados_id[]`` once per selected state. A list of pairs is used
        so URL encoding preserves those repeated keys exactly.
        """
        pairs: list[tuple[str, str]] = [("_token", self.csrf)]
        for field in FILTER_FIELDS:
            value = self._date_range(date_text) if field == "fecha_ingreso_planta" else ""
            pairs.append((field, value))
        for state_id in state_ids:
            pairs.append(("estados_id[]", str(int(state_id))))
        # Both the browser grid request and export request observed for this
        # workflow carry these two fields.
        pairs.append(("is_estado", "1"))
        pairs.append(("type", "xls"))
        if not export:
            pairs.extend([
                ("sort", "id"),
                ("order", "desc"),
                ("limit", "10"),
                ("offset", "0"),
            ])
        return pairs

    async def _post_pairs(self, path: str, pairs: list[tuple[str, str]], context: str):
        body = urlencode(pairs)
        async with self.sem:
            response = await self.request.post(
                self._url(path),
                data=body,
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Referer": self.referer,
                },
                timeout=self.settings["request_timeout_ms"],
            )
        return await self._json_response(response, context)

    async def filter(self, cliente_id: int, date_text: str):
        payload = self.make_payload(cliente_id, date_text, export=False)
        async with self.sem:
            response = await self.request.post(
                self._url(self.settings["filter_path"]),
                form=payload,
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.referer,
                },
                timeout=self.settings["request_timeout_ms"],
            )
        return await self._json_response(response, "filtrar guías")

    async def filter_visits(self, date_text: str, state_ids: list[int]):
        return await self._post_pairs(
            self.settings["filter_path"],
            self.make_visits_payload(date_text, state_ids, export=False),
            "filtrar visitas",
        )


    @staticmethod
    def filter_result_count(data) -> int | None:
        """Extrae la cantidad de resultados de /guias/filter de forma tolerante.

        Epresis puede envolver la grilla en estructuras distintas. Para decidir
        si un seller no tiene guías, buscamos totales/listas en CUALQUIER nivel
        del JSON, no solo en claves predefinidas como ``data``. También tolera
        JSON serializado dentro de strings y respuestas HTML de tabla.

        Devuelve:
          * 0 si hay evidencia inequívoca de que no hay filas;
          * >0 si hay evidencia de filas;
          * None si la forma de respuesta sigue siendo ambigua.
        """
        import re

        count_keys = {
            "total", "count", "recordstotal", "recordsfiltered",
            "totalrows", "totalrow", "cantidad", "cantidadtotal",
            "totalrecords", "rowcount", "recordcount",
            "totalregistros", "registros", "totalitems", "itemcount",
        }
        list_keys = {
            "rows", "items", "results", "records", "data",
            "guias", "resultados", "registros", "list", "lista",
        }
        html_keys = {"html", "table", "tabla", "tbody", "body", "content", "contenido"}
        no_data_phrases = (
            "no se encontraron", "sin resultados", "sin registros",
            "no hay registros", "no hay resultados", "ningun registro",
            "ninguna guia", "sin guias", "no data",
        )

        def keynorm(k):
            return re.sub(r"[^a-z0-9]", "", str(k).lower())

        def as_nonnegative_int(value):
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value if value >= 0 else None
            if isinstance(value, float) and value >= 0 and value.is_integer():
                return int(value)
            if isinstance(value, str):
                t = value.strip()
                if re.fullmatch(r"\d+", t):
                    return int(t)
            return None

        explicit_counts = []
        list_lengths = []
        html_evidence = []
        seen = set()

        def walk(obj, depth=0, parent_key=""):
            if depth > 8:
                return
            oid = id(obj)
            if isinstance(obj, (dict, list)):
                if oid in seen:
                    return
                seen.add(oid)

            if isinstance(obj, dict):
                for k, v in obj.items():
                    nk = keynorm(k)
                    if nk in count_keys:
                        n = as_nonnegative_int(v)
                        if n is not None:
                            explicit_counts.append(n)
                    if nk in list_keys and isinstance(v, list):
                        list_lengths.append(len(v))
                    if nk in html_keys and isinstance(v, str):
                        low = v.lower()
                        if any(x in low for x in no_data_phrases):
                            html_evidence.append(0)
                        elif "<tr" in low and ("<td" in low or "data-" in low):
                            # Una tabla con al menos una fila de datos.
                            html_evidence.append(1)
                    walk(v, depth + 1, nk)
                return

            if isinstance(obj, list):
                # Una lista raíz/no etiquetada también puede ser el resultado.
                if parent_key in list_keys or depth <= 2:
                    list_lengths.append(len(obj))
                for item in obj[:50]:
                    walk(item, depth + 1, parent_key)
                return

            if isinstance(obj, str):
                t = obj.strip()
                # A veces el backend envuelve JSON dentro de un string.
                if len(t) >= 2 and t[0] in "[{" and t[-1] in "]}":
                    try:
                        nested = json.loads(t)
                    except Exception:
                        nested = None
                    if nested is not None:
                        walk(nested, depth + 1, parent_key)
                if parent_key in html_keys:
                    low = t.lower()
                    if any(x in low for x in no_data_phrases):
                        html_evidence.append(0)

        walk(data)

        # Los totales explícitos son la evidencia más fuerte. Si existe cualquier
        # total >0, hay datos. Si todos los totales encontrados son 0, no hay.
        if explicit_counts:
            if max(explicit_counts) > 0:
                return max(explicit_counts)
            return 0

        # Luego usamos listas de resultados conocidas. Una lista no vacía prueba
        # que hay datos. Varias listas vacías sin otra evidencia apuntan a cero.
        if list_lengths:
            if max(list_lengths) > 0:
                return max(list_lengths)
            return 0

        if html_evidence:
            if max(html_evidence) > 0:
                return 1
            return 0

        return None

    @staticmethod
    def _retry_after_seconds(response) -> float | None:
        try:
            raw = (response.headers or {}).get("retry-after")
        except Exception:
            raw = None
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return None

    async def _export_payload_call(self, payload, context_name: str) -> dict:
        """Llama /guias/exportarExcel respetando el rate limit de Epresis.

        El sitio devuelve 429 cuando se disparan varios exports casi al mismo
        tiempo. En lugar de convertirlo inmediatamente en error, serializamos
        todas las llamadas a este endpoint, dejamos una separación mínima y
        reintentamos 429 con backoff. Esto aplica tanto al primer POST que
        programa el job como a los POST posteriores que consultan si ya quedó
        disponible (status=cached + url).
        """
        min_interval = max(2.7, float(self.settings.get("export_min_interval_seconds", 2.7)))
        max_retries = int(self.settings.get("rate_limit_max_retries", 8))
        base_delay = float(self.settings.get("rate_limit_base_delay_seconds", 2.0))
        max_delay = float(self.settings.get("rate_limit_max_delay_seconds", 20.0))

        async with self._export_lock:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_export_call_at
            if self._last_export_call_at and elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

            for attempt in range(max_retries + 1):
                headers = {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.referer,
                }
                if isinstance(payload, list):
                    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                    response = await self.request.post(
                        self._url(self.settings["export_path"]),
                        data=urlencode(payload),
                        headers=headers,
                        timeout=self.settings["request_timeout_ms"],
                    )
                else:
                    response = await self.request.post(
                        self._url(self.settings["export_path"]),
                        form=payload,
                        headers=headers,
                        timeout=self.settings["request_timeout_ms"],
                    )
                self._last_export_call_at = loop.time()

                if response.status != 429:
                    return await self._json_response(response, context_name)

                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Rate limit de Epresis en exportar Excel (HTTP 429) "
                        f"después de {max_retries + 1} intentos."
                    )

                retry_after = self._retry_after_seconds(response)
                exponential = min(max_delay, base_delay * (2 ** attempt))
                delay = max(min_interval, retry_after or 0.0, exponential)
                # Jitter pequeño para no volver exactamente en el mismo instante.
                delay += random.random() * 0.35
                self.logger.warning(
                    "Epresis respondió 429. Reintentando export en %.1fs (%d/%d)...",
                    delay, attempt + 1, max_retries
                )
                await asyncio.sleep(delay)

        raise RuntimeError("No se pudo completar exportar Excel.")

    async def export_call(self, cliente_id: int, date_text: str) -> dict:
        return await self._export_payload_call(
            self.make_payload(cliente_id, date_text, export=True),
            "exportar Excel",
        )

    async def export_visits_call(self, date_text: str, state_ids: list[int]) -> dict:
        return await self._export_payload_call(
            self.make_visits_payload(date_text, state_ids, export=True),
            "exportar visitas",
        )

    async def _wait_for_export_generic(self, initial: dict, export_fn, filter_fn, label: str) -> dict:
        if initial.get("url"):
            return initial
        timeout = float(self.settings.get("poll_timeout_seconds", 300))
        interval = max(4.0, float(self.settings.get("poll_interval_seconds", 4.0)))
        no_data_probe_after = float(self.settings.get("no_data_recheck_after_seconds", 12.0))
        no_data_probe_every = float(self.settings.get("no_data_recheck_every_seconds", 12.0))
        # Si un job nunca entrega URL y tampoco podemos interpretar el filtro, no
        # quedarse 5 minutos martillando exportarExcel. Se corta con error claro;
        # si el filtro confirma >0 filas, se permite esperar hasta poll_timeout.
        unknown_stall_timeout = float(self.settings.get("unknown_export_stall_seconds", 75.0))
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + timeout
        next_no_data_probe = started + no_data_probe_after
        last_known_count = None
        last = initial
        while loop.time() < deadline:
            await asyncio.sleep(interval + random.random() * 0.20)
            last = await export_fn()
            if last.get("url"):
                return last
            status = str(last.get("status", "")).lower()
            if status not in {"ok", "queued", "pending", "processing", "programmed", "cached", ""}:
                raise RuntimeError(f"Estado inesperado de exportación: {last}")

            # Algunas cuentas de Epresis aceptan el job aun cuando la búsqueda no
            # tiene filas; en ese caso el archivo nunca aparece y el botón parece
            # quedar 'pensando' para siempre. Reconsultamos /guias/filter fuera del
            # endpoint rate-limitado y, solo si confirma 0 filas, lo tratamos como
            # un día sin guías en vez de seguir consumiendo exportarExcel.
            now = loop.time()
            if now >= next_no_data_probe:
                try:
                    filtered = await filter_fn()
                    count = self.filter_result_count(filtered)
                    last_known_count = count
                    if count == 0:
                        raise NoDataDetected(f"La búsqueda de {label} devuelve 0 registros; Epresis no generará archivo.")
                    if count is None:
                        self.logger.debug("No pude extraer cantidad de /guias/filter. Respuesta: %s", repr(filtered)[:4000])
                except NoDataDetected:
                    raise
                except Exception as e:
                    # Una comprobación auxiliar no debe romper un export que sí
                    # podría terminar. Se registra en debug y se sigue esperando.
                    self.logger.debug("No pude revalidar si el export estaba vacío: %s", e)
                next_no_data_probe = now + no_data_probe_every

            # Guard de no-bloqueo: si después de bastante tiempo no existe URL y
            # el filtro tampoco pudo decirnos si hay filas, cortar esta tarea en
            # vez de seguir indefinidamente. Si el filtro confirmó que sí hay
            # filas (>0), dejamos que alcance el timeout normal.
            if (now - started) >= unknown_stall_timeout and last_known_count is None:
                raise RuntimeError(
                    f"Export sin archivo después de {unknown_stall_timeout:.0f}s y /guias/filter "
                    f"no permitió confirmar si hay guías. Última respuesta: {last}"
                )

        raise TimeoutError(f"La exportación no quedó disponible en {timeout:.0f}s. Última respuesta: {last}")

    async def wait_for_export(self, cliente_id: int, date_text: str, initial: dict) -> dict:
        async def do_export():
            return await self.export_call(cliente_id, date_text)

        async def do_filter():
            return await self.filter(cliente_id, date_text)

        return await self._wait_for_export_generic(initial, do_export, do_filter, "guías")

    async def wait_for_visits_export(self, date_text: str, state_ids: list[int], initial: dict) -> dict:
        async def do_export():
            return await self.export_visits_call(date_text, state_ids)

        async def do_filter():
            return await self.filter_visits(date_text, state_ids)

        return await self._wait_for_export_generic(initial, do_export, do_filter, "visitas")

    async def download(self, export_data: dict, destination: Path) -> Path:
        remote_url = export_data.get("url")
        if not remote_url:
            raise RuntimeError(f"Exportación sin URL: {export_data}")
        filename = export_data.get("file") or Path(str(remote_url)).name or "guias.csv"
        filename = safe_filename(filename)
        dest = destination / filename
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            i = 2
            while dest.exists():
                dest = destination / f"{stem}__{i}{suffix}"
                i += 1

        async with self.sem:
            response = await self.request.get(
                self._url(str(remote_url)),
                headers={"Referer": self.referer},
                timeout=self.settings["request_timeout_ms"],
            )
        if response.status in (401, 403, 419):
            raise SessionExpired(f"Sesión vencida al descargar {filename}.")
        if not response.ok:
            raise RuntimeError(f"Descarga HTTP {response.status}: {remote_url}")
        body = await response.body()
        if not body:
            raise RuntimeError(f"Archivo vacío descargado: {filename}")
        head = body[:400].lstrip().lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            raise RuntimeError(f"Epresis devolvió HTML en lugar del archivo: {filename}")
        destination.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return dest


def csv_has_data_rows(path: Path) -> bool:
    raw = path.read_bytes()
    # Los exports vistos son CSV aunque se pida type=xls. Detectar encoding razonablemente.
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return True  # No bloquear un formato binario futuro.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) > 1
