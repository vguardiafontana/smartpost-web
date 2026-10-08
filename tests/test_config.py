from app.core.config import build_alias_map, load_config, seller_map
from app.core.utils import sha256_file
from app.core.config import resolve_path
from app.procesamiento.rules import normalize_key


def test_config_has_14_sellers_and_known_ids():
    cfg = load_config()
    sm = seller_map(cfg)
    assert len([s for s in sm.values() if s.get("enabled", True)]) == 14
    assert sm["GIANGIU"]["cliente_id"] == 122
    assert sm["APOLLO"]["cliente_id"] == 88
    assert sm["APOLLO"]["date_mode"] == "month_to_selected"


def test_aliases_cover_real_company_names():
    cfg = load_config()
    aliases = build_alias_map(cfg, normalize_key)
    assert aliases[normalize_key("ONYX MEDIA S.A")] == "ENOTEK"
    assert aliases[normalize_key("PRIMER ROUND SRL")] == "JAGUAR"
    assert aliases[normalize_key("LUPATINI Y CIA SA - PINTURERIA SAN ANTONIO")] == "PINTURERIAS SAN ANTONIO"


def test_asset_hashes_match_config():
    cfg = load_config()
    assert sha256_file(resolve_path(cfg, "prompt")) == cfg["app"]["prompt_sha256"]
    assert sha256_file(resolve_path(cfg, "template")) == cfg["app"]["template_sha256"]
