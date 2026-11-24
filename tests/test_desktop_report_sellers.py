from copy import deepcopy
from datetime import date
from pathlib import Path
import yaml
import pytest
from app.core.config import report_seller_configs, build_alias_map
from app.core.dates import seller_date_range
from app.procesamiento.rules import normalize_key, resolve_seller_from_rows
from app.reportes import desktop_sellers as mod

@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / 'config.yaml'
    path.write_text((Path(__file__).resolve().parents[1] / 'config.default.yaml').read_text(encoding='utf-8'), encoding='utf-8')
    def load(): return yaml.safe_load(path.read_text(encoding='utf-8'))
    def save(cfg): path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    monkeypatch.setattr(mod, 'load_config', load)
    monkeypatch.setattr(mod, 'save_config', save)
    return load


def names(cfg, day):
    return {s['seller'] for s in report_seller_configs(cfg, day)}


def test_existing_config_unchanged(config):
    original = config()
    assert mod.apply_desktop_sellers(original) == original
    for d in range(3, 10):
        day = date(2026, 10, d)
        assert names(original, day) == names(mod.apply_desktop_sellers(original), day)
    assert next(s for s in mod.list_sellers() if s['seller'] == 'CLASS')['days'] == list(range(7))


def test_add_edit_delete_persist_scope(config):
    original = deepcopy(config()['sellers'])
    mod.update_seller(None, 'Nuevo', 'Cliente Nuevo SRL', [5, 1], 'Grupo Nuevo')
    current = mod.apply_desktop_sellers(config())
    assert 'NUEVO' in names(current, date(2026, 10, 3))
    assert 'NUEVO' not in names(current, date(2026, 10, 5))
    assert 'NUEVO' in names(current, date(2026, 10, 6))
    new = next(s for s in current['sellers'] if s['seller'] == 'NUEVO')
    assert new['whatsapp_group'] == 'Grupo Nuevo' and new['require_exact_client']
    assert resolve_seller_from_rows([{'Cliente': 'Cliente Nuevo SRL'}], build_alias_map(current, normalize_key))[0] == 'NUEVO'
    mod.update_seller('NUEVO', 'Nuevo Dos', 'Otro cliente SA', [0], 'Grupo Dos')
    current = mod.apply_desktop_sellers(config())
    assert 'NUEVO DOS' in names(current, date(2026, 10, 5))
    assert 'NUEVO DOS' not in names(current, date(2026, 10, 3))
    mod.delete_seller('NUEVO DOS'); mod.delete_seller('CLASS')
    assert 'CLASS' not in names(mod.apply_desktop_sellers(config()), date(2026, 10, 3))
    assert config()['sellers'] == original


def test_special_rules_and_group_settings_preserved(config):
    old = next(s for s in config()['sellers'] if s['seller']=='APOLLO')
    mod.update_seller('APOLLO', 'APOLLO', old['expected_empresa'], [0,5], old['whatsapp_group'])
    entry = next(s for s in mod.apply_desktop_sellers(config())['sellers'] if s['seller']=='APOLLO')
    assert {k:v for k,v in entry.items() if k!='report_days'} == old
    assert seller_date_range(entry, date(2026,10,5)) == '01/10/2026 - 05/10/2026'
    cfg = config(); next(s for s in cfg['sellers'] if s['seller']=='APOLLO')['whatsapp_group'] = 'Desde Configuración'; mod.save_config(cfg)
    assert next(s for s in mod.list_sellers() if s['seller']=='APOLLO')['group'] == 'Desde Configuración'
    mod.update_seller('APOLLO', 'APOLLO', 'Otro cliente exacto', [0], 'Grupo')
    entry = next(s for s in mod.apply_desktop_sellers(config())['sellers'] if s['seller']=='APOLLO')
    assert 'cliente_id' not in entry and 'expected_empresa_contains' not in entry
    assert entry['search_terms'] == ['Otro cliente exacto'] and entry['require_exact_client']
    assert entry['date_mode'] == 'month_to_selected'


def test_validation_and_disable(config):
    for name,client,days in [('CLASS','Otro',[1]),('Otro','APOLLO SRL',[1]),('Otro','Cliente',[]),('../otro','Cliente',[1]),('Otro','Cliente',[7])]:
        with pytest.raises(ValueError): mod.update_seller(None,name,client,days,'Grupo')
    old = next(s for s in mod.list_sellers() if s['seller']=='CLASS')
    mod.update_seller('CLASS','CLASS',old['client'],[5],old['group'],False)
    assert 'CLASS' not in names(mod.apply_desktop_sellers(config()), date(2026,10,3))
    with pytest.raises(KeyError): mod.delete_seller('NO EXISTE')


def test_desktop_dialog_smoke(config, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from app.gui.report_sellers_dialog import ReportSellersDialog, SellerEditor
    app = QApplication.instance() or QApplication([])
    dialog = ReportSellersDialog()
    assert dialog.table.rowCount() == len(config()['sellers'])
    editor = SellerEditor(parent=dialog)
    editor.name.setText('NUEVO'); editor.client.setText('Cliente Nuevo SRL'); editor.group.setText('Grupo')
    editor.days[5].setChecked(True); editor._save(); dialog._reload()
    assert dialog.table.rowCount() == len(config()['sellers']) + 1
    dialog.close()
