"""Configuración local exclusiva de Reportes Desktop (no altera otros módulos)."""
from copy import deepcopy
from datetime import date

from app.core.config import load_config, save_config, report_seller_configs
from app.procesamiento.rules import canonical_seller_name, normalize_key

KEY = 'desktop_report_seller_overrides'


def _records(cfg):
    overrides = cfg.get(KEY) or []
    by_base = {o['base']: o for o in overrides if o['base'] is not None}
    for base in cfg.get('sellers', []):
        override = by_base.get(base['seller'])
        if override and override.get('removed'):
            continue
        entry = deepcopy(base)
        if override:
            entry.update(deepcopy(override['changes']))
            # A deleted client ID/contains must not survive the overlay.
            for key in override.get('unset', []):
                entry.pop(key, None)
        yield entry, override, base
    for override in overrides:
        if override['base'] is None and not override.get('removed'):
            yield deepcopy(override['changes']), override, None


def apply_desktop_sellers(cfg):
    return {**cfg, 'sellers': [entry for entry, _, _ in _records(cfg)]}


def list_sellers(cfg=None):
    cfg = load_config() if cfg is None else cfg
    effective = apply_desktop_sellers(cfg)
    saturday = {s['seller'] for s in report_seller_configs(effective, date(2026, 10, 3), enabled_only=False)}
    return [{'seller': s['seller'], 'client': s.get('expected_empresa') or s['seller'],
             'days': sorted(s.get('report_days', [0, 1, 2, 3, 4, 6] + ([5] if s['seller'] in saturday else []))),
             'group': s.get('whatsapp_group', ''), 'enabled': s.get('enabled', True)}
            for s in effective['sellers']]


def update_seller(original, name, client, days, group, enabled=True):
    name, client, group = name.strip().upper(), client.strip(), group.strip()
    if not name or not client or not days or any(type(d) is not int or d not in range(7) for d in days):
        raise ValueError('Completá nombre, cliente y al menos un día válido.')
    cfg = load_config()
    records = list(_records(cfg))
    record = next((r for r in records if r[0]['seller'] == original), None)
    if original is not None and record is None:
        raise KeyError(original)
    old, override, base = record or (None, None, None)
    if old is None or name != old['seller']:
        if (name != canonical_seller_name(name) or not normalize_key(name) or any(c in name for c in '/\\:*?"<>|')
                or any(ord(c) < 32 for c in name) or normalize_key(name) in {'VISITAS', 'SAMEDAY EN RUTA', 'TODOS'}):
            raise ValueError('Nombre de seller inválido o reservado.')
    keys = {normalize_key(canonical_seller_name(x)) for x in (name, client)}
    if '' in keys:
        raise ValueError('Nombre de cliente inválido.')
    for other, _, _ in records:
        if other is old:
            continue
        other_keys = {normalize_key(canonical_seller_name(x)) for x in [other['seller'], other.get('expected_empresa', ''), *(other.get('aliases') or [])] if x}
        if keys & other_keys:
            raise ValueError('El seller o cliente coincide con otro seller configurado.')
    entry = deepcopy(old) if old is not None else {'enabled': True, 'aliases': [], 'whatsapp_group': '', 'date_mode': 'single_day'}
    if old is None or client != (old.get('expected_empresa') or old['seller']):
        entry.pop('cliente_id', None)
        entry.pop('expected_empresa_contains', None)
        entry.update(aliases=[canonical_seller_name(client)], expected_empresa=client, search_terms=[client], require_exact_client=True)
    elif name != old['seller']:
        entry['aliases'] = list(dict.fromkeys([*(entry.get('aliases') or []), old['seller']]))
    entry.update(seller=name, report_days=sorted(set(days)), whatsapp_group=group, enabled=bool(enabled))
    overrides = cfg.setdefault(KEY, [])
    replacement = {'base': base['seller'] if base else None,
                   'changes': {k: v for k, v in entry.items() if base is None or k not in base or v != base[k]},
                   'unset': [k for k in (base or {}) if k not in entry]}
    if override is not None:
        overrides[overrides.index(override)] = replacement
    else:
        overrides.append(replacement)
    save_config(cfg)


def delete_seller(name):
    cfg = load_config()
    record = next((r for r in _records(cfg) if r[0]['seller'] == name), None)
    if record is None:
        raise KeyError(name)
    _, override, base = record
    overrides = cfg.setdefault(KEY, [])
    if override is not None:
        overrides.remove(override)
    if base is not None:
        overrides.append({'base': base['seller'], 'changes': {}, 'removed': True})
    save_config(cfg)
