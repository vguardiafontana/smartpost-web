import random

from app.denuncias.messages import seller_message
from app.denuncias.narratives import ShipmentLine, generate_unknown_circumstances
from app.denuncias.input_parser import parse_identifiers, query_field_order


def test_seller_message_singular():
    msg = seller_message(
        ["48038316651"],
        "uno {remito}",
        "varios {remitos}",
    )
    assert msg == "uno 48038316651"


def test_seller_message_plural():
    msg = seller_message(
        ["48038316651", "48038316685"],
        "uno {remito}",
        "varios:\n{remitos}",
    )
    assert "Remito 48038316651" in msg
    assert "Remito 48038316685" in msg


def test_unknown_narrative_contains_only_supplied_shipment_data():
    items = [ShipmentLine("GIANGIU", "47712345678", "2000011111111111")]
    text = generate_unknown_circumstances(items, random.Random(1))
    assert "GIANGIU" in text
    assert "47712345678" in text
    assert "2000011111111111" not in text
    assert "47712345678 - Seller: GIANGIU" in text
    assert "arma de fuego" in text.lower()
    assert any(word in text.lower() for word in ("amenaz", "intimid"))


def test_parse_identifiers_accepts_mixed_text_and_deduplicates():
    text = "Guía 6171234\nRemito: 48038316651\nGuía Agente 2000017817513284\n6171234"
    assert parse_identifiers(text) == ["6171234", "48038316651", "2000017817513284"]


def test_query_order_is_only_a_priority_not_a_hard_rule():
    assert query_field_order("6171234")[0] == "nroGuia"
    assert query_field_order("48038316651")[0] == "rto_cliente"
    assert query_field_order("2000017817513284")[0] == "guia_agente"
    assert set(query_field_order("7777777")) == {"nroGuia", "rto_cliente", "guia_agente"}


def test_narrative_package_line_format_requested():
    items = [ShipmentLine("ENVIO PACK", "48049277663", "2000017817513284")]
    text = generate_unknown_circumstances(items, random.Random(2))
    assert "48049277663 - Seller: ENVIO PACK" in text
    assert "Numero de venta" not in text
