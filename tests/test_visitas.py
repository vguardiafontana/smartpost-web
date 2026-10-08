from pathlib import Path

import yaml

from app.descarga.epresis_api import EpresisAPI


class DummyRequest:
    pass


def make_api():
    return EpresisAPI(
        DummyRequest(),
        {
            "base_url": "https://example.test",
            "request_timeout_ms": 30000,
            "max_concurrent_requests": 1,
        },
        "csrf-demo",
        logger=type("L", (), {"warning": lambda *a, **k: None})(),
    )


def test_visits_payload_has_repeated_state_ids_and_no_client():
    api = make_api()
    pairs = api.make_visits_payload("21/09/2026", [127, 119, 183], export=True)
    assert ("cliente_id", "") in pairs
    assert ("fecha_ingreso_planta", "21/09/2026 - 21/09/2026") in pairs
    assert [value for key, value in pairs if key == "estados_id[]"] == ["127", "119", "183"]
    assert ("is_estado", "1") in pairs
    assert ("type", "xls") in pairs


def test_visits_filter_payload_has_grid_fields():
    api = make_api()
    pairs = api.make_visits_payload("19/09/2026", [48, 51], export=False)
    payload = dict(pairs)
    assert payload["sort"] == "id"
    assert payload["order"] == "desc"
    assert payload["limit"] == "10"
    assert payload["offset"] == "0"


def test_default_visits_config_is_file_only_to_night_group():
    cfg = yaml.safe_load(Path("config.default.yaml").read_text(encoding="utf-8"))
    visits = cfg["visitas"]
    assert visits["enabled"] is True
    assert visits["whatsapp_group"] == "CONSULTAS / Operación nocturna"
    assert visits["whatsapp_message"] == ""
    assert [x["id"] for x in visits["estados"]] == [127, 119, 183, 48, 51, 117, 63]


def test_progress_payload_can_have_its_own_status_field():
    # Regression test for v2.1.0: the stage emitter used `status` as both
    # positional argument and payload keyword, causing TypeError before
    # WhatsApp in successful/no-data VISITAS flows.
    received = []

    def progress(stage, stage_status, payload):
        received.append((stage, stage_status, payload))

    def emit(stage: str, stage_status: str, **payload):
        progress(stage, stage_status, payload)

    emit("visitas", "ok", status="generated", rows=5)
    assert received == [("visitas", "ok", {"status": "generated", "rows": 5})]
