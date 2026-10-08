from app.cambio_estado.service import extract_identifiers, _guide_info
from app.cambio_estado.states import STATES, STATE_BY_ID


def test_extract_identifiers_mixed_dirty_text_and_dedupes():
    text = "Guía 6190808 / remito: 48081585158\nAgente 2000015167962061\nrepetido 6190808"
    assert extract_identifiers(text) == ["6190808", "48081585158", "2000015167962061"]


def test_states_include_known_operational_values():
    assert STATE_BY_ID[39] == "POD - ENTREGADA"
    assert STATE_BY_ID[70] == "RC - EN RUTA PARA SU ENTREGA"
    assert STATE_BY_ID[196] == "SINI - ENVÍO SINIESTRADO"
    assert len(STATES) == len({x[0] for x in STATES})


def test_guide_info_reads_nested_epresis_shape():
    row = {
        "id": 6190808,
        "remito": "48081585158",
        "datos_envios": {"guiaAgente": "2000015167962061"},
        "cliente": {"empresa": "DBOX (NAK)"},
        "estado": {"id": 204, "nombre": "EN LA PUERTA"},
    }
    info = _guide_info(row, "48081585158", "Remito")
    assert info.retiro_id == 6190808
    assert info.guia == "6190808"
    assert info.remito == "48081585158"
    assert info.guia_agente == "2000015167962061"
    assert info.current_state_id == 204
    assert info.current_state == "EN LA PUERTA"
