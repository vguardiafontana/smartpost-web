from __future__ import annotations

import json
import html
import re
import tempfile
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from app.core.config import epresis_settings, resolve_path
from app.descarga.epresis_api import EpresisAPI
from app.cambio_estado.service import (
    extract_identifiers,
    _filter_guide,
    _resolve_one,
    _get_nested,
)


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _first(*values: Any) -> str:
    for value in values:
        text = _s(value)
        if text:
            return text
    return ""


def _unwrap_excel(value: Any) -> str:
    s = _s(value)
    m = re.fullmatch(r'=\"(.*)\"', s, flags=re.S)
    return m.group(1) if m else s


def _norm(value: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()






def _excel_text(value: Any) -> str:
    """Texto estable para valores leídos vía Excel COM (evita 1130029545.0)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip()
    return str(value).strip()


def _distributor_from_excel_values(headers: list[Any], values: list[Any]) -> dict[str, str]:
    """Mapea una fila del Excel completo de Distribuidores por nombre de columna.

    El export real de Epresis usa `codigo` (ej. 45823637P) como identificador
    del distribuidor y expone `telefono` y `celular` como columnas separadas.
    """
    hmap = {_norm(_excel_text(h)).replace(" ", "_").lower(): i for i, h in enumerate(headers)}

    def val(*names: str) -> str:
        for name in names:
            key = _norm(name).replace(" ", "_").lower()
            idx = hmap.get(key)
            if idx is not None and idx < len(values):
                text = _excel_text(values[idx])
                if text:
                    return text
        return ""

    codigo = val("codigo", "dni", "documento")
    dni = re.sub(r"\D", "", codigo)
    telefono = val("telefono", "telefono_1", "tel")
    celular = val("celular", "movil", "mobile")
    nombre = val("nombre")
    apellido = val("apellido")
    return {
        "codigo": codigo,
        "dni": dni,
        "nombre": nombre,
        "apellido": apellido,
        "telefono": telefono,
        "celular": celular,
        "phone": telefono or celular,
        "name": " ".join(x for x in (nombre, apellido) if x).strip(),
    }


def _read_distributor_excel_index(path: Path, logger) -> dict[str, dict[str, str]]:
    """Lee el .xls exportado por Epresis usando Microsoft Excel (ya requerido por SmartPost)."""
    import pythoncom
    import win32com.client

    index: dict[str, dict[str, str]] = {}
    excel = None
    wb = None
    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        wb = excel.Workbooks.Open(str(path.resolve()), ReadOnly=True)
        ws = wb.Worksheets(1)
        used = ws.UsedRange.Value
        if not used:
            return index
        rows = list(used) if isinstance(used, tuple) else [used]
        if not rows:
            return index
        headers = list(rows[0]) if isinstance(rows[0], tuple) else [rows[0]]
        for raw in rows[1:]:
            values = list(raw) if isinstance(raw, tuple) else [raw]
            item = _distributor_from_excel_values(headers, values)
            dni = re.sub(r"\D", "", item.get("dni", ""))
            if dni:
                index[dni] = item
        logger.info("[BUSQUEDA] Excel de distribuidores cargado: %s registros.", len(index))
        return index
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


async def _download_distributor_excel_index(page, context, settings: dict, logger) -> dict[str, dict[str, str]]:
    """Descarga una sola vez el Excel completo de distribuidores y arma un índice por DNI.

    El endpoint ``/distribuidores/excelDistribuidores`` devuelve HTTP 405 ante un GET
    directo. En Epresis la exportación correcta se dispara desde el botón
    ``#expor-excel`` de la grilla, por lo que primero reproducimos ese click real con
    Playwright. Como respaldo probamos POST autenticado al mismo endpoint.
    """
    base = settings["base_url"].rstrip("/")
    list_url = base + "/distribuidores/lista-distribuidores"
    path = str(settings.get("distributor_excel_path") or "/distribuidores/excelDistribuidores")
    url = base + path
    tmp_path: Path | None = None

    async def read_body(body: bytes) -> dict[str, dict[str, str]]:
        nonlocal tmp_path
        if not body or not body.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            return {}
        fd, name = tempfile.mkstemp(prefix="smartpost_distribuidores_", suffix=".xls")
        import os
        os.close(fd)
        tmp_path = Path(name)
        tmp_path.write_bytes(body)
        return _read_distributor_excel_index(tmp_path, logger)

    try:
        # Camino principal: exactamente la acción que hace el operador en la web.
        await page.goto(list_url, wait_until="domcontentloaded", timeout=int(settings.get("request_timeout_ms", 30000)))
        button = page.locator("#expor-excel")
        if await button.count():
            try:
                async with page.expect_download(timeout=int(settings.get("request_timeout_ms", 30000))) as info:
                    await button.first.click(timeout=5000)
                download = await info.value
                body = await Path(await download.path()).read_bytes()
                index = await read_body(body)
                if index:
                    logger.info("[BUSQUEDA] Excel distribuidores descargado desde el botón EXPORTAR COMPLETO A EXCEL.")
                    return index
                logger.warning("[BUSQUEDA] El botón de exportación descargó un archivo, pero no era un XLS clásico válido.")
            except Exception as exc:
                logger.warning("[BUSQUEDA] No pude descargar Excel con #expor-excel: %s", exc)

        # Respaldo: la ruta rechaza GET (405) pero algunas instalaciones aceptan POST.
        try:
            response = await context.request.post(
                url,
                headers={"Referer": list_url},
                timeout=int(settings.get("request_timeout_ms", 30000)),
            )
            if response.ok:
                index = await read_body(await response.body())
                if index:
                    logger.info("[BUSQUEDA] Excel distribuidores descargado por POST autenticado.")
                    return index
            else:
                logger.warning("[BUSQUEDA] Excel distribuidores por POST: HTTP %s", response.status)
        except Exception as exc:
            logger.warning("[BUSQUEDA] Falló respaldo POST del Excel distribuidores: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("[BUSQUEDA] No pude descargar/leer el Excel completo de distribuidores: %s", exc)
        return {}
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _distributor_id_from_url(url: str) -> str:
    m = re.search(r"/distribuidores/show/(\d+)(?:[/?#]|$)", _s(url), flags=re.I)
    return m.group(1) if m else ""


async def _extract_distributor_reference(page) -> dict[str, str]:
    """Obtiene el enlace real del distribuidor desde el show de la guía.

    En Epresis el nombre del distribuidor es un <a> que apunta a
    /distribuidores/show/<ID>. Ese ID es más estable que intentar inferirlo
    desde el texto visible o desde la grilla.
    """
    data = await page.evaluate(
        r"""() => {
          const clean = s => (s || '').toString().replace(/\s+/g, ' ').trim();
          const anchors = [...document.querySelectorAll('a[href*="/distribuidores/show/"]')];
          if (!anchors.length) return null;
          let best = anchors.find(a => {
            const root = a.closest('tr,.form-group,.row,td,div') || a.parentElement;
            return /distribuidor/i.test(clean(root?.innerText || root?.textContent));
          }) || anchors[0];
          const href = best.href || best.getAttribute('href') || '';
          const text = clean(best.innerText || best.textContent || '');
          const m = href.match(/\/distribuidores\/show\/(\d+)/i);
          return { url: href, id: m ? m[1] : '', name: text };
        }"""
    )
    return {str(k): _s(v) for k, v in (data or {}).items()}


async def _scrape_distributor_show(page, url: str, timeout_ms: int) -> dict[str, str]:
    """Lee nombre/DNI/teléfono/celular desde la ficha real del distribuidor."""
    if not url:
        return {}
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    labeled = await _scrape_labeled_values(page)
    extra = await page.evaluate(
        r"""() => {
          const clean=s=>(s||'').toString().replace(/\s+/g,' ').trim();
          const norm=s=>clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
          const out={};
          const wanted=['telefono','celular','dni','nombre','apellido'];
          for (const el of document.querySelectorAll('th,td,label,strong,b,dt,span,div,p')) {
            const key=norm(el.innerText||el.textContent).replace(/[:*]+$/,'').trim();
            if (!wanted.includes(key)) continue;
            let val='';
            const tr=el.closest('tr');
            if (tr) {
              const cells=[...tr.querySelectorAll(':scope > th,:scope > td')];
              const idx=cells.indexOf(el.closest('th,td'));
              if (idx>=0 && cells[idx+1]) val=clean(cells[idx+1].innerText||cells[idx+1].textContent);
            }
            if (!val) {
              const parent=el.parentElement;
              if (parent) {
                const candidates=[...parent.children].filter(x=>x!==el);
                val=clean(candidates.map(x=>x.value ?? x.innerText ?? x.textContent).find(Boolean));
              }
            }
            if (val && !out[key]) out[key]=val;
          }
          return out;
        }"""
    )
    merged = {**{str(k): str(v) for k, v in (labeled or {}).items()}, **{str(k): str(v) for k, v in (extra or {}).items()}}
    phone = _first(
        _pick_labeled(merged, "Teléfono", "Telefono", "Tel."),
        _pick_labeled(merged, "Celular", "Móvil", "Movil"),
        merged.get("telefono"), merged.get("celular"),
    )
    dni = _first(_pick_labeled(merged, "DNI", "Documento"), merged.get("dni"))
    name = " ".join(x for x in [
        _first(_pick_labeled(merged, "Nombre"), merged.get("nombre")),
        _first(_pick_labeled(merged, "Apellido"), merged.get("apellido")),
    ] if x).strip()
    return {"phone": phone, "dni": dni, "name": name}


def _deep_values(obj: Any, *names: str) -> list[Any]:
    """Busca claves por nombre normalizado en cualquier nivel del JSON."""
    wanted = {_norm(n).replace(" ", "") for n in names if n}
    out: list[Any] = []

    def walk(cur: Any):
        if isinstance(cur, dict):
            for key, value in cur.items():
                nk = _norm(str(key)).replace(" ", "")
                if nk in wanted and value not in (None, "", [], {}):
                    out.append(value)
                walk(value)
        elif isinstance(cur, list):
            for item in cur[:100]:
                walk(item)

    walk(obj)
    return out


def _deep_first(obj: Any, *names: str) -> str:
    for value in _deep_values(obj, *names):
        text = _s(value)
        if text:
            return text
    return ""


def _service_text(row: dict) -> str:
    servicio = row.get("servicio") if isinstance(row.get("servicio"), dict) else {}
    datos = row.get("datos_envios") if isinstance(row.get("datos_envios"), dict) else {}
    value = _first(
        servicio.get("nombre"), servicio.get("descripcion"),
        row.get("servicio_nombre"),
        row.get("servicio") if not isinstance(row.get("servicio"), dict) else "",
        row.get("tipo_servicio"), datos.get("tipoServicio"),
        row.get("canal"), _deep_first(row, "servicioNombre", "servicio_desc", "descripcionServicio"),
    )
    if _norm(value) in {"MFLEX", "MERCADO FLEX"}:
        return "FLEX"
    if value:
        return value
    return _first(row.get("servicio_id"), datos.get("servicio_id"))

def _pick_labeled(mapping: dict[str, str], *names: str) -> str:
    nm = {_norm(k): _s(v) for k, v in (mapping or {}).items()}
    for name in names:
        target = _norm(name)
        if target in nm and nm[target]:
            return nm[target]
    for name in names:
        target = _norm(name)
        for key, value in nm.items():
            if target and target in key and value:
                return value
    return ""


async def _scrape_labeled_values(page) -> dict[str, str]:
    data = await page.evaluate(
        r"""() => {
          const out = {};
          const clean = s => (s || '').toString().replace(/\s+/g, ' ').trim();
          const put = (k,v) => { k=clean(k).replace(/[:*]+$/,'').trim(); v=clean(v); if(k && v && !out[k]) out[k]=v; };
          const textOf = el => {
            if (!el) return '';
            if (el.tagName === 'SELECT') {
              const opt = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
              return clean((opt && opt.textContent) || el.value);
            }
            return clean(el.value ?? el.innerText ?? el.textContent);
          };
          document.querySelectorAll('label').forEach(label => {
            const key = clean(label.innerText || label.textContent);
            let ctl = label.htmlFor ? document.getElementById(label.htmlFor) : null;
            if (!ctl) {
              let root = label.parentElement;
              for (let i=0; root && i<5 && !ctl; i++, root=root.parentElement) ctl = root.querySelector('input,select,textarea');
            }
            let val = textOf(ctl);
            if (!val && label.parentElement) {
              const copy = label.parentElement.cloneNode(true);
              copy.querySelectorAll('label').forEach(x => x.remove());
              val = clean(copy.innerText || copy.textContent);
            }
            put(key,val);
          });
          document.querySelectorAll('tr').forEach(tr => {
            const cells = [...tr.querySelectorAll(':scope > th,:scope > td')].map(x=>clean(x.innerText||x.textContent));
            if (cells.length === 2) put(cells[0], cells[1]);
          });
          document.querySelectorAll('dt').forEach(dt => { const dd=dt.nextElementSibling; if(dd && dd.tagName==='DD') put(dt.innerText,dd.innerText); });
          document.querySelectorAll('.form-group,.row').forEach(root => {
            const label=root.querySelector('label,.control-label,strong,b');
            if(!label) return;
            let value=root.querySelector('input,select,textarea');
            let val=textOf(value);
            if(!val){
              const candidates=[...root.querySelectorAll('p,span,div,td')].filter(x=>x!==label && !x.contains(label));
              val=clean(candidates.map(x=>x.innerText||x.textContent).find(Boolean));
            }
            put(label.innerText||label.textContent,val);
          });
          document.querySelectorAll('input,select,textarea').forEach(el => {
            const key = clean(el.getAttribute('name') || el.getAttribute('id') || el.getAttribute('placeholder'));
            put(key,textOf(el));
          });
          return out;
        }"""
    )
    return {str(k): str(v) for k, v in (data or {}).items()}


def _strip_html(value: Any) -> str:
    """Convierte una celda HTML simple en texto visible."""
    text = re.sub(r"<[^>]+>", " ", _s(value))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _distributor_from_cells(cells: list[Any]) -> dict[str, str]:
    """Mapea las columnas reales de /distribuidores/lista-distribuidores.

    Orden observado en Epresis:
      0 id, 1 código/DNI+P, 2 foto, 3 nombre, 4 apellido, 5 DNI,
      6 nacimiento, 7 empresa, 8 zona, 9 -, 10 teléfono, 11 celular,
      12 email, ...
    """
    vals = [_strip_html(v) for v in cells]
    if len(vals) < 6:
        return {}
    def at(i: int) -> str:
        return vals[i] if i < len(vals) else ""
    telefono = at(10)
    celular = at(11)
    return {
        "id": at(0),
        "codigo": at(1),
        "nombre": at(3),
        "apellido": at(4),
        "dni": at(5) or re.sub(r"\D", "", at(1)),
        "telefono": telefono,
        "celular": celular,
        "email": at(12),
    }


def _distributor_from_html_row(row_html: str) -> dict[str, str]:
    cells = re.findall(r"<td\b[^>]*>(.*?)</td>", _s(row_html), flags=re.I | re.S)
    return _distributor_from_cells(cells) if cells else {}


def _extract_distributor_phone(row: Any) -> str:
    """Extrae teléfono/celular aun cuando Epresis anida o devuelve filas HTML."""
    if isinstance(row, str):
        parsed = _distributor_from_html_row(row)
        return _first(parsed.get("telefono"), parsed.get("celular"))
    if isinstance(row, (tuple, list)) and row and not any(isinstance(v, (dict, list)) for v in row):
        parsed = _distributor_from_cells(list(row))
        return _first(parsed.get("telefono"), parsed.get("celular"))
    if not isinstance(row, (dict, list)):
        return ""

    exact_keys = {
        "telefono", "telefono1", "telefono2", "tel", "phone", "telefono_celular",
        "celular", "cel", "movil", "mobile", "whatsapp", "telefono_contacto",
        "celular_contacto", "nro_telefono", "numero_telefono",
    }
    candidates: list[str] = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            for key, value in obj.items():
                nk = _norm(str(key)).replace(" ", "_").lower()
                if nk in exact_keys or any(token in nk for token in ("telefono", "celular", "movil", "phone", "whatsapp")):
                    text = _s(value)
                    if text and any(ch.isdigit() for ch in text):
                        candidates.append(text)
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(row)
    return candidates[0] if candidates else ""


def _normalize_distributor_row(row: Any) -> dict:
    if isinstance(row, dict):
        # Bootstrap-table a veces guarda el HTML de la fila/celdas en un campo.
        for key in ("html", "row", "tr", "content"):
            value = row.get(key)
            if isinstance(value, str) and "<td" in value.lower():
                parsed = _distributor_from_html_row(value)
                if parsed:
                    return {**row, **{k: v for k, v in parsed.items() if v}}
        return row
    if isinstance(row, str):
        return _distributor_from_html_row(row)
    if isinstance(row, (tuple, list)):
        return _distributor_from_cells(list(row))
    return {}


def _extract_distributor_rows(data: Any) -> list[dict]:
    """Tolera rows/data/results, arrays de celdas y HTML de la tabla de distribuidores."""
    if isinstance(data, str):
        trs = re.findall(r"<tr\b[^>]*>.*?</tr>", data, flags=re.I | re.S)
        return [r for tr in trs if (r := _distributor_from_html_row(tr))]
    if isinstance(data, list):
        return [r for item in data if (r := _normalize_distributor_row(item))]
    if not isinstance(data, dict):
        return []
    for key in ("rows", "data", "results", "items"):
        value = data.get(key)
        if isinstance(value, (list, str)):
            rows = _extract_distributor_rows(value)
            if rows:
                return rows
        if isinstance(value, dict):
            nested = _extract_distributor_rows(value)
            if nested:
                return nested
    if any(k in data for k in ("dni", "nombre", "apellido", "telefono", "celular")):
        return [data]
    return []


async def _search_distributor_in_page(page, base: str, path: str, dni: str, logger, timeout_ms: int = 30000) -> dict[str, str]:
    """Busca el distribuidor usando la grilla visible real de Epresis.

    La pagina /distribuidores/lista-distribuidores usa una tabla con filtros por columna.
    Para evitar depender del endpoint interno de bootstrap-table, abrimos la pagina,
    localizamos la columna DNI por su encabezado, escribimos el DNI en su filtro y
    leemos las columnas Telefono/Celular de la fila resultante.
    """
    if not dni:
        return {}
    url = base.rstrip("/") + path
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_timeout(700)
    except Exception:
        pass

    # Detectar encabezados/inputs por texto visible, sin depender de clases minificadas.
    meta = await page.evaluate(
        r"""() => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const norm=s=>clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
          const tables=[...document.querySelectorAll('table')];
          for (const table of tables) {
            const ths=[...table.querySelectorAll('thead th')];
            if (!ths.length) continue;
            const headers=ths.map(th=>norm(th.innerText||th.textContent));
            const dniIndex=headers.findIndex(t=>t==='dni' || t.includes('documento') || t.includes('dni'));
            const telIndex=headers.findIndex(t=>t==='telefono' || (t.includes('telefono') && !t.includes('celular')));
            const celIndex=headers.findIndex(t=>t.includes('celular') || t.includes('movil'));
            if (dniIndex < 0 || (telIndex < 0 && celIndex < 0)) continue;
            const dniTh=ths[dniIndex];
            let input=dniTh.querySelector('input');
            if (!input) {
              const all=[...table.querySelectorAll('thead input')];
              input=all.find(el=>{
                const ph=norm(el.getAttribute('placeholder'));
                const nm=norm(el.getAttribute('name'));
                const id=norm(el.getAttribute('id'));
                return ph.includes('dni') || nm.includes('dni') || id.includes('dni');
              }) || null;
            }
            return {found:true, dniIndex, telIndex, celIndex, hasInput:!!input};
          }
          return {found:false};
        }"""
    )
    if not meta or not meta.get("found"):
        logger.warning("[BUSQUEDA] No pude identificar columnas DNI/Telefono en la grilla de distribuidores.")
        return {}

    # Completar el filtro de DNI dentro del encabezado correspondiente.
    filtered = await page.evaluate(
        r"""(dni) => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const norm=s=>clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
          for (const table of document.querySelectorAll('table')) {
            const ths=[...table.querySelectorAll('thead th')];
            const headers=ths.map(th=>norm(th.innerText||th.textContent));
            const i=headers.findIndex(t=>t==='dni' || t.includes('documento') || t.includes('dni'));
            if (i < 0) continue;
            let input=ths[i].querySelector('input');
            if (!input) {
              input=[...table.querySelectorAll('thead input')].find(el=>{
                const x=norm((el.getAttribute('placeholder')||'')+' '+(el.getAttribute('name')||'')+' '+(el.getAttribute('id')||''));
                return x.includes('dni');
              }) || null;
            }
            if (!input) return false;
            input.focus();
            const proto=Object.getPrototypeOf(input);
            const desc=Object.getOwnPropertyDescriptor(proto,'value');
            if (desc && desc.set) desc.set.call(input, dni); else input.value=dni;
            input.dispatchEvent(new Event('input',{bubbles:true}));
            input.dispatchEvent(new Event('change',{bubbles:true}));
            input.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
            input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
            return true;
          }
          return false;
        }""", dni
    )
    if filtered:
        try:
            await page.wait_for_timeout(1400)
        except Exception:
            pass

    result = await page.evaluate(
        r"""(dni) => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const norm=s=>clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
          const digits=s=>(s||'').replace(/\D/g,'');
          for (const table of document.querySelectorAll('table')) {
            const ths=[...table.querySelectorAll('thead th')];
            const headers=ths.map(th=>norm(th.innerText||th.textContent));
            const dniIndex=headers.findIndex(t=>t==='dni' || t.includes('documento') || t.includes('dni'));
            const telIndex=headers.findIndex(t=>t==='telefono' || (t.includes('telefono') && !t.includes('celular')));
            const celIndex=headers.findIndex(t=>t.includes('celular') || t.includes('movil'));
            if (dniIndex < 0) continue;
            for (const tr of table.querySelectorAll('tbody tr')) {
              const tds=[...tr.querySelectorAll('td')];
              if (!tds.length) continue;
              const rdni=clean(tds[dniIndex]?.innerText||tds[dniIndex]?.textContent);
              if (digits(rdni) !== digits(dni)) continue;
              const telefono=telIndex>=0 ? clean(tds[telIndex]?.innerText||tds[telIndex]?.textContent) : '';
              const celular=celIndex>=0 ? clean(tds[celIndex]?.innerText||tds[celIndex]?.textContent) : '';
              const nombre=clean(tds[3]?.innerText||tds[3]?.textContent);
              const apellido=clean(tds[4]?.innerText||tds[4]?.textContent);
              return {
                id: tr.getAttribute('data-uniqueid') || clean(tds[0]?.innerText||tds[0]?.textContent),
                dni: rdni, nombre, apellido, telefono, celular
              };
            }
          }
          return null;
        }""", dni
    )
    return result or {}


def _parse_distributor_text(value: str) -> tuple[str, str]:
    """Devuelve (dni, nombre visible) a partir del texto habitual de Epresis."""
    text = _s(value)
    if not text:
        return "", ""
    m = re.match(r"\s*(\d{6,10})[A-Z]?\s*-\s*(.+?)\s*$", text, flags=re.I)
    if m:
        name = m.group(2).strip()
        # Epresis suele mostrar APELLIDO..., NOMBRE. Lo dejamos legible sin inventar orden.
        return m.group(1), name
    dni = ""
    mdni = re.search(r"\b(\d{7,8})\b", text)
    if mdni:
        dni = mdni.group(1)
    return dni, text


async def _search_distributor(context, page, settings: dict, csrf: str, distributor_text: str, logger) -> dict[str, str]:
    """Busca al distribuidor en /distribuidores/lista-distribuidores y obtiene su teléfono.

    La tabla real de Epresis tiene columnas separadas Teléfono y Celular. Primero filtramos
    por DNI cuando está disponible (más preciso) y, si no devuelve filas, por apellido.
    Luego, si el JSON no expone el teléfono de forma usable, abrimos el detalle del
    distribuidor y leemos los campos visibles Teléfono/Celular como respaldo.
    """
    dni, name = _parse_distributor_text(distributor_text)
    if not distributor_text:
        return {"dni": dni, "name": name, "phone": ""}

    path = str(settings.get("distributor_search_path") or "/distribuidores/lista-distribuidores")
    base = settings["base_url"].rstrip("/")
    surname = ""
    if " - " in distributor_text:
        after = distributor_text.split(" - ", 1)[1]
        surname = after.split(",", 1)[0].strip().split()[0] if after.strip() else ""
    if not surname and name:
        surname = name.split(",", 1)[0].strip().split()[0]

    async def fetch_rows(filter_obj: dict) -> list[dict]:
        payload = {
            "limit": "20",
            "offset": "0",
            "_token": csrf,
            "estado": "1",
            "filter": json.dumps(filter_obj, ensure_ascii=False),
        }
        response = await context.request.post(
            base + path,
            form=payload,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": base + path,
            },
            timeout=int(settings.get("request_timeout_ms", 30000)),
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")
        try:
            data = await response.json()
        except Exception:
            data = await response.text()
        return _extract_distributor_rows(data)

    try:
        rows: list[dict] = []
        if dni:
            # La grilla permite filtrar por DNI; es preferible a apellido para evitar homónimos.
            rows = await fetch_rows({"dni": dni})
        if not rows and surname:
            rows = await fetch_rows({"apellido": surname})
        if not rows and dni:
            ui_row = await _search_distributor_in_page(
                page, base, path, dni, logger, int(settings.get("request_timeout_ms", 30000))
            )
            if ui_row:
                ui_phone = _first(ui_row.get("telefono"), ui_row.get("celular"))
                ui_name = " ".join(x for x in [_s(ui_row.get("nombre")), _s(ui_row.get("apellido"))] if x).strip() or name
                if ui_phone:
                    return {"dni": _first(ui_row.get("dni"), dni), "name": ui_name, "phone": ui_phone}
                rows = [ui_row]
        if not rows:
            return {"dni": dni, "name": name, "phone": ""}

        matches = rows
        if dni:
            exact = [
                r for r in rows
                if re.sub(r"\D", "", _s(r.get("dni") or r.get("documento") or r.get("codigo"))) == re.sub(r"\D", "", dni)
            ]
            if exact:
                matches = exact
        row = _normalize_distributor_row(matches[0])

        rdni = _first(row.get("dni"), row.get("documento"), dni)
        rname = " ".join(x for x in [_s(row.get("nombre")), _s(row.get("apellido"))] if x).strip() or name
        phone = _first(
            row.get("telefono"), row.get("celular"), row.get("telefono_celular"),
            row.get("movil"), row.get("phone"), row.get("whatsapp"),
            _extract_distributor_phone(row),
        )

        # Respaldo principal: consultar la grilla visible real y leer sus columnas Telefono/Celular.
        if not phone and dni:
            try:
                ui_row = await _search_distributor_in_page(
                    page, base, path, dni, logger, int(settings.get("request_timeout_ms", 30000))
                )
                if ui_row:
                    phone = _first(ui_row.get("telefono"), ui_row.get("celular"))
                    rdni = _first(ui_row.get("dni"), rdni)
                    ui_name = " ".join(x for x in [_s(ui_row.get("nombre")), _s(ui_row.get("apellido"))] if x).strip()
                    rname = ui_name or rname
                    if not row.get("id") and ui_row.get("id"):
                        row["id"] = ui_row.get("id")
            except Exception as exc:
                logger.warning("[BUSQUEDA] No pude leer la grilla visible de distribuidores para %s: %s", dni, exc)

        # Ultimo respaldo: abrir la ficha del distribuidor y leer Telefono/Celular del HTML visible.
        dist_id = _first(row.get("id"), row.get("distribuidor_id"), row.get("DT_RowId"))
        if not phone and dist_id:
            try:
                show_url = base + f"/distribuidores/show/{dist_id}"
                await page.goto(show_url, wait_until="domcontentloaded", timeout=int(settings.get("request_timeout_ms", 30000)))
                labeled = await _scrape_labeled_values(page)
                phone = _first(
                    _pick_labeled(labeled, "Teléfono", "Telefono", "Tel."),
                    _pick_labeled(labeled, "Celular", "Móvil", "Movil"),
                )
            except Exception as exc:
                logger.warning("[BUSQUEDA] No pude leer la ficha del distribuidor %s: %s", dist_id, exc)

        if not phone:
            logger.warning("[BUSQUEDA] Distribuidor encontrado sin teléfono/celular: %s", distributor_text)
        return {"dni": rdni, "name": rname, "phone": phone}
    except Exception as exc:
        logger.warning("[BUSQUEDA] No pude enriquecer distribuidor %s: %s", distributor_text, exc)
        return {"dni": dni, "name": name, "phone": ""}




def _photo_value_present(value: Any) -> bool:
    """Devuelve True sólo cuando un campo asociado a foto contiene evidencia usable."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        return any(_photo_value_present(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_photo_value_present(v) for v in value)
    text = _s(value)
    if not text:
        return False
    norm = _norm(text)
    if norm in {"0", "NO", "FALSE", "NULL", "NONE", "SIN FOTO", "SIN FOTOS", "NO TIENE FOTO", "NO TIENE FOTOS"}:
        return False
    return True


