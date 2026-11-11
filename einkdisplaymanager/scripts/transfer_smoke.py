"""Verify live UI during a real, deliberately stalled local HTTP image response."""

import asyncio
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from aiohttp import ClientError, web
from aiohttp.test_utils import TestClient, TestServer
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media import placeholder
from server import Manager


async def main():
    artifacts = Path(os.environ.get('EINK_ARTIFACTS', '/private/tmp/eink-browser-artifacts'))
    artifacts.mkdir(parents=True, exist_ok=True)
    original_write = web.StreamResponse.write
    started, release = asyncio.Event(), asyncio.Event()
    image_responses = set()
    phase = {'mode':'hold'}

    async def controlled_write(response, chunk):
        if chunk.startswith(b'BM'):
            image_responses.add(response)
        elif response in image_responses:
            if phase['mode'] == 'hold':
                started.set()
                await release.wait()
            elif phase['mode'] == 'disconnect':
                raise ConnectionResetError('Synthetic frame disconnect; never log raw error text')
        return await original_write(response, chunk)

    with tempfile.TemporaryDirectory(prefix='eink-transfer-') as root:
        manager = Manager(root, dev=True)
        admin_app, frames_app = manager.apps()
        try:
            async with TestClient(TestServer(admin_app)) as admin, TestClient(TestServer(frames_app)) as frames:
                snapshot = await (await admin.get('/api/state')).json()
                admin.session.headers['X-Eink-CSRF'] = snapshot['csrf']
                await admin.put('/api/settings', json={'base_url':str(frames.make_url('/')).rstrip('/')})
                upload = await (await admin.post('/api/assets',data=placeholder(),headers={'X-File-Name':'Test frame.bmp'})).json()
                device = await (await admin.post('/api/devices',json={'name':'Transfer test frame'})).json()
                device_id = device['id']
                device = await (await admin.put('/api/devices/'+device_id,json={'entries':[
                    {'asset_id':upload['id'],'mode':'original','enabled':True}]})).json()
                image_path = '/d/'+device_id+'/image?k='+manager.store.get('device',device_id)['token']

                async def download():
                    response = await frames.get(image_path)
                    return await response.read()

                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page(viewport={'width':1440,'height':1050})
                    await page.goto(str(admin.make_url('/'))+'#devices/'+device_id)
                    await page.get_by_role('heading',name='Transfer test frame',exact=True).wait_for()
                    await page.get_by_label('Name',exact=True).fill('Unsaved draft name')
                    web.StreamResponse.write = controlled_write
                    transfer = asyncio.create_task(download())
                    try:
                        await asyncio.wait_for(started.wait(),timeout=3)
                        await page.locator('[data-transfer-state="sending"]').wait_for(timeout=10000)
                        assert await page.locator('#next').is_disabled()
                        assert await page.locator('progress[aria-label="Image bytes written by server"]').get_attribute('value') == '65536'
                        assert await page.get_by_label('Name',exact=True).input_value() == 'Unsaved draft name'
                        await page.locator('#transfer-status').scroll_into_view_if_needed()
                        await page.screenshot(path=str(artifacts/'transfer-running.png'),full_page=True)
                    finally:
                        phase['mode'] = 'normal'
                        release.set()
                        assert await transfer == placeholder()
                    await page.locator('[data-transfer-state="completed"]').wait_for(timeout=10000)
                    assert not await page.locator('#next').is_disabled()
                    assert await page.get_by_label('Name',exact=True).input_value() == 'Unsaved draft name'

                    phase['mode'] = 'disconnect'
                    with suppress(ClientError,ConnectionError):
                        await download()
                    await page.locator('[data-transfer-state="interrupted"]').wait_for(timeout=10000)
                    await page.get_by_text('Error category: connection_closed',exact=True).wait_for()
                    assert 'image_interrupted' in await page.locator('#device-events').inner_text()
                    await page.screenshot(path=str(artifacts/'transfer-interrupted.png'),full_page=True)
                    phase['mode'] = 'normal'
                    assert await download() == placeholder()
                    await page.locator('[data-transfer-state="completed"]').wait_for(timeout=10000)
                    assert 'image_completed' in await page.locator('#device-events').inner_text()
                    assert await page.get_by_label('Name',exact=True).input_value() == 'Unsaved draft name'
                    await page.set_viewport_size({'width':390,'height':844})
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    await page.screenshot(path=str(artifacts/'device-log-mobile.png'),full_page=True)
                    await browser.close()
        finally:
            web.StreamResponse.write = original_write
            manager.store.close()
    print('Live transfer UI passed: real stalled HTTP response, byte progress, protected actions, interruption/retry events, preserved form draft, and mobile layout.')


if __name__ == '__main__':
    asyncio.run(main())
