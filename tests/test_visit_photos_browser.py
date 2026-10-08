"""Prueba opcional de navegador, sin conectarse a Epresis.

SMARTPOST_TEST_BROWSER debe apuntar al ejecutable Chromium local.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.visitas.fotos import photo_from_guide_page


@pytest.mark.skipif(not os.environ.get('SMARTPOST_TEST_BROWSER'), reason='Chromium local no configurado')
def test_photo_evidence_and_mobile_yes_no_controls():
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ['SMARTPOST_TEST_BROWSER'], headless=True)
            page = await browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            fixtures = [
                ('<div>Fotos<button>Cargar foto</button><a href="#">Ver fotos</a><input type="file"></div>', False),
                ('<img alt="logo" src="/logo.png"><img alt="Foto perfil" src="/avatar.jpg">', False),
                ('<div class="card">Fotos<img src="/evidencias/123.jpg"></div>', True),
                ('<a data-fancybox="gallery" href="/storage/abc.png">Abrir</a>', True),
                ('<div class="card">Fotos<img src="/images/no-image.png"></div>', False),
            ]
            for html, expected in fixtures:
                await page.set_content(html)
                assert await photo_from_guide_page(page) is expected
            static = Path('app/web/static')
            job = {'id': 'local', 'status': 'completed', 'date': '2026-10-08', 'message': 'Consulta terminada.', 'rows': [
                {'guia': '10001', 'foto': 'Sí', 'estado': '1° VISITA'},
                {'guia': '6255448', 'guia_agente': '2000018857041302', 'remito': '48200354755', 'cliente': 'PINTURERIAS MM TIMARO S.R.L', 'servicio': 'FLEX', 'destinatario': 'Quiroga tatiana', 'domicilio': 'Sargento Cabral 1398', 'localidad': 'Wilde', 'provincia': 'Buenos Aires', 'codigo_postal': '1875', 'telefono': '', 'foto': 'No', 'estado': '1RVT - 1° VISITA', 'distribuidor_raw': '47013362P - ERCILA MORALES PR PM, LUIS ALBERTO'},
                {'guia': '10003', 'foto': 'Sin verificar', 'estado': '3° VISITA'},
            ]}
            polls = 0
            async def route(request):
                nonlocal polls
                path = request.request.url.split('https://smartpost.test', 1)[-1]
                if path == '/api/visit-photo-jobs/local':
                    polls += 1
                    if polls == 1:
                        await request.fulfill(status=502, body='Bad Gateway');return
                if path == '/':
                    await request.fulfill(body=(static/'index.html').read_text(encoding='utf-8'), content_type='text/html')
                elif path.startswith('/static/'):
                    file = static/path.rsplit('/', 1)[-1]
                    mime = 'text/css' if file.suffix == '.css' else 'application/javascript'
                    await request.fulfill(body=file.read_bytes(), content_type=mime)
                else:
                    data = {'authenticated': True} if path == '/api/session' else {'states': []} if path == '/api/states' else job
                    await request.fulfill(body=json.dumps(data), content_type='application/json')
            await page.route('**/*', route)
            await page.goto('https://smartpost.test/')
            await page.locator('#openVisitPhotosBtn').click()
            await page.locator('#queryVisitPhotos').click()
            await page.locator('#visitPhotosRows tbody tr').wait_for()
            assert await page.locator('#visitPhotosRows tbody tr td:first-child').all_text_contents() == ['6255448']
            expected='6255448\t2000018857041302\t48200354755\tPINTURERIAS MM TIMARO S.R.L\tFLEX\tQuiroga tatiana\tSargento Cabral 1398\tWilde\tBuenos Aires\t1875\t—\tNo\t1RVT - 1° VISITA\t47013362P - ERCILA MORALES PR PM, LUIS ALBERTO'
            assert '\t'.join((await page.locator('#visitPhotosRows tbody tr td').all_text_contents())[:14]) == expected
            assert await page.evaluate('(row)=>guideTSV([row])', job['rows'][1]) == expected
            await page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}})")
            await page.locator('#visitPhotosRows [data-guide-action="copy"]').click()
            assert await page.evaluate('window.copied') == expected
            await page.locator('#visitPhotoYes').click()
            assert await page.locator('#visitPhotosRows tbody tr td:first-child').all_text_contents() == ['10001']
            await page.locator('#visitPhotoNo').click()
            assert await page.locator('#visitPhotosRows tbody tr td:first-child').all_text_contents() == ['6255448']
            assert '1 guías sin verificar' in await page.locator('#visitPhotosUnknownTitle').inner_text()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path='.test-mobile-visitas.png', full_page=True)
            # Paginación visual: todas accesibles, sin miles de nodos simultáneos.
            await page.evaluate("renderGuideTable('visitPhotosRows',Array.from({length:205},(_,i)=>({guia:String(10000+i),foto:'No'})))")
            assert await page.locator('#visitPhotosRows tbody tr').count() == 100
            await page.locator('#visitPhotosRows [data-guide-action="next"]').click()
            await page.locator('#visitPhotosRows [data-guide-action="next"]').click()
            assert await page.locator('#visitPhotosRows tbody tr').count() == 5
            assert await page.locator('#visitPhotosRows tbody tr td:first-child').first.inner_text() == '10200'
            await page.evaluate("renderGuideTable('visitPhotosRows',[{guia:'<img src=x onerror=alert(1)>',foto:'No'}])")
            assert await page.locator('#visitPhotosRows img').count() == 0
            assert errors == []
            assert polls >= 2
            await browser.close()
    asyncio.run(run())