def _photo_from_payload(payload: Any) -> bool:
    """Busca campos de foto/evidencia dentro del JSON de la guía sin confundir avatar/logo."""
    wanted = ("FOTO", "PHOTO", "IMAGEN", "IMAGE", "EVIDENCIA")
    excluded = ("DISTRIBUIDOR", "CHOFER", "PERFIL", "AVATAR", "LOGO", "CLIENTE")

    def walk(obj: Any, path: str = "") -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_norm = _norm(str(key))
                full = f"{path} {key_norm}".strip()
                if any(token in full for token in wanted) and not any(token in full for token in excluded):
                    if _photo_value_present(value):
                        return True
                if isinstance(value, (dict, list, tuple)) and walk(value, full):
                    return True
        elif isinstance(obj, (list, tuple)):
            for value in obj:
                if walk(value, path):
                    return True
        return False

    return walk(payload)


def _photo_from_labeled(labeled: dict[str, str]) -> bool:
    wanted = ("FOTO", "FOTOS", "IMAGEN", "IMAGENES", "EVIDENCIA", "EVIDENCIAS")
    excluded = ("DISTRIBUIDOR", "CHOFER", "PERFIL", "AVATAR", "LOGO")
    for key, value in (labeled or {}).items():
        nk = _norm(key)
        if any(token in nk for token in wanted) and not any(token in nk for token in excluded):
            if _photo_value_present(value):
                return True
    return False


