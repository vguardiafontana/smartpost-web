import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.web import visit_photos as web


@pytest.mark.parametrize('status', [200, 403, 500])
def test_filter_response_always_releases_body(status):
    response = AsyncMock()
    response.status = status
    response.ok = status == 200
    response.json.return_value = {'total': 0, 'rows': []}
    response.text.return_value = 'error'
    api = web.ReleasedResponseAPI(None, {'base_url': 'https://example.test'}, 'token', logging.getLogger())
    async def run():
        if status == 200:
            assert await api._json_response(response, 'test') == {'total': 0, 'rows': []}
        else:
            with pytest.raises(RuntimeError):
                await api._json_response(response, 'test')
        response.dispose.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize('resource,blocked', [('image', True), ('media', True), ('font', True), ('script', False), ('xhr', False), ('document', False), ('stylesheet', False)])
def test_photo_pixels_blocked_but_metadata_and_page_scripts_allowed(resource, blocked):
    route = AsyncMock()
    route.request.resource_type = resource
    asyncio.run(web.skip_heavy_resources(route))
    assert route.abort.await_count == int(blocked)
    assert route.continue_.await_count == int(not blocked)


def test_pages_are_fetched_lazily_without_holding_entire_export():
    session = SimpleNamespace(fetch_page=AsyncMock(side_effect=[
        {'total': 3, 'rows': [{'id': 1}, {'id': 2}]},
        {'total': 3, 'rows': [{'id': 3}]},
    ]))
    async def run():
        pages = web.iter_visit_pages(session, '2026-10-08')
        first, total = await anext(pages)
        assert total == 3 and len(first) == 2
        assert session.fetch_page.await_count == 1
        assert (await anext(pages))[0] == [{'id': 3}]
        assert session.fetch_page.call_args.args[1] == 2
        with pytest.raises(StopAsyncIteration): await anext(pages)
    asyncio.run(run())


@pytest.mark.parametrize('responses', [
    [{'status': 'unknown'}], [{'total': 3, 'rows': []}],
    [{'total': 3, 'rows': [{'id': 1}]}, {'total': 3, 'rows': [{'id': 1}]}],
    [{'total': 4, 'rows': [{'id': 1}, {'id': 2}]}, {'total': 4, 'rows': [{'id': 2}, {'id': 3}]}],
])
def test_paged_query_rejects_incomplete_results(responses):
    async def run():
        session = SimpleNamespace(fetch_page=AsyncMock(side_effect=responses))
        with pytest.raises(RuntimeError):
            async for _ in web.iter_visit_pages(session, '2026-10-08'): pass
    asyncio.run(run())


def test_browsers_recycled_and_closed_without_losing_rows(monkeypatch):
    session = SimpleNamespace(open=AsyncMock(), close=AsyncMock(), recycle=AsyncMock(), page=object(),
        fetch_page=AsyncMock(side_effect=[{'total': 53, 'rows': [{'id': n} for n in range(1, 51)]},
                                         {'total': 53, 'rows': [{'id': n} for n in range(51, 54)]}]))
    class Playwright:
        async def __aenter__(self): return object()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(web, 'async_playwright', Playwright)
    monkeypatch.setattr(web, 'VisitBrowser', lambda *a: session)
    monkeypatch.setattr(web, 'epresis_settings', lambda cfg: {})
    async def inspect(page, row, settings): return {'guia': str(row['id']), 'foto': 'No'}
    monkeypatch.setattr(web, 'inspect_visit', inspect)
    result = asyncio.run(web.search_visit_photos_web({}, logging.getLogger(), date='2026-10-08'))
    assert result['total'] == 53
    assert [r['guia'] for r in result['rows']] == [str(i) for i in range(1, 54)]
    assert session.recycle.await_count == 2
    session.close.assert_awaited_once()


def test_browser_closed_if_startup_or_query_fails(monkeypatch):
    session = SimpleNamespace(open=AsyncMock(side_effect=RuntimeError('login')), close=AsyncMock())
    class Playwright:
        async def __aenter__(self): return object()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(web, 'async_playwright', Playwright)
    monkeypatch.setattr(web, 'VisitBrowser', lambda *a: session)
    monkeypatch.setattr(web, 'epresis_settings', lambda cfg: {})
    with pytest.raises(RuntimeError):
        asyncio.run(web.search_visit_photos_web({}, logging.getLogger()))
    session.close.assert_awaited_once()


def test_browser_restarts_in_sequence_with_cookies_and_no_persistent_profile(monkeypatch):
    events = []
    context = AsyncMock()
    context.storage_state.return_value = {'cookies': [], 'origins': []}
    browser = AsyncMock()
    browser.new_context.return_value = context
    async def close(): events.append('closed')
    async def launch(**kwargs):
        events.append('launch')
        assert kwargs['headless'] is True
        return browser
    browser.close.side_effect = close
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    monkeypatch.setattr(web, 'ensure_authenticated', AsyncMock())
    monkeypatch.setattr(web, 'navigate_to_guide_search', AsyncMock(return_value='https://example.test/guias'))
    monkeypatch.setattr(web, 'extract_csrf_token', AsyncMock(return_value='csrf'))
    async def run():
        session = web.VisitBrowser(playwright, {'base_url': 'https://example.test'}, logging.getLogger())
        await session.open()
        await session.recycle()
        assert events == ['launch', 'closed', 'launch']
        assert browser.new_context.call_args.kwargs['storage_state'] == {'cookies': [], 'origins': []}
        assert browser.new_context.call_args.kwargs['service_workers'] == 'block'
        await session.close()
    asyncio.run(run())
