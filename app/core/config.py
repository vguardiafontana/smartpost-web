from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any
import shutil

import yaml

from .runtime_paths import bundle_root, data_root, ensure_data_dirs, resource_path

PROJECT_ROOT = bundle_root()
CONFIG_PATH = data_root() / "config.yaml"
DEFAULT_CONFIG_PATH = resource_path("config.default.yaml")


class ConfigError(RuntimeError):
    pass


def ensure_user_config() -> Path:
    ensure_data_dirs()
    if not CONFIG_PATH.exists():
        if not DEFAULT_CONFIG_PATH.exists():
            raise ConfigError(f"No existe la configuración base: {DEFAULT_CONFIG_PATH}")
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    return CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = ensure_user_config()
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Forward-compatible configuration migration. New application versions may
    # introduce sections/keys (for example VISITAS) while an installed user
    # already has %APPDATA%\SmartPost\config.yaml from an older release. Merge
    # missing defaults without overwriting any user customization.
    if DEFAULT_CONFIG_PATH.exists():
        with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
            defaults = _parse_defaults(f.read())
        merged = _deep_merge(defaults, cfg)
        if merged != cfg:
            cfg = merged
            with path.open("w", encoding="utf-8", newline="\n") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=120)
    validate_config(cfg)
    return cfg


@lru_cache(maxsize=1)
def _parse_defaults(contents: str):
    # Sólo evita volver a interpretar el mismo recurso. El archivo se lee en
    # cada llamada: cambios incluso con igual fecha/tamaño se detectan. La
    # configuración del usuario nunca se cachea y _deep_merge copia defaults.
    return yaml.safe_load(contents) or {}


def _deep_merge(defaults: Any, current: Any) -> Any:
    """Return defaults filled with current values, preserving user settings.

    Dictionaries are merged recursively. Lists are intentionally treated as an
    atomic value: sellers/state lists already present in the user's config must
    not be duplicated or reordered during an upgrade.
    """
    if isinstance(defaults, dict) and isinstance(current, dict):
        out = deepcopy(defaults)
        for key, value in current.items():
            if key in out:
                out[key] = _deep_merge(out[key], value)
            else:
                out[key] = deepcopy(value)
        return out
    return deepcopy(current)


def save_config(cfg: dict[str, Any]) -> None:
    validate_config(cfg)
    path = ensure_user_config()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=120)


def resolve_path(cfg: dict[str, Any], key: str) -> Path:
    value = cfg.get("paths", {}).get(key)
    if not value:
        raise ConfigError(f"Falta paths.{key} en configuración")
    p = Path(str(value))
    if p.is_absolute():
        return p
    # Bundled, read-only resources stay next to the application image.
    if key in {"prompt", "template"}:
        return resource_path(p)
    # All mutable state lives under the current user's APPDATA.
    return (data_root() / p).resolve()


def seller_configs(cfg: dict[str, Any], enabled_only: bool = True) -> list[dict[str, Any]]:
    sellers = list(cfg.get("sellers") or [])
    if enabled_only:
        sellers = [s for s in sellers if s.get("enabled", True)]
    return sellers


def report_seller_configs(cfg: dict[str, Any], selected_date, enabled_only: bool = True) -> list[dict[str, Any]]:
    """Sellers que deben participar del lote de Reportes para la fecha elegida.

    La regla de sábado depende exclusivamente de la fecha seleccionada por el
    usuario en el calendario. VISITAS no usa esta función y por lo tanto no se
    ve afectado por este filtro.
    """
    sellers = seller_configs(cfg, enabled_only=enabled_only)
    try:
        is_saturday = int(selected_date.weekday()) == 5
    except Exception:
        is_saturday = False
    if not is_saturday:
        return sellers

    configured = (cfg.get("reportes") or {}).get("saturday_sellers") or [
        "ZETABURGOS",
        "GIANGIU",
        "G-COMMERCE",
        "PINTURERIAS MM / TIMARO",
        "TECNONUBEL",
        "CLASS",
        "PINTURERIA MILCOLORES",
    ]
    allowed = {str(name).strip() for name in configured if str(name).strip()}
    return [s for s in sellers if str(s.get("seller", "")).strip() in allowed]