async def _photo_from_show(page, labeled: dict[str, str]) -> bool:
    """Detecta una foto/evidencia en el show de la guía sin contar imágenes decorativas."""
    if _photo_from_labeled(labeled):
        return True
    try:
        return bool(await page.evaluate(
            r"""() => {
              const clean=s=>(s||'').toString().replace(/\s+/g,' ').trim();
              const norm=s=>clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
              const photoWords=/(foto|fotos|imagen|imagenes|evidencia|evidencias|proof)/i;
              const excluded=/(logo|avatar|perfil|distribuidor|chofer)/i;
              for (const el of document.querySelectorAll('a[href],img[src],button,[data-lightbox],[data-fancybox]')) {
                const href=clean(el.getAttribute('href')||el.getAttribute('src')||'');
                const own=clean(el.innerText||el.textContent||el.getAttribute('title')||el.getAttribute('alt')||'');
                const root=el.closest('tr,.form-group,.row,.card,.panel,td,div')||el.parentElement;
                const around=clean(root?.innerText||root?.textContent||'');
                const haystack=norm(`${href} ${own} ${around}`);
                if (!photoWords.test(haystack) || excluded.test(haystack)) continue;
                const looksLikeImage=/\.(jpe?g|png|webp|gif)(?:[?#]|$)/i.test(href) || /foto|imagen|evidencia|proof/i.test(href);
                if (looksLikeImage || el.tagName==='IMG' || photoWords.test(own) || photoWords.test(around)) return true;
              }
              return false;
            }"""
        ))
    except Exception:
        return False

