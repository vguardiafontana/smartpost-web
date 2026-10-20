import asyncio


import json


import logging


import os


from pathlib import Path


import pytest


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_mobile_date_at_23_and_selected_date_preview(tmp_path):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page(viewport={'width': 390, 'height': 844}, timezone_id='UTC')
            await page.clock.install(time=__import__('datetime').datetime(2026, 10, 20, 2, 30, tzinfo=__import__('datetime').timezone.utc))
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            requests = []
            async def route(route):
                path = route.request.url.split('https://smartpost.test', 1)[-1]
                if path == '/':
                    await route.fulfill(body=Path('app/web/static/index.html').read_text(encoding='utf-8'), content_type='text/html')
                elif path.startswith('/static/'):
                    file = Path('app/web/static') / path.rsplit('/', 1)[-1]
                    await route.fulfill(body=file.read_bytes(), content_type='text/css' if file.suffix == '.css' else 'application/javascript')
                else:
                    data = {'authenticated': True} if path == '/api/session' else {'states': [{'id': 70, 'label': 'EN RUTA'}]}
                    if path == '/api/preview':
                        body = route.request.post_data_json; requests.append(body)
                        data = {'preview_id': 'test', 'count': 1, 'state_label': 'EN RUTA', 'selected_date': body['date'], 'rows': []}
                    await route.fulfill(body=json.dumps(data), content_type='application/json')
            await page.route('**/*', route)
            await page.goto('https://smartpost.test/')
            await page.locator('#openV2Btn').click()
            assert await page.locator('#stateDate').input_value() == '2026-10-19'
            await page.locator('#stateDate').fill('2026-10-17')
            await page.locator('#bulkInput').fill('12345')
            await page.locator('#previewBtn').click()
            await page.locator('#confirmBtn').wait_for()
            assert requests[0]['date'] == '2026-10-17'
            assert '17/10/2026' in await page.locator('#previewMeta').inner_text()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(tmp_path / 'mobile-date.png'), full_page=True)
            assert not errors
            await browser.close()
    asyncio.run(run())
