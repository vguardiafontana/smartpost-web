from app.busqueda_guias.service import _details_from_row, _parse_distributor_text


def test_bulk_search_extracts_requested_fields():
    row = {
        "id": 6190808,
        "remito": "48081585158",
        "servicio_id": 10,
        "distribuidor": "28775644P - GOMEZ PR PM, DANIEL NERI",
        "cliente": {"empresa": "DBOX (NAK)"},
        "datos_envios": {"guiaAgente": "2000015167962061"},
        "comprador": {
            "apellido_nombre": "Daiana Sanchez",
            "calle": "Alejandro Magariños Cervantes",
            "altura": 5452,
            "localidad": "Villa Luro",
            "provincia": "Capital Federal",
            "cp": 1407,
            "celular": "1112345678",
        },
        "estado": {"codigo": "ATD", "nombre": "EN LA PUERTA", "id": 204},
    }
    d = _details_from_row(row, "6190808")
    assert d["guia"] == "6190808"
    assert d["remito"] == "48081585158"
    assert d["guia_agente"] == "2000015167962061"
    assert d["cliente"] == "DBOX (NAK)"
    assert d["destinatario"] == "Daiana Sanchez"
    assert d["domicilio"] == "Alejandro Magariños Cervantes 5452"
    assert d["localidad"] == "Villa Luro"
    assert d["provincia"] == "Capital Federal"
    assert d["codigo_postal"] == "1407"
    assert d["telefono"] == "1112345678"
    assert d["estado"] == "ATD - EN LA PUERTA"


def test_distributor_text_extracts_dni_and_name():
    dni, name = _parse_distributor_text("28775644P - GOMEZ PR PM, DANIEL NERI")
    assert dni == "28775644"
    assert name == "GOMEZ PR PM, DANIEL NERI"


def test_bulk_search_handles_flat_filter_aliases_and_flex():
    row = {
        "id": 6193469,
        "rto_cliente": "48085271827",
        "guiaAgente": "2000015175564933",
        "cliente_nombre": "TECNONUBEL - MARCELO FABIAN MAUCERI",
        "canal": "Mflex",
        "nombre_comprador": "roque adrian ferreira",
        "calle": "Albert Schweitzer",
        "altura": "1230",
        "localidad": "Ejemplo",
        "provincia": "Buenos Aires",
        "cp_comprador": "1704",
        "celular": "1122334455",
        "estado_nombre": "EN RUTA PARA SU ENTREGA",
        "estado_codigo": "RC",
    }
    d = _details_from_row(row, "6193469")
    assert d["remito"] == "48085271827"
    assert d["guia_agente"] == "2000015175564933"
    assert d["cliente"] == "TECNONUBEL - MARCELO FABIAN MAUCERI"
    assert d["servicio"] == "FLEX"
    assert d["destinatario"] == "roque adrian ferreira"
    assert d["domicilio"] == "Albert Schweitzer 1230"


def test_distributor_html_row_extracts_phone_and_cellular():
    from app.busqueda_guias.service import _distributor_from_html_row, _extract_distributor_phone
    html = '''<tr data-index="0" data-uniqueid="2397"><td>2397</td><td>45823637P</td><td><img src="x"></td><td>FERNANDO MARTIN</td><td>SUAREZ PR PM</td><td>45823637</td><td>09/16/2004</td><td>SMARTPOST</td><td>CABA</td><td>-</td><td>1130029545</td><td>1130029545</td><td>MAIL@EXAMPLE.COM</td></tr>'''
    row = _distributor_from_html_row(html)
    assert row["dni"] == "45823637"
    assert row["nombre"] == "FERNANDO MARTIN"
    assert row["apellido"] == "SUAREZ PR PM"
    assert row["telefono"] == "1130029545"
    assert row["celular"] == "1130029545"
    assert _extract_distributor_phone(html) == "1130029545"


def test_distributor_html_row_uses_cellular_when_phone_empty():
    from app.busqueda_guias.service import _distributor_from_html_row, _extract_distributor_phone
    html = '''<tr><td>2397</td><td>45823637P</td><td></td><td>FERNANDO</td><td>SUAREZ</td><td>45823637</td><td></td><td>SMARTPOST</td><td>CABA</td><td>-</td><td></td><td>1166667777</td><td></td></tr>'''
    row = _distributor_from_html_row(html)
    assert row["telefono"] == ""
    assert row["celular"] == "1166667777"
    assert _extract_distributor_phone(html) == "1166667777"


def test_distributor_excel_values_uses_codigo_and_phone():
    from app.busqueda_guias.service import _distributor_from_excel_values
    headers = ["nombre", "apellido", "telefono", "celular", "codigo"]
    row = ["FERNANDO MARTIN", "SUAREZ PR PM", 1130029545, 1130029545, "45823637P"]
    item = _distributor_from_excel_values(headers, row)
    assert item["dni"] == "45823637"
    assert item["phone"] == "1130029545"
    assert item["name"] == "FERNANDO MARTIN SUAREZ PR PM"


def test_distributor_excel_values_falls_back_to_cellular():
    from app.busqueda_guias.service import _distributor_from_excel_values
    headers = ["codigo", "telefono", "celular", "nombre", "apellido"]
    row = ["28775644P", None, 1166677788, "DANIEL NERI", "GOMEZ PR PM"]
    item = _distributor_from_excel_values(headers, row)
    assert item["dni"] == "28775644"
    assert item["phone"] == "1166677788"


def test_distributor_id_from_show_url():
    from app.busqueda_guias.service import _distributor_id_from_url
    assert _distributor_id_from_url('https://smartpostecommerce.epresis.com/distribuidores/show/1374') == '1374'
    assert _distributor_id_from_url('/distribuidores/show/2397?x=1') == '2397'
    assert _distributor_id_from_url('/distribuidores/distribuidoresEditar/2397') == ''