def _details_from_row(row: dict, guide: str) -> dict[str, str]:
    cliente = row.get("cliente") if isinstance(row.get("cliente"), dict) else {}
    comprador = row.get("comprador") if isinstance(row.get("comprador"), dict) else {}
    datos = row.get("datos_envios") if isinstance(row.get("datos_envios"), dict) else {}
    estado = row.get("estado") if isinstance(row.get("estado"), dict) else {}

    street = _first(
        comprador.get("calle"), row.get("calle"),
        _deep_first(row, "domicilio_calle", "comprador_calle")
    )
    height = _first(comprador.get("altura"), row.get("altura"), _deep_first(row, "domicilio_altura"))
    full_address = _first(
        comprador.get("full_address"), row.get("domicilio"), row.get("comprador_domicilio"),
        _deep_first(row, "fullAddress", "direccion", "direccion_completa")
    )
    if not full_address:
        full_address = " ".join(x for x in (street, height) if x).strip()

    state_code = _first(estado.get("codigo"), row.get("estado_codigo"), _deep_first(row, "codigo_estado"))
    state_name = _first(estado.get("nombre"), row.get("estado_nombre"), _deep_first(row, "nombre_estado"))
    state_id = _first(estado.get("id"), row.get("estado_id"))
    state_text = " - ".join(x for x in (state_code, state_name) if x) or state_name or state_id

    client_text = _first(
        cliente.get("empresa"), cliente.get("nombre_fantasia"),
        row.get("cliente_nombre"), row.get("empresa_cliente"),
        row.get("cliente") if not isinstance(row.get("cliente"), dict) else "",
        _deep_first(row, "clienteEmpresa", "nombreCliente"),
    )

    return {
        "guia": _first(row.get("id"), row.get("retiro_id"), _deep_first(row, "nroGuia", "nro_guia"), guide),
        "remito": _unwrap_excel(_first(
            row.get("remito"), row.get("rto_cliente"), row.get("shipping_id"),
            _get_nested(row, ("dato_flex", "shipping_id")), _deep_first(row, "remitoCliente", "rtoCliente")
        )),
        "guia_agente": _unwrap_excel(_first(
            datos.get("guiaAgente"), row.get("guiaAgente"), row.get("guia_agente"),
            _get_nested(row, ("dato_flex", "orden_id")), _deep_first(row, "guiaAgente", "guia_agente")
        )),
        "cliente": client_text,
        "servicio": _service_text(row),
        "destinatario": _first(
            comprador.get("apellido_nombre"), row.get("apellido_nombre"), row.get("nombre_comprador"),
            _get_nested(row, ("dato_flex", "nombre")), _deep_first(row, "destinatario", "nombreDestinatario")
        ),
        "domicilio": full_address,
        "localidad": _first(comprador.get("localidad"), row.get("localidad"), _get_nested(row, ("dato_flex", "localidad")), _deep_first(row, "localidadComprador")),
        "provincia": _first(comprador.get("provincia"), row.get("provincia"), _get_nested(row, ("dato_flex", "provincia")), _deep_first(row, "provinciaComprador")),
        "codigo_postal": _first(comprador.get("cp"), row.get("cp_comprador"), row.get("cp"), _get_nested(row, ("dato_flex", "cp")), _deep_first(row, "codigoPostal", "codigo_postal")),
        "telefono": _first(comprador.get("celular"), row.get("celular"), row.get("telefono"), _get_nested(row, ("dato_flex", "tel")), _deep_first(row, "telefonoDestinatario", "telefono_comprador")),
        "estado": state_text,
        "foto": "Sí" if _photo_from_payload(row) else "No",
        "distribuidor_raw": _first(row.get("distribuidor"), row.get("distribuidor_nombre"), _deep_first(row, "nombreDistribuidor")),
    }


