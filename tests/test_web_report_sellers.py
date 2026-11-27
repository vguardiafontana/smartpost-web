from datetime import date
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
import yaml
from app.core.config import report_seller_configs, build_alias_map
from app.core.dates import seller_date_range
from app.procesamiento.rules import normalize_key, resolve_seller_from_rows
from app.web import report_sellers as mod
from app.descarga.epresis_api import EpresisAPI

@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1]/'config.default.yaml').read_text(encoding='utf-8'))
    monkeypatch.setattr(mod, 'load_config', lambda: cfg)
    monkeypatch.setattr(mod, 'data_root', lambda: tmp_path)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    return cfg


def names(cfg, day):
    return {s['seller'] for s in report_seller_configs(cfg, day)}


def test_existing_rules_preserved(config):
    new = mod.apply_report_sellers(config)
    for day in range(3, 10):
        d = date(2026, 10, day)
        assert names(new,d) == names(config,d)
    apollo = next(s for s in new['sellers'] if s['seller']=='APOLLO')
    assert seller_date_range(apollo,date(2026,10,5)) == '01/10/2026 - 05/10/2026'
    original = next(s for s in config['sellers'] if s['seller']=='APOLLO')
    assert {k:v for k,v in apollo.items() if k != 'report_days'} == original


def test_add_edit_delete_and_persistence(config):
    mod.update_seller(None,'Nuevo','Cliente Nuevo SRL',[5,1])
    new = mod.apply_report_sellers(config)
    assert 'NUEVO' in names(new,date(2026,10,3))
    assert 'NUEVO' not in names(new,date(2026,10,5))
    assert 'NUEVO' in names(new,date(2026,10,6))
    assert resolve_seller_from_rows([{'Cliente':'Cliente Nuevo SRL'}],build_alias_map(new,normalize_key))[0]=='NUEVO'
    mod.update_seller('NUEVO','Nuevo','Otro cliente SA',[0])
    new=mod.apply_report_sellers(config)
    assert 'NUEVO' not in names(new,date(2026,10,3))
    assert 'NUEVO' in names(new,date(2026,10,5))
    assert next(s for s in new['sellers'] if s['seller']=='NUEVO')['search_terms']==['Otro cliente SA']
    mod.delete_seller('NUEVO')
    mod.delete_seller('CLASS')
    assert 'CLASS' not in names(mod.apply_report_sellers(config),date(2026,10,3))
    assert 'CLASS' in names(config,date(2026,10,3))


def test_edit_existing_preserves_special_fields(config):
    old = next(s for s in config['sellers'] if s['seller']=='APOLLO')
    mod.update_seller('APOLLO','APOLLO',old['expected_empresa'],[0,5])
    entry = next(s for s in mod.apply_report_sellers(config)['sellers'] if s['seller']=='APOLLO')
    assert entry['cliente_id']==old['cliente_id']
    assert entry['date_mode']=='month_to_selected'
    assert entry['aliases']==old['aliases']
    assert 'APOLLO' in names(mod.apply_report_sellers(config),date(2026,10,3))


def test_validation(config):
    for name,client,days in [('CLASS','Otro',[1]),('Otro','APOLLO SRL',[1]),('Otro','Cliente',[]),('../otro','Cliente',[1]),('Otro','Cliente',[7])]:
        with pytest.raises(ValueError): mod.update_seller(None,name,client,days)
    with pytest.raises(KeyError): mod.delete_seller('NO EXISTE')


def test_exact_resolution_for_new_sellers(config):
    mod.update_seller(None,'Nuevo','Cliente Nuevo SRL',[0])
    entry=next(s for s in mod.apply_report_sellers(config)['sellers'] if s['seller']=='NUEVO')
    api=object.__new__(EpresisAPI)
    api.search_clients=AsyncMock(return_value=[{'id':111,'empresa':'Otro cliente'}])
    with pytest.raises(RuntimeError): asyncio.run(api.resolve_client(entry,{}))
    api.search_clients=AsyncMock(return_value=[{'id':222,'empresa':'Cliente Nuevo SRL'}])
    assert asyncio.run(api.resolve_client(entry,{}))==(222,'Cliente Nuevo SRL')


def test_seller_endpoints_require_session_and_persist(config):
    import threading
    from fastapi.testclient import TestClient
    from app.web.server import create_app
    from app.web.security import WebSecuritySettings
    class Manager:
        operation_lock=threading.Lock()
        def start(self): pass
        def stop(self): pass
    app=create_app(security=WebSecuritySettings(pin='246810',session_secret='x'*64),manager=Manager(),report_manager=Manager(),visit_photo_manager=Manager())
    body={'seller':'NUEVO','client':'Cliente Nuevo SRL','days':[5]}
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/api/report-sellers').status_code==401
        assert client.post('/api/report-sellers',json=body).status_code==401
        assert client.post('/api/report-sellers/delete',json={'seller':'CLASS'}).status_code==401
        assert client.post('/api/auth/login',json={'pin':'246810'}).status_code==200
        assert len(client.get('/api/report-sellers').json()['sellers'])==len(config['sellers'])
        assert client.post('/api/report-sellers',json=body).status_code==200
        assert client.post('/api/report-sellers',json=body).status_code==400
        assert any(s['seller']=='NUEVO' for s in client.get('/api/report-sellers').json()['sellers'])
        assert client.post('/api/report-sellers/delete',json={'seller':'NUEVO'}).status_code==200
        assert not any(s['seller']=='NUEVO' for s in client.get('/api/report-sellers').json()['sellers'])
