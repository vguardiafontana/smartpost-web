from app.procesamiento.rules import normalize_row, normalize_service, remito_as_string


def test_47_is_flex():
    service, unknown = normalize_service("47812345678", "Same day")
    assert service == "FLEX"
    assert unknown is False


def test_alphanumeric_generic_flex_is_sameday():
    service, unknown = normalize_service("01M0CY933K8GKGF0KJZFQJ3AEG", "FLEX")
    assert service == "SAMEDAY"
    assert unknown is False


def test_minus_01_removed():
    row, flags = normalize_row({"Remito": "47812345678-01"})
    assert row is None


def test_long_guia_agente_is_text():
    row, _ = normalize_row({"Remito": "123", "Guia Agente": "2000015047288863", "Servicio": "FLEX"})
    assert row["Guia Agente"] == "2000015047288863"


def test_peso_volumetrico_preserves_comma():
    row, _ = normalize_row({"Remito": "123", "Peso Volumetrico": "24,84375", "Servicio": "FLEX"})
    assert row["Peso Volumetrico"] == "24,84375"


def test_hash_remito_preserved():
    row, _ = normalize_row({"Remito": "#32063-Q", "Servicio": "24-48"})
    assert remito_as_string(row["Remito"]) == "#32063-Q"