def _merge_show(details: dict[str, str], labeled: dict[str, str]) -> dict[str, str]:
    # El show se usa sólo para completar huecos; nunca pisa datos estructurados del endpoint.
    mapping = {
        "remito": ("Rto. Cliente", "Remito", "Rto Cliente", "Remito Cliente"),
        "guia_agente": ("Guía Agente", "Guia Agente"),
        "cliente": ("Cliente", "Empresa", "Empresa Cliente"),
        "servicio": ("Servicio", "Tipo Servicio", "Canal"),
        "destinatario": ("Destinatario", "Apellido y Nombre", "Comprador", "Nombre Destinatario"),
        "localidad": ("Localidad", "Localidad/Barrio"),
        "provincia": ("Provincia",),
        "codigo_postal": ("CP", "Código postal", "Codigo postal"),
        "telefono": ("Teléfono", "Telefono", "Celular", "Teléfono destinatario", "Telefono destinatario"),
        "estado": ("Estado",),
        "distribuidor_raw": ("Distribuidor", "Distribuidor Recorrido"),
    }
    for key, names in mapping.items():
        if not details.get(key):
            details[key] = _pick_labeled(labeled, *names)
    if not details.get("domicilio"):
        details["domicilio"] = " ".join(
            x for x in (_pick_labeled(labeled, "Calle", "Domicilio"), _pick_labeled(labeled, "Altura")) if x
        ).strip()
    return details


