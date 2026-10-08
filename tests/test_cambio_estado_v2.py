from app.cambio_estado_v2.service import _route_payload, _rendition_list_payload, _find_rows


def test_route_payload_uses_pc_date_and_distributor():
    p = _route_payload("csrf", "1114", "06/10/2026")
    assert p["distribuidor_id"] == "1114"
    assert p["fecha_recorrido"] == "06/10/2026 - 06/10/2026"
    assert p["sort"] == "id"
    assert p["order"] == "desc"
    assert p["cerrada"] == "TODAS"
    assert p["guias_pendientes"] == "TODAS"


def test_rendition_list_payload_targets_planilla():
    p = _rendition_list_payload("csrf", 98130)
    assert p["planilla"] == "98130"
    assert p["limit"] == "1000"
    assert p["estado"] == ""


def test_find_rows_accepts_array_and_rows_wrapper():
    assert _find_rows([{"retiro_id": 1}]) == [{"retiro_id": 1}]
    assert _find_rows({"rows": [{"retiro_id": 2}]}) == [{"retiro_id": 2}]

from app.cambio_estado_v2.service import _row_distributor_hint


def test_row_distributor_hint_reads_nested_distributor_object():
    row = {
        "id": 6249087,
        "distribuidor": {
            "id": 2510,
            "dni": "45573374",
            "apellido": "DELGADO - FLOTA SUR FLEX",
            "nombre": "ALEJANDRO JAVIER",
        },
    }
    hint = _row_distributor_hint(row)
    assert hint["id"] == "2510"
    assert hint["dni"] == "45573374"
    assert "DELGADO" in hint["name"]


def test_row_distributor_hint_reads_text_distributor():
    row = {
        "id": 6249087,
        "datos_envios": {
            "distribuidor_nombre": "45573374 - DELGADO - FLOTA SUR FLEX, ALEJANDRO JAVIER"
        },
    }
    hint = _row_distributor_hint(row)
    assert hint["dni"] == "45573374"
    assert hint["name"] == "DELGADO - FLOTA SUR FLEX, ALEJANDRO JAVIER"


def test_row_distributor_hint_reads_explicit_distributor_id():
    row = {"retiro_id": 6249087, "distribuidor_id": 2510, "dni_distribuidor": "45573374"}
    hint = _row_distributor_hint(row)
    assert hint["id"] == "2510"
    assert hint["dni"] == "45573374"

from app.cambio_estado_v2.service import _route_from_rendition_error, _confirm_payload


def test_route_from_rendition_error_extracts_actual_route():
    data = {
        "status": "error",
        "message": "La guía: 6249087 está en el recorrido: 98149 y debe cerrarlo para continuar",
    }
    assert _route_from_rendition_error(data) == 98149


def test_route_from_rendition_error_returns_none_for_unrelated_error():
    assert _route_from_rendition_error({"status": "error", "message": "Otro error"}) is None


def test_confirm_payload_builds_single_or_massive_selection():
    p = _confirm_payload("csrf", 98149, [6249087, 6249253], 70, 248, "06/10/2026", "21:11")
    assert p["planilla_id"] == "98149"
    assert p["estado_id"] == "70"
    assert p["nro_rendicion_chofer"] == "248"
    assert p["seleccion"] == '[{"retiro_id":"6249087"},{"retiro_id":"6249253"}]'

from app.cambio_estado_v2.service import _dist_code, _dist_base_dni


def test_distributor_profile_code_preserves_suffix_and_base_dni():
    assert _dist_code("37.424.493 APP") == "37424493APP"
    assert _dist_code("37424493P") == "37424493P"
    assert _dist_base_dni("37424493APP") == "37424493"
    assert _dist_base_dni("37424493P") == "37424493"


def test_row_distributor_hint_preserves_exact_profile_code():
    row = {
        "id": 6249087,
        "datos_envios": {
            "distribuidor_nombre": "37424493APP - BALLARDINI PR APP, BELEN"
        },
    }
    hint = _row_distributor_hint(row)
    assert hint["code"] == "37424493APP"
    assert hint["dni"] == "37424493"
    assert "BALLARDINI" in hint["name"]

from app.cambio_estado_v2.service import _rendition_number_from_text


def test_rendition_number_from_open_page_header():
    assert _rendition_number_from_text("Nro de Rendicion: 248 - Usuario: valentinoguardia") == 248
    assert _rendition_number_from_text("Nro de Rendición: 247 - Usuario: prueba") == 247
    assert _rendition_number_from_text("Sin rendición activa") is None


from app.cambio_estado.states import STATE_BY_ID


def test_target_state_label_for_already_assigned_detection():
    assert STATE_BY_ID[70] == "RC - EN RUTA PARA SU ENTREGA"
    assert STATE_BY_ID[39] == "POD - ENTREGADA"