def seller_map(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(s["seller"]): s for s in seller_configs(cfg, enabled_only=False)}


def build_alias_map(cfg: dict[str, Any], normalize_key) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in seller_configs(cfg, enabled_only=False):
        canonical = str(s["seller"])
        for alias in [canonical, s.get("expected_empresa", ""), *(s.get("aliases") or [])]:
            if alias:
                out[normalize_key(alias)] = canonical
    return out


def legacy_report_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "safety": deepcopy(cfg.get("reportes", {}).get("safety", {})),
        "performance": deepcopy(cfg.get("whatsapp", {}).get("performance", {})),
        "whatsapp": {
            "browser": cfg.get("whatsapp", {}).get("browser", "chromium"),
            "profile_dir": str(resolve_path(cfg, "whatsapp_profile")),
            "attachment_caption": cfg.get("whatsapp", {}).get(
                "attachment_caption", "Buenas noches, adjunto el reporte del día {date}."
            ),
        },
    }


def epresis_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    e = deepcopy(cfg.get("epresis") or {})
    e["guias_url"] = e.pop("guides_url", e.get("guias_url", ""))
    e["browser_profile_dir"] = str(resolve_path(cfg, "epresis_profile"))
    return e


def validate_config(cfg: dict[str, Any]) -> None:
    for section in ("app", "paths", "epresis", "reportes", "visitas", "cambio_estado", "denuncias", "whatsapp", "sellers"):
        if section not in cfg:
            raise ConfigError(f"Falta la sección '{section}' en configuración")


    denuncias = cfg.get("denuncias") or {}
    if denuncias.get("enabled", True):
        if not str(denuncias.get("whatsapp_group", "")).strip():
            raise ConfigError("Denuncias está habilitado pero no tiene grupo general de WhatsApp")
        if "{remito}" not in str(denuncias.get("seller_message_singular", "")):
            raise ConfigError("El mensaje singular de Denuncias debe incluir {remito}")
        if "{remitos}" not in str(denuncias.get("seller_message_plural", "")):
            raise ConfigError("El mensaje plural de Denuncias debe incluir {remitos}")
        seen_den = set()
        for item in denuncias.get("seller_groups") or []:
            name = str(item.get("seller", "")).strip()
            group = str(item.get("whatsapp_group", "")).strip()
            if not name or not group:
                raise ConfigError("Hay un grupo adicional de Denuncias incompleto")
            key = name.casefold()
            if key in seen_den:
                raise ConfigError(f"Seller duplicado en grupos de Denuncias: {name}")
            seen_den.add(key)

    visits = cfg.get("visitas") or {}
    if visits.get("enabled", True):
        states = visits.get("estados") or []
        if not states:
            raise ConfigError("Visitas está habilitado pero no tiene estados configurados")
        seen_state_ids = set()
        for item in states:
            try:
                sid = int(item.get("id"))
            except Exception as exc:
                raise ConfigError(f"ID de estado de Visitas inválido: {item!r}") from exc
            if sid in seen_state_ids:
                raise ConfigError(f"Estado de Visitas duplicado: {sid}")
            seen_state_ids.add(sid)
    sellers = cfg.get("sellers") or []
    if not sellers:
        raise ConfigError("La configuración no contiene sellers")
    seen = set()
    for item in sellers:
        name = str(item.get("seller", "")).strip()
        if not name:
            raise ConfigError("Hay un seller sin nombre")
        if name in seen:
            raise ConfigError(f"Seller duplicado: {name}")
        seen.add(name)
        mode = str(item.get("date_mode", "single_day"))
        if mode not in {"single_day", "month_to_selected"}:
            raise ConfigError(f"date_mode inválido para {name}: {mode}")