async def search_shipments(cfg: dict, identifiers: list[str], logger) -> list[dict[str, str]]:
    """Búsqueda masiva no destructiva de guía/remito/Guía Agente."""
    from app.descarga.auth import ensure_authenticated, extract_csrf_token
    settings = epresis_settings(cfg)
    ce = cfg.get("cambio_estado") or {}
    bg = cfg.get("busqueda_guias") or {}
    settings["remito_search_path"] = str(ce.get("remito_search_path") or "/tracker/searchByRemitoCliente")
    settings["guia_agente_search_path"] = str(ce.get("guia_agente_search_path") or "/tracker/searchByGuiaAgente")
    settings["distributor_search_path"] = str(
        bg.get("distributor_search_path")
        or (cfg.get("denuncias") or {}).get("distributor_search_path")
        or "/distribuidores/lista-distribuidores"
    )
    settings["distributor_excel_path"] = str(
        bg.get("distributor_excel_path") or "/distribuidores/excelDistribuidores"
    )
    arrival_url = settings["base_url"].rstrip("/") + str(ce.get("arrival_path") or "/guias/arribo_paquetes")

    out: list[dict[str, str]] = []
    seen_guides: set[str] = set()
    distributor_cache: dict[str, dict[str, str]] = {}

    async with async_playwright() as p:
        profile = resolve_path(cfg, "epresis_profile")
        profile.mkdir(parents=True, exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=bool(settings.get("headless", True)),
            accept_downloads=True,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await ensure_authenticated(page, settings, logger)
            response = await page.goto(arrival_url, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Epresis devolvió HTTP {response.status} al abrir Arribo de Paquetes.")
            csrf = await extract_csrf_token(page)
            api = EpresisAPI(context.request, settings, csrf, logger, referer=arrival_url)

            # Fuente preferida para teléfono/celular: exportación completa de Distribuidores.
            # Se descarga UNA vez y luego se consulta localmente por DNI.
            distributor_excel_index = await _download_distributor_excel_index(page, context, settings, logger)

            for idx, value in enumerate(identifiers, start=1):
                value = str(value).strip()
                if not value:
                    continue
                logger.info("[BUSQUEDA] Resolviendo %s/%s: %s", idx, len(identifiers), value)
                try:
                    resolved = await _resolve_one(context, api, csrf, settings, arrival_url, value, logger)
                    if not resolved.retiro_id:
                        out.append({"entrada": value, "error": resolved.message or "No encontrado"})
                        continue
                    guide = str(resolved.retiro_id)
                    if guide in seen_guides:
                        continue
                    seen_guides.add(guide)
                    row = await _filter_guide(api, guide) or {}
                    details = _details_from_row(row, guide)
                    details["entrada"] = value
                    details["tipo_detectado"] = resolved.detected_type

                    # Completar datos que el filtro no exponga usando el show ya conocido.
                    # También tomamos el enlace REAL del nombre del distribuidor; Epresis
                    # lo apunta a /distribuidores/show/<ID>.
                    distributor_ref: dict[str, str] = {}
                    try:
                        show_url = settings["base_url"].rstrip("/") + f"/guias/editar-guia-v2/show/{guide}"
                        await page.goto(show_url, wait_until="domcontentloaded", timeout=settings["request_timeout_ms"])
                        labeled = await _scrape_labeled_values(page)
                        details = _merge_show(details, labeled)
                        if details.get("foto") != "Sí" and await _photo_from_show(page, labeled):
                            details["foto"] = "Sí"
                        distributor_ref = await _extract_distributor_reference(page)
                        if distributor_ref.get("name") and not details.get("distribuidor_raw"):
                            details["distribuidor_raw"] = distributor_ref["name"]
                        details["distribuidor_id"] = distributor_ref.get("id", "")
                        details["distribuidor_url"] = distributor_ref.get("url", "")
                    except Exception as exc:
                        logger.warning("[BUSQUEDA] No pude completar show/%s: %s", guide, exc)

                    dist_raw = details.get("distribuidor_raw", "")
                    parsed_dni, parsed_name = _parse_distributor_text(dist_raw)
                    dni_key = re.sub(r"\D", "", parsed_dni)

                    # Fuente principal: la ficha REAL enlazada desde el nombre del distribuidor
                    # dentro del show de la guía. Así usamos el ID exacto de Epresis.
                    direct_dist: dict[str, str] = {}
                    dist_url = details.get("distribuidor_url", "")
                    if dist_url:
                        try:
                            direct_dist = await _scrape_distributor_show(
                                page, dist_url, int(settings.get("request_timeout_ms", 30000))
                            )
                        except Exception as exc:
                            logger.warning("[BUSQUEDA] No pude leer ficha distribuidor %s: %s", dist_url, exc)

                    excel_dist = distributor_excel_index.get(dni_key, {}) if dni_key else {}
                    if direct_dist.get("phone"):
                        dist = {
                            "dni": direct_dist.get("dni") or parsed_dni,
                            "name": direct_dist.get("name") or distributor_ref.get("name") or parsed_name,
                            "phone": direct_dist.get("phone", ""),
                        }
                    elif excel_dist:
                        dist = {
                            "dni": excel_dist.get("dni", parsed_dni),
                            "name": excel_dist.get("name", parsed_name),
                            "phone": excel_dist.get("phone", ""),
                        }
                    else:
                        cache_key = dist_raw or details.get("distribuidor_id", "") or ""
                        if cache_key not in distributor_cache:
                            distributor_cache[cache_key] = await _search_distributor(context, page, settings, csrf, dist_raw, logger)
                        dist = distributor_cache[cache_key]

                    details["distribuidor_dni"] = dist.get("dni", "") or parsed_dni
                    details["distribuidor_nombre"] = dist.get("name", "") or distributor_ref.get("name", "") or parsed_name
                    details["distribuidor_telefono"] = dist.get("phone", "")
                    details["show_url"] = settings["base_url"].rstrip("/") + f"/guias/editar-guia-v2/show/{guide}"
                    out.append(details)
                except Exception as exc:
                    logger.exception("[BUSQUEDA] Error resolviendo %s", value)
                    out.append({"entrada": value, "error": str(exc)})
            return out
        finally:
            await context.close()


__all__ = ["extract_identifiers", "search_shipments"]
