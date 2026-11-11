"""Exercise the real UI and worker against a temporary, loopback-only server.

Run with a Python environment containing aiohttp, Pillow and Playwright Chromium.
Screenshots are written outside the repository; no real frame or credentials used.
"""

import asyncio
import io
import os
import socket
import sys
import tempfile
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from media import validate_bmp


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def sample_image():
    image = Image.new('RGB', (720, 960))
    draw = ImageDraw.Draw(image)
    for y in range(960):
        ratio = y / 960
        draw.line((0, y, 720, y), fill=(int(80 + 90 * ratio), int(125 + 55 * ratio), int(180 - 30 * ratio)))
    draw.ellipse((465, 115, 605, 255), fill=(244, 216, 141))
    draw.polygon([(0, 650), (240, 330), (440, 640), (600, 400), (720, 600), (720, 960), (0, 960)], fill=(39, 69, 84))
    draw.polygon([(0, 800), (300, 590), (530, 800), (720, 700), (720, 960), (0, 960)], fill=(52, 98, 110))
    out = io.BytesIO()
    image.save(out, 'JPEG')
    return out.getvalue()


async def main():
    admin_port, device_port = free_port(), free_port()
    origin = f'http://127.0.0.1:{admin_port}'
    artifacts = Path(os.environ.get('EINK_ARTIFACTS', '/private/tmp/eink-browser-artifacts'))
    artifacts.mkdir(parents=True, exist_ok=True)
    errors = []
    with tempfile.TemporaryDirectory(prefix='eink-browser-') as data:
        process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / 'server.py'), '--dev', '--data', data,
                                    '--admin-port', str(admin_port), '--device-port', str(device_port),
                                   stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            async with aiohttp.ClientSession() as session:
                for _ in range(100):
                    try:
                        async with session.get(origin + '/api/state') as response:
                            if response.status == 200:
                                break
                    except aiohttp.ClientError:
                        pass
                    await asyncio.sleep(.1)
                else:
                    raise RuntimeError('Local development server did not start.')
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch()
                    page = await browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.goto(origin)
                    await page.get_by_text('A home for your images').wait_for()
                    await page.locator('#upload-input').set_input_files({'name': 'Blue mountain.jpg', 'mimeType': 'image/jpeg', 'buffer': sample_image()})
                    await page.get_by_role('button', name='Open Blue mountain.jpg', exact=True).wait_for()
                    await page.get_by_role('button', name='Open Blue mountain.jpg', exact=True).click()
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.get_by_role('button', name='Save as new variant').wait_for(state='visible')
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    await page.screenshot(path=str(artifacts / 'optimizer-desktop.png'), full_page=True)
                    await page.get_by_role('button', name='Save as new variant').click()
                    await page.get_by_text('Saved a new variant.', exact=False).wait_for()
                    # Exercise a second processing path and validate its actual pixel codes.
                    await page.locator('#fit').select_option('cover')
                    await page.locator('#rotation').select_option('90')
                    await page.locator('#palette').select_option('grayscale')
                    await page.locator('#dither').select_option('atkinson')
                    await page.locator('#contrast').fill('15')
                    await page.locator('#focusX').fill('80')
                    await page.locator('#variant-name').fill('Monochrome crop')
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    await page.get_by_role('button', name='Save as new variant').click()
                    await page.get_by_text('Monochrome crop', exact=True).wait_for()
                    async with session.get(origin + '/api/state') as response:
                        snapshot = await response.json()
                    monochrome = next(v for v in snapshot['variants'] if v['name'] == 'Monochrome crop')
                    async with session.get(origin + f"/api/media/variant/{monochrome['id']}/file") as response:
                        mono_data = await response.read()
                        validate_bmp(mono_data)
                        assert {n for b in mono_data[118:] for n in (b >> 4, b & 15)} <= {0, 6}
                    await page.get_by_role('button', name='Close dialog').click()
                    await page.screenshot(path=str(artifacts / 'library-desktop.png'), full_page=True)
                    await page.get_by_role('link', name='Settings', exact=True).click()
                    await page.locator('#base-url').fill(f'http://127.0.0.1:{device_port}')
                    await page.get_by_role('button', name='Save LAN base URL').click()
                    await page.get_by_text('LAN base URL saved.', exact=False).wait_for()
                    await page.get_by_role('link', name='Devices', exact=False).click()
                    await page.locator('#add-device').click()
                    await page.get_by_label('Device name').fill('Living room')
                    await page.locator('#new-device').get_by_role('button', name='Add device').click()
                    await page.get_by_role('heading', name='Living room', exact=True).wait_for()
                    await page.get_by_role('button', name='Add images', exact=False).click()
                    await page.get_by_label('Image version for Blue mountain.jpg').select_option('original')
                    await page.get_by_role('button', name='Add to device').click()
                    await page.get_by_text('Image added to the device list.').wait_for()
                    options = await page.get_by_label('Image version for Blue mountain.jpg').locator('option').evaluate_all('(items)=>items.map(o=>o.value)')
                    variant_id = next(v for v in options if v != 'original')
                    await page.get_by_label('Image version for Blue mountain.jpg').select_option(variant_id)
                    await page.get_by_role('button', name='Added · add again').click()
                    await page.get_by_role('button', name='Close dialog').click()
                    await page.get_by_label('Name', exact=True).fill('Studio frame')
                    await page.get_by_label('Update interval (seconds)').fill('120')
                    await page.get_by_role('button', name='Save settings', exact=True).click()
                    await page.get_by_role('heading', name='Studio frame', exact=True).wait_for()
                    url = await page.locator('#image-url').input_value()
                    async with session.get(url) as response:
                        assert response.content_type == 'image/jpeg'
                        assert await response.read() == sample_image()
                    await page.get_by_role('button', name='Next image', exact=True).click()
                    await page.get_by_text('Selection updated.', exact=False).wait_for()
                    assert await page.locator('#image-url').input_value() == url
                    async with session.get(url) as response:
                        assert response.content_type == 'image/bmp'
                        validate_bmp(await response.read())
                    await page.get_by_role('button', name='Refresh status').click()
                    await page.screenshot(path=str(artifacts / 'device-desktop.png'), full_page=True)
                    for width in (390, 720):
                        await page.set_viewport_size({'width': width, 'height': 844})
                        await page.screenshot(path=str(artifacts / f'device-{width}.png'), full_page=True)
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Horizontal overflow at {width}px'
                    await page.get_by_role('link', name='Media Library', exact=False).click()
                    await page.screenshot(path=str(artifacts / 'library-mobile.png'), full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    await browser.close()
            print('Browser smoke passed: upload, full-resolution optimization, variant persistence, device setup/settings, original/BMP delivery at one fixed URL, and responsive layouts.')
            print(f'Screenshots: {artifacts}')
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except TimeoutError:
                process.kill()
                await process.wait()
            log = (await process.stderr.read()).decode()
            if process.returncode not in (0, -15):
                print(log, file=sys.stderr)


if __name__ == '__main__':
    asyncio.run(main())
