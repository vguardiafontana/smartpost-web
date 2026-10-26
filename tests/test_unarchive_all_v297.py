import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.delivery import chat_archive
from app.delivery import unarchive_all as service


def test_explicit_unarchive_only_calls_archived_flow(monkeypatch):
    page = SimpleNamespace(is_closed=lambda: False)
    context = SimpleNamespace(pages=[page])
    monkeypatch.setattr(chat_archive, '_open_home', AsyncMock())
    monkeypatch.setattr(chat_archive, '_find_archived_entry', AsyncMock(side_effect=AssertionError('legacy toggle must not run')))
    monkeypatch.setattr(chat_archive, '_archive_from_company_list', AsyncMock(side_effect=AssertionError('must not archive')))
    action = AsyncMock(return_value={'mode': 'unarchive', 'count': 3, 'list': 'Archivados'})
    monkeypatch.setattr(service, 'unarchive_all', action)
    result = asyncio.run(chat_archive._toggle_once(context, {'whatsapp': {'company_chat_list': 'OTHER'}}, logging.getLogger('test'), mode='unarchive'))
    assert result['count'] == 3
    action.assert_awaited_once_with(page, logging.getLogger('test'))


def test_all_chats_are_processed_beyond_previous_250_limit(monkeypatch):
    remaining = list(range(261)); completed = []
    pane = SimpleNamespace(is_visible=AsyncMock(return_value=True)); page = object()
    monkeypatch.setattr(service, '_enter_archived', AsyncMock(return_value=pane))
    monkeypatch.setattr(service, '_archived_pane', AsyncMock(return_value=pane))
    monkeypatch.setattr(service, '_scroll_top', AsyncMock(return_value=False))
    async def rows(*args): return remaining[:1]
    async def identity(row): return str(row)
    async def action(page, row):
        assert row == remaining[0]
        completed.append(remaining.pop(0))
    monkeypatch.setattr(service, '_ready_rows', rows)
    monkeypatch.setattr(service, '_row_identity', identity)
    monkeypatch.setattr(service, '_unarchive_row', action)
    monkeypatch.setattr(service, '_removed', AsyncMock(return_value=True))
    result = asyncio.run(service.unarchive_all(page, logging.getLogger('test')))
    assert result['count'] == 261
    assert completed == list(range(261))


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
@pytest.mark.parametrize('pane_kind,action_kind', [('drawer', 'quick'), ('header', 'menu'), ('drawer', 'lazy')])
def test_drain_archived_list_without_touching_normal_chats(pane_kind, action_kind):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.route('**/*', lambda route: route.abort())
            root = 'data-testid="archived-drawer"' if pane_kind == 'drawer' else 'id="archived-panel"'
            html = '''<style>[role=row]{height:60px;width:320px}#drawer{width:350px}</style>
            <div id="app"><div id="pane-side"><button onclick="openArchived()">Archivados <span>3</span></button>
              <button onclick="window.wrong=true">Smart Post</button><div role="row" data-id="normal"><span title="Normal">Normal</span></div></div>
            <div id="drawer" style="display:none"><div ROOT><header><button aria-label="Volver">←</button><h1>Archivados</h1></header>
              <div role="grid" id="rows"></div><p id="empty" hidden>No hay chats archivados</p></div></div>
            <div id="main"><header><button aria-label="Menú" onclick="window.wrong=true">Menú conversación</button></header></div></div>
            <div id="menu" role="menu" hidden><button role="menuitem" onclick="removeChat(window.current);this.parentElement.hidden=true">Desarchivar chat</button></div>
            <script>
            window.left=[1,2,3];window.done=[];window.wrong=false;window.opens=0;window.mode='MODE';
            function render(){document.getElementById('rows').innerHTML=window.left.slice(0,window.mode==='lazy'?1:3).map(id=>
              `<div role="row" data-id="a${id}"><span title="Seller ${id}">Seller ${id}</span>`+
              (window.mode==='menu'?`<button aria-label="Menú" onclick="event.stopPropagation();window.current=${id};document.getElementById('menu').hidden=false">⋮</button>`:
                `<button aria-label="Desarchivar chat" onclick="event.stopPropagation();removeChat(${id})"><svg width="20" height="20"><title>ic-unarchive</title><rect width="20" height="20"/></svg></button>`)+`</div>`).join('');
              document.getElementById('empty').hidden=window.left.length!==0;}
            function openArchived(){window.opens++;document.getElementById('drawer').style.display='block';render()}
            function removeChat(id){window.done.push(id);window.left=window.left.filter(x=>x!==id);
              if(window.mode==='lazy'){document.getElementById('rows').innerHTML='';setTimeout(render,180)}else render()}
            </script>'''.replace('ROOT', root).replace('MODE', action_kind)
            await page.set_content(html)
            result = await service.unarchive_all(page, logging.getLogger('test'))
            assert result['count'] == 3
            assert await page.evaluate('window.done') == [1, 2, 3]
            assert await page.evaluate('window.opens') == 1
            assert await page.evaluate('window.wrong') is False
            assert await page.locator('#pane-side [data-id="normal"]').count() == 1
            assert await page.locator('#rows [role="row"]').count() == 0
            assert (await service.unarchive_all(page, logging.getLogger('test')))['count'] == 0
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_unknown_rows_are_not_reported_as_an_empty_archive():
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.set_content('<div data-testid="archived-chats"><div style="height:60px"><span title="Unrecognized chat">Unrecognized chat</span></div></div>')
            with pytest.raises(RuntimeError, match='Hay chats visibles'):
                await service.unarchive_all(page, logging.getLogger('test'))
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_bulk_snapshot_does_not_read_each_chat_separately():
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.set_content('<div data-testid="archived-chats">'+''.join(f'<div role="row" data-id="{i}" style="height:60px"><span title="{i}">{i}</span></div>' for i in range(40))+'</div>')
            calls = []
            class Counter:
                def __init__(self, locator): self.locator_obj = locator
                def locator(self, selector): return Counter(self.locator_obj.locator(selector))
                def nth(self, index): return self.locator_obj.nth(index)
                async def evaluate_all(self, *args):
                    calls.append('read'); return await self.locator_obj.evaluate_all(*args)
            rows = await service._rows(Counter(page.locator('[data-testid="archived-chats"]')))
            assert len(rows) == 40
            assert len(calls) == 2  # independent of the forty visible chats
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_no_effect_click_does_not_report_success(monkeypatch):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.set_content('<div data-testid="archived-chats"><div role="row" data-id="same" style="height:60px"><span title="Same">Same</span><button aria-label="Desarchivar chat" onclick="window.clicks=(window.clicks||0)+1">Desarchivar</button></div></div>')
            monkeypatch.setattr(service, '_removed', AsyncMock(return_value=False))
            with pytest.raises(RuntimeError, match='sigue en Archivados'):
                await service.unarchive_all(page, logging.getLogger('test'))
            assert await page.evaluate('window.clicks') == 2
            assert await page.locator('[data-id="same"]').count() == 1
            await browser.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_virtual_list_starts_at_top_even_when_scrollbar_is_outside_grid():
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page()
            await page.set_content('''<div id="scroll" style="height:130px;overflow-y:auto" onscroll="render()"><div role="grid" aria-label="Archivados" id="grid"></div></div>
              <script>
              window.left=[1,2,3,4];window.done=[];
              function render(){let visible=document.getElementById('scroll').scrollTop>0?window.left.filter(i=>i>=3):window.left.slice(0,2);
                document.getElementById('grid').innerHTML=visible.map(id=>`<div role="row" data-id="${id}" style="height:60px"><span title="${id}">${id}</span><button aria-label="Desarchivar chat" onclick="window.done.push(${id});window.left=window.left.filter(i=>i!==${id});render()">Desarchivar</button></div>`).join('')+
                  (window.left.length?'<div style="height:1000px"></div>':'<p>No hay chats archivados</p>');}
              render();document.getElementById('scroll').scrollTop=300;render();
              </script>''')
            result = await service.unarchive_all(page, logging.getLogger('test'))
            assert result['count'] == 4
            assert await page.evaluate('window.done') == [1,2,3,4]
            await browser.close()
    asyncio.run(run())
