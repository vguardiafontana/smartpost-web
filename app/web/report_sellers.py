"""Persistent seller configuration, scoped to the web report module."""
from copy import deepcopy
import json
import os
import threading
from uuid import uuid4

from app.core.config import load_config, report_seller_configs
from app.core.runtime_paths import data_root
from app.procesamiento.rules import canonical_seller_name, normalize_key

_lock = threading.RLock()


def _storage(value=None):
    url = os.environ.get('DATABASE_URL', '').strip()
    if url:
        import psycopg
        with psycopg.connect(url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute('CREATE TABLE IF NOT EXISTS smartpost_report_sellers (id INTEGER PRIMARY KEY, payload JSONB NOT NULL)')
                if value is not None:
                    cur.execute('INSERT INTO smartpost_report_sellers VALUES (1, %s::jsonb) ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload', (json.dumps(value, ensure_ascii=False),))
                cur.execute('SELECT payload FROM smartpost_report_sellers WHERE id=1')
                row = cur.fetchone()
                return row[0] if row else None
    path = data_root() / 'web_report_sellers.json'
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'{path.name}.{uuid4().hex}.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def _initial(cfg):
    from datetime import date
    saturday = {s['seller'] for s in report_seller_configs(cfg, date(2026, 10, 3), enabled_only=False)}
    result = deepcopy(cfg.get('sellers', []))
    for s in result:
        s.setdefault('report_days', [0, 1, 2, 3, 4, 6] + ([5] if s['seller'] in saturday else []))
        s['report_days'].sort()
    return result


def _read(cfg):
    saved = _storage()
    return _initial(cfg) if saved is None else saved


def apply_report_sellers(cfg):
    if 'sellers' not in cfg:
        return cfg
    with _lock:
        return {**cfg, 'sellers': _read(cfg)}


def _public(s):
    return {'seller': s['seller'], 'client': s.get('expected_empresa') or s['seller'], 'days': s['report_days'], 'enabled': s.get('enabled', True)}


def list_sellers():
    with _lock:
        return [_public(s) for s in _read(load_config())]


def update_seller(original, name, client, days):
    name = name.strip().upper()
    client = client.strip()
    if not name or not client or not days or any(type(d) is not int or d not in range(7) for d in days):
        raise ValueError('Completá nombre, cliente y al menos un día válido.')
    with _lock:
        sellers = _read(load_config())
        old = next((s for s in sellers if s['seller'] == original), None)
        if original is not None and old is None:
            raise KeyError(original)
        if old is not None and name == old['seller']:
            pass  # Preserve existing special names, including TIMARO.
        elif (name != canonical_seller_name(name) or not normalize_key(name) or any(c in name for c in '/\\:*?"<>|') or any(ord(c)<32 for c in name)):
            raise ValueError('Nombre de seller no válido para un archivo de reporte.')
        keys = {normalize_key(canonical_seller_name(x)) for x in (name, client)}
        if '' in keys:
            raise ValueError('Nombre de cliente inválido.')
        if name != original and normalize_key(name) in {'VISITAS', 'SAMEDAY EN RUTA', 'TODOS'}:
            raise ValueError('Ese nombre está reservado por SmartPost.')
        for s in sellers:
            if s is old:
                continue
            other = {normalize_key(canonical_seller_name(x)) for x in [s['seller'], s.get('expected_empresa', ''), *(s.get('aliases') or [])] if x}
            if keys & other:
                raise ValueError('El seller o cliente coincide con otro seller configurado.')
        entry = deepcopy(old) if old is not None else {'enabled': True, 'aliases': [], 'whatsapp_group': '', 'date_mode': 'single_day'}
        if old is None or client != (old.get('expected_empresa') or old['seller']):
            entry.pop('cliente_id', None)
            entry.pop('expected_empresa_contains', None)
            entry['aliases'] = [canonical_seller_name(client)]
            entry['expected_empresa'] = client
            entry['search_terms'] = [client]
            entry['require_exact_client'] = True
        entry.update(seller=name, report_days=sorted(set(days)))
        if old is not None:
            sellers[sellers.index(old)] = entry
        else:
            sellers.append(entry)
        _storage(sellers)
        return [_public(s) for s in sellers]


def delete_seller(name):
    with _lock:
        sellers = _read(load_config())
        if not any(s['seller'] == name for s in sellers):
            raise KeyError(name)
        sellers = [s for s in sellers if s['seller'] != name]
        _storage(sellers)
        return [_public(s) for s in sellers]
