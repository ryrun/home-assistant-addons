"""Exercise the real UI and worker against a temporary, loopback-only server.

Run with a Python environment containing aiohttp, Pillow and Playwright Chromium.
Screenshots are written outside the repository; no real frame or credentials used.
"""

import asyncio
import base64
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import aiohttp
from PIL import Image, ImageChops, ImageDraw
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from correction import rotate_delivery
from media import validate_bmp, validate_variant


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
                    gallery = await page.locator('#gallery').element_handle()
                    await page.clock.install()
                    await page.clock.fast_forward(16000)
                    assert await gallery.evaluate('(node)=>node.isConnected'), 'Polling rebuilt the library'
                    await page.clock.resume()
                    await page.get_by_role('button', name='Open Blue mountain.jpg', exact=True).click()
                    # A worker load failure must be visible above the native modal,
                    # restore controls, and permit a fresh attempt.
                    starts = 0
                    async def refuse_optimizer(route):
                        nonlocal starts
                        starts += 1
                        await route.fulfill(status=503, content_type='text/javascript', body='')
                    await page.route('**/static/optimizer.js', refuse_optimizer)
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.locator('#preview-note').filter(has_text='Its browser module could not load').wait_for()
                    assert starts == 2, 'Startup failure was not retried once'
                    assert not await page.locator('#optimize').is_disabled()
                    assert await page.locator('#save-variant').is_disabled()
                    assert await page.locator('#notice').evaluate('(node)=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
                    await page.screenshot(path=str(artifacts / 'optimizer-start-error.png'),full_page=True)
                    await page.unroute('**/static/optimizer.js', refuse_optimizer)
                    starts = 0
                    async def transient_optimizer_failure(route):
                        nonlocal starts
                        starts += 1
                        if starts == 1:
                            await route.fulfill(status=503,content_type='text/javascript',body='')
                        else:
                            await route.continue_()
                    await page.route('**/static/optimizer.js', transient_optimizer_failure)
                    assert await page.locator('#palette').input_value() == 'spectra6'
                    await page.locator('#intent').select_option('vivid')
                    preview_box = await page.locator('.preview-stage').bounding_box()
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.get_by_role('button', name='Save as new variant').wait_for(state='visible')
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    assert starts == 2, 'A transient startup failure did not recover'
                    await page.unroute('**/static/optimizer.js', transient_optimizer_failure)
                    invalid = await page.evaluate('''async ()=>{const {optimizeImage}=await import('./static/optimizer-client.js');try{await optimizeImage({source:new Blob(['invalid image'],{type:'image/png'}),recipe:{},signal:new AbortController().signal});return 'unexpected success';}catch(error){return error.message;}}''')
                    assert 'decoding the source image' in invalid
                    assert 'Automatic applied' in await page.locator('#automatic-summary').inner_text()
                    assert 'vivid' in await page.locator('#automatic-summary').inner_text()
                    updated_box = await page.locator('.preview-stage').bounding_box()
                    assert preview_box['height'] == updated_box['height'] and preview_box['width'] == updated_box['width']
                    await page.set_viewport_size({'width': 1440, 'height': 750})
                    await page.locator('.dialog-body').evaluate('(node)=>{node.scrollTop=150;}')
                    await page.wait_for_timeout(100)
                    assert await page.locator('.dialog-body').evaluate('(node)=>node.scrollTop') > 0
                    await page.locator('.dialog-body').evaluate('(node)=>{node.scrollTop=0;}')
                    await page.set_viewport_size({'width': 1440, 'height': 1100})
                    await page.screenshot(path=str(artifacts / 'optimizer-desktop.png'), full_page=True)
                    await page.get_by_role('button', name='Save as new variant').click()
                    await page.get_by_text('Saved a new variant.', exact=False).wait_for()
                    async def stall_optimizer(route):
                        await route.fulfill(content_type='text/javascript',body="self.onmessage=()=>{};self.postMessage({ready:true});")
                    await page.route('**/static/optimizer.js',stall_optimizer)
                    await page.get_by_role('button',name='Update full-resolution preview').click()
                    await page.locator('#preview-note').filter(has_text='Starting optimizer').wait_for()
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.unroute('**/static/optimizer.js',stall_optimizer)
                    await page.get_by_role('button',name='Open Blue mountain.jpg',exact=True).click()
                    assert not await page.locator('#optimize').is_disabled()
                    assert not await page.locator('#notice').evaluate('(node)=>node.classList.contains("error")&&!node.hidden')
                    # Exercise a second processing path and validate its actual pixel codes.
                    await page.locator('#orientation').select_option('landscape')
                    await page.locator('#fit').select_option('cover')
                    await page.locator('#rotation').select_option('90')
                    await page.locator('#palette').select_option('grayscale')
                    await page.locator('#dither').select_option('atkinson')
                    await page.locator('#contrast').fill('15')
                    await page.locator('#focusX').fill('80')
                    await page.locator('#variant-name').fill('Monochrome crop')
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    assert await page.locator('#image-preview').evaluate('(img)=>[img.naturalWidth,img.naturalHeight]') == [1600, 1200]
                    preview_bytes = base64.b64decode(await page.locator('#image-preview').evaluate('(img)=>{const canvas=document.createElement("canvas");canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;canvas.getContext("2d").drawImage(img,0,0);return canvas.toDataURL("image/png").split(",")[1];}'))
                    await page.screenshot(path=str(artifacts / 'optimizer-landscape.png'), full_page=True)
                    await page.get_by_role('button', name='Save as new variant').click()
                    await page.get_by_text('Monochrome crop', exact=True).wait_for()
                    async with session.get(origin + '/api/state') as response:
                        snapshot = await response.json()
                    monochrome = next(v for v in snapshot['variants'] if v['name'] == 'Monochrome crop')
                    async with session.get(origin + f"/api/media/variant/{monochrome['id']}/file") as response:
                        mono_data = await response.read()
                        validate_bmp(mono_data)
                        assert {n for b in mono_data[118:] for n in (b >> 4, b & 15)} <= {0, 6}
                        native = Image.open(io.BytesIO(mono_data)).convert('RGB').transpose(Image.Transpose.ROTATE_270)
                        preview = Image.open(io.BytesIO(preview_bytes)).convert('RGB')
                        assert ImageChops.difference(native, preview).getbbox() is None, 'Landscape preview differs from transmitted pixels'
                    await page.locator(f'[data-edit-variant="{monochrome["id"]}"]').click()
                    assert await page.locator('#orientation').input_value() == 'landscape'
                    assert await page.locator('#rotation').input_value() == '90'
                    assert await page.locator('#contrast').input_value() == '15'
                    assert await page.locator('#focusX').input_value() == '80'
                    assert await page.locator('#dither').input_value() == 'atkinson'
                    assert await page.get_by_role('button', name='About dithering methods').count() == 0
                    assert 'predictable baseline' in await page.locator('#matching-tip').inner_text()
                    await page.locator('#dither').select_option('stucki')
                    await page.locator('#palette').select_option('spectra6')
                    await page.locator('#matching').select_option('lab')
                    assert 'human perception' in await page.locator('#matching-tip').inner_text()
                    assert 'photographic gradients' in await page.locator('#dither-tip').inner_text()
                    await page.get_by_role('button', name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    await page.get_by_role('button', name='Save changes', exact=True).click()
                    await page.locator('#notice').filter(has_text='Variant updated.').wait_for()
                    assert await page.locator('#notice').evaluate('(node)=>node.parentElement===document.querySelector("#editor")')
                    assert await page.locator('#notice').evaluate('(node)=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
                    async with session.get(origin + '/api/state') as response:
                        snapshot = await response.json()
                    revision = next(v for v in snapshot['variants'] if v['id'] == monochrome['id'])
                    assert revision['recipe']['palette'] == 'spectra6' and revision['recipe']['dither'] == 'stucki'
                    assert revision['revision'] == 1 and revision['name'] == monochrome['name']
                    assert len(snapshot['variants']) == 2
                    # Check the actual full-resolution BMPs, not just the checkbox.
                    comparison = await page.evaluate('''async (asset)=>{
                      const {optimizeImage}=await import('./static/optimizer-client.js');
                      const source=await (await fetch(`api/media/asset/${asset}/source`)).blob();
                      const baseline={profile:'openpaper_l',orientation:'portrait',fit:'contain',rotation:0,palette:'spectra6',intent:'vivid',matching:'rgb',brightness:0,contrast:0,saturation:0,dither:'floyd'};
                      const convert=async(automatic,contrast=0)=>{const data=await optimizeImage({source,recipe:{...baseline,automatic,contrast},signal:new AbortController().signal});return {hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data.bmp))).join(','),analysis:data.recipe.automaticAnalysis,options:data.recipe.resolvedOptions};};
                      return {off:await convert(false),on:await convert(true),manual:await convert(true,15)};
                    }''', snapshot['assets'][0]['id'])
                    assert comparison['off']['hash'] != comparison['on']['hash'], 'Automatic optimization did not affect delivered pixels'
                    assert comparison['on']['analysis']['enabled'] and not comparison['off']['analysis']['enabled']
                    assert comparison['on']['analysis']['intent'] == 'vivid'
                    assert comparison['on']['options']['toneMapping']['saturation'] == comparison['manual']['options']['toneMapping']['saturation']
                    assert comparison['manual']['options']['toneMapping']['contrast'] == .15
                    assert not any(key.isdigit() for key in comparison['on']['options'])
                    (artifacts / 'automatic-comparison.json').write_text(json.dumps(comparison,indent=2))
                    # Exercise each new worker algorithm without publishing extra variants.
                    output_hashes = []
                    for algorithm in ('floyd', 'jarvis', 'burkes', 'sierra3', 'ordered', 'blueNoise', 'none'):
                        result = await page.evaluate('''async ({asset, algorithm})=>{
                          const source=await (await fetch(`api/media/asset/${asset}/source`)).blob();
                          const worker=new Worker(new URL('static/optimizer.js',location.href),{type:'module'});
                          const data=await new Promise((resolve,reject)=>{worker.onmessage=e=>{if(e.data.ready||e.data.progress)return;e.data.error?reject(new Error(e.data.error)):resolve(e.data);};worker.onerror=e=>reject(new Error(e.message));worker.postMessage({source,recipe:{profile:'openpaper_l',orientation:'portrait',fit:'contain',rotation:0,palette:'spectra6',matching:'rgb',automatic:false,brightness:0,contrast:0,saturation:0,dither:algorithm}});});
                          worker.terminate();const pixels=new Uint8Array(data.bmp), view=new DataView(data.bmp);
                          if(pixels.length!==960118||view.getInt32(18,true)!==1200||view.getInt32(22,true)!==-1600)throw new Error('Invalid native output');
                          const valid=new Set([0,1,2,3,5,6]);for(const b of pixels.subarray(118))if(!valid.has(b>>4)||!valid.has(b&15))throw new Error('Invalid palette code');
                          return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data.bmp))).join(',');
                        }''', {'asset': snapshot['assets'][0]['id'], 'algorithm': algorithm})
                        output_hashes.append(result)
                    assert len(set(output_hashes)) == len(output_hashes), 'Algorithm choices unexpectedly produced identical outputs'
                    await page.get_by_role('button', name='Close dialog').click()
                    await page.screenshot(path=str(artifacts / 'library-desktop.png'), full_page=True)
                    await page.get_by_role('link', name='Settings', exact=True).click()
                    assert await page.locator('#base-url').input_value() == 'http://homeassistant.local:8098'
                    await page.get_by_text('Editing the URL alone does not change the port mapping.', exact=False).wait_for()
                    await page.get_by_label('Broker',exact=True).fill('127.0.0.1')
                    await page.get_by_label('MQTT username',exact=True).fill('browser-test-user')
                    await page.get_by_label('MQTT password',exact=True).fill('browser-test-secret')
                    await page.get_by_label('Use TLS with certificate verification').check()
                    assert await page.get_by_label('MQTT port',exact=True).input_value() == '8883'
                    await page.get_by_label('Use TLS with certificate verification').uncheck()
                    await page.get_by_role('button',name='Save MQTT settings',exact=True).click()
                    await page.locator('#mqtt-save-status').filter(has_text='MQTT settings saved.').wait_for()
                    assert await page.get_by_label('MQTT password',exact=True).input_value() == ''
                    assert 'Saved password' in await page.get_by_label('MQTT password',exact=True).get_attribute('placeholder')
                    mqtt_data = await page.evaluate('fetch("api/mqtt").then(r=>r.json())')
                    assert mqtt_data['password_set'] and 'password' not in mqtt_data
                    assert 'browser-test-secret' not in await page.evaluate('fetch("api/state").then(r=>r.text())')
                    await page.get_by_label('MQTT username',exact=True).fill('unsaved draft')
                    await page.wait_for_timeout(5500)
                    assert await page.get_by_label('MQTT username',exact=True).input_value() == 'unsaved draft'
                    await page.reload()
                    await page.get_by_role('heading',name='MQTT & Home Assistant',exact=True).wait_for()
                    assert await page.get_by_label('MQTT username',exact=True).input_value() == 'browser-test-user'
                    await page.get_by_role('button',name='Save MQTT settings',exact=True).click()
                    await page.locator('#mqtt-save-status').filter(has_text='MQTT settings saved.').wait_for()
                    assert (await page.evaluate('fetch("api/mqtt").then(r=>r.json())'))['password_set']
                    await page.get_by_label('Clear saved MQTT password',exact=True).check()
                    await page.get_by_role('button',name='Save MQTT settings',exact=True).click()
                    await page.locator('#mqtt-save-status').filter(has_text='MQTT settings saved.').wait_for()
                    assert not (await page.evaluate('fetch("api/mqtt").then(r=>r.json())'))['password_set']
                    await page.screenshot(path=str(artifacts / 'mqtt-settings-desktop.png'),full_page=True)
                    await page.set_viewport_size({'width':390,'height':844})
                    await page.screenshot(path=str(artifacts / 'mqtt-settings-mobile.png'),full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    await page.set_viewport_size({'width':1440,'height':1100})
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
                    options = await page.get_by_label('Image version for Blue mountain.jpg').locator('option').evaluate_all('(items)=>items.map(o=>o.value)')
                    variant_id = next(v for v in options if v != 'original')
                    await page.get_by_role('button', name='Add to device').click()
                    await page.get_by_text('Image added to the device list.').wait_for()
                    assert await page.locator('[data-add-asset]').count() == 0
                    await page.get_by_text('All library images are already assigned',exact=False).wait_for()
                    await page.get_by_role('button', name='Close dialog').click()
                    # Preserve regression coverage for existing lists with repeated
                    # motifs. New picker additions hide the whole assigned asset.
                    await page.evaluate('''async variantId=>{const state=await fetch('api/state').then(r=>r.json());const d=await fetch('api/devices/'+state.devices[0].id).then(r=>r.json());const entry={asset_id:state.assets[0].id,mode:'variant',variant_id:variantId};const response=await fetch('api/devices/'+d.id,{method:'PUT',headers:{'Content-Type':'application/json','X-Eink-CSRF':state.csrf},body:JSON.stringify({entries:[...d.entries,entry],modified:d.modified})});if(!response.ok)throw new Error('Legacy duplicate fixture failed');}''',variant_id)
                    await page.locator('#refresh-device').click()
                    await page.locator('.queue [data-entry]').nth(1).wait_for()
                    await page.get_by_label('Name', exact=True).fill('Studio frame')
                    await page.get_by_label('Update interval (seconds)').fill('120')
                    await page.get_by_label('Mounting orientation').select_option('landscape')
                    await page.get_by_label('Automatic sensor rotation').check()
                    await page.get_by_label('Mounted upside down',exact=False).check()
                    assert await page.get_by_label('Automatic sensor rotation').is_disabled()
                    assert not await page.get_by_label('Automatic sensor rotation').is_checked()
                    await page.get_by_role('button', name='Save settings', exact=True).click()
                    await page.get_by_role('heading', name='Studio frame', exact=True).wait_for()
                    await page.locator('#device-save-status').filter(has_text='Settings saved. The frame will apply them on its next wake-up.').wait_for()
                    async def reject_stale_save(route):
                        if route.request.method == 'PUT':
                            await asyncio.sleep(.4)
                            await route.fulfill(status=409,content_type='application/json',body='{"error":"Refresh device before saving."}')
                        else:
                            await route.continue_()
                    await page.route('**/api/devices/*',reject_stale_save)
                    await page.get_by_role('button',name='Save settings',exact=True).click()
                    assert await page.get_by_role('button',name='Saving…',exact=True).is_disabled()
                    await page.locator('#device-save-status').filter(has_text='Refresh device before saving.').wait_for()
                    assert await page.get_by_label('Name',exact=True).input_value() == 'Studio frame'
                    assert await page.get_by_label('Automatic sensor rotation').is_disabled()
                    await page.unroute('**/api/devices/*',reject_stale_save)
                    await page.get_by_role('button',name='Save settings',exact=True).click()
                    await page.locator('#device-save-status').filter(has_text='Settings saved.').wait_for()
                    assert await page.get_by_label('Mounting orientation').input_value() == 'landscape'
                    assert await page.get_by_label('Mounted upside down',exact=False).is_checked()
                    assert await page.get_by_label('Automatic sensor rotation').is_disabled()
                    assert 'device=' in await page.locator('#device-frame-preview img').get_attribute('src')
                    await page.get_by_text('Refresh the frame and apply settings', exact=True).click()
                    await page.get_by_text('press the large reset button twice', exact=False).wait_for()
                    await page.get_by_text('Refresh the frame and apply settings', exact=True).click()
                    url = await page.locator('#image-url').input_value()
                    settings_url = await page.locator('#settings-url').input_value()
                    # Simulate the official HTTPS flasher origin with browser LNA
                    # permission granted, without contacting its hosted service.
                    flasher = await browser.new_page()
                    await flasher.context.grant_permissions(['local-network-access'], origin='https://paperlesspaper.github.io')
                    await flasher.route('https://paperlesspaper.github.io/eink-test', lambda route: route.fulfill(content_type='text/html', body='<title>Flasher-origin CORS test</title>'))
                    await flasher.goto('https://paperlesspaper.github.io/eink-test')
                    fetched = await flasher.evaluate('(url)=>fetch(url,{cache:"no-store"}).then(async r=>({status:r.status,json:await r.json()}))', settings_url + '&nocache=123')
                    assert fetched['status'] == 200 and fetched['json']['downloadUrl'] == url
                    await flasher.close()
                    async with session.get(url) as response:
                        assert response.content_type == 'image/jpeg'
                        assert await response.read() == rotate_delivery(sample_image(), 'image/jpeg')
                    await page.locator('#device-battery-estimate').filter(has_text='100%').wait_for()
                    await page.get_by_role('button', name='Next image', exact=True).click()
                    await page.get_by_text('Selection updated.', exact=False).wait_for()
                    assert await page.locator('#image-url').input_value() == url
                    async with session.get(url) as response:
                        assert response.content_type == 'image/bmp'
                        validate_bmp(await response.read())
                    await page.get_by_role('button', name='Refresh status').click()
                    await page.locator('.device-cover img').wait_for()
                    await page.locator('.device-cover img').evaluate('(img)=>img.decode()')
                    assert await page.locator('.device-cover img').evaluate('(img)=>img.naturalWidth>img.naturalHeight')
                    await page.screenshot(path=str(artifacts / 'device-desktop.png'), full_page=True)
                    for width in (390, 720):
                        await page.set_viewport_size({'width': width, 'height': 844})
                        await page.screenshot(path=str(artifacts / f'device-{width}.png'), full_page=True)
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Horizontal overflow at {width}px'
                    await page.get_by_role('link', name='Media Library', exact=False).click()
                    await page.get_by_role('button', name='Open Blue mountain.jpg', exact=True).click()
                    await page.get_by_label('Image name',exact=False).fill('Mountain evening')
                    await page.get_by_role('button',name='Save name',exact=True).click()
                    await page.locator('#image-name-status').filter(has_text='Image name saved.').wait_for()
                    await page.locator('#dialog-title').filter(has_text='Mountain evening').wait_for()
                    await page.get_by_role('button', name='Close dialog').click()
                    await page.get_by_role('button', name='Open Mountain evening', exact=True).wait_for()
                    await page.reload()
                    await page.get_by_role('button', name='Open Mountain evening', exact=True).wait_for()
                    await page.screenshot(path=str(artifacts / 'library-mobile.png'), full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    # OpenPaper 7 has a landscape native raster and a separate recipe.
                    await page.set_viewport_size({'width':1440,'height':1100})
                    await page.get_by_role('link',name='Devices',exact=False).click()
                    await page.locator('#add-device').click()
                    await page.get_by_label('Device type').select_option('openpaper_7')
                    await page.get_by_label('Device name').fill('Office 7')
                    await page.locator('#new-device').get_by_role('button',name='Add device',exact=True).click()
                    await page.get_by_role('heading',name='Office 7',exact=True).wait_for()
                    assert await page.get_by_label('Mounting orientation').input_value() == 'landscape'
                    assert await page.get_by_label('Mounting orientation').locator('option:checked').inner_text() == 'Landscape · 800 × 480'
                    small_url = await page.locator('#image-url').input_value()
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    assert await page.get_by_label('Image version for Mountain evening').locator('option').count() == 1
                    await page.locator('[data-prepare-asset]').first.click()
                    assert (await page.locator('#target-profile').input_value()).startswith('device:')
                    assert '800 × 480' in await page.locator('#output-dimensions').inner_text()
                    await page.locator('#dither').select_option('stucki')
                    await page.locator('#matching').select_option('lab')
                    await page.get_by_role('button',name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    assert await page.locator('#image-preview').evaluate('(img)=>[img.naturalWidth,img.naturalHeight]') == [800,480]
                    await page.get_by_role('button',name='Save as new variant',exact=True).click()
                    await page.locator('#notice').filter(has_text='Saved a new variant.').wait_for()
                    assert await page.locator('#orientation').input_value() == 'landscape'
                    assert '800 × 480' in await page.locator('#output-dimensions').inner_text()
                    async with session.get(origin+'/api/state') as response:
                        small_state = await response.json()
                    small_device = next(d for d in small_state['devices'] if d['name']=='Office 7')
                    small_variant = next(v for v in small_state['variants'] if v['profile']=='openpaper_7')
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    versions = await page.get_by_label('Image version for Mountain evening').locator('option').evaluate_all('(items)=>items.map(o=>o.value)')
                    assert set(versions) == {'original',small_variant['id']}
                    await page.get_by_label('Image version for Mountain evening').select_option(small_variant['id'])
                    await page.get_by_role('button',name='Add to device',exact=True).click()
                    await page.get_by_role('button',name='Close dialog').click()
                    async with session.get(small_url) as response:
                        initial_small = await response.read()
                        small_etag = response.headers['ETag']
                    validate_bmp(initial_small,'openpaper_7')
                    assert len(initial_small)==192118
                    await page.get_by_label('Mounting orientation').select_option('portrait')
                    await page.get_by_label('Mounted upside down',exact=False).check()
                    await page.get_by_role('button',name='Save settings',exact=True).click()
                    await page.locator('#device-save-status').filter(has_text='Settings saved.').wait_for()
                    await page.get_by_role('link',name='Media Library',exact=False).click()
                    await page.get_by_role('button',name='Open Mountain evening',exact=True).click()
                    await page.locator(f'[data-edit-variant="{small_variant["id"]}"]').click()
                    assert await page.locator('#target-profile').input_value() == 'profile:openpaper_7'
                    assert await page.locator('#dither').input_value() == 'stucki'
                    await page.locator('#orientation').select_option('portrait')
                    await page.get_by_role('button',name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    small_preview = base64.b64decode(await page.locator('#image-preview').evaluate('(img)=>{const c=document.createElement("canvas");c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext("2d").drawImage(img,0,0);return c.toDataURL("image/png").split(",")[1];}'))
                    assert Image.open(io.BytesIO(small_preview)).size == (480,800)
                    await page.get_by_role('button',name='Save changes',exact=True).click()
                    await page.locator('#notice').filter(has_text='Variant updated.').wait_for()
                    async with session.get(origin+f"/api/media/variant/{small_variant['id']}/file") as response:
                        small_native = await response.read()
                    validate_bmp(small_native,'openpaper_7')
                    physical = Image.open(io.BytesIO(small_native)).convert('RGB').transpose(Image.Transpose.ROTATE_270)
                    assert ImageChops.difference(physical,Image.open(io.BytesIO(small_preview)).convert('RGB')).getbbox() is None
                    async with session.get(small_url,headers={'If-None-Match':small_etag}) as response:
                        assert response.status==200
                        assert await response.read()==rotate_delivery(small_native,'image/bmp')
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.goto(origin+f"/#devices/{small_device['id']}")
                    await page.get_by_role('heading',name='Office 7',exact=True).wait_for()
                    assert await page.get_by_label('Mounting orientation').input_value() == 'portrait'
                    await page.locator('#device-frame-preview img').evaluate('(img)=>img.decode()')
                    await expect(page.locator('#device-frame-preview img')).to_have_js_property('naturalWidth',384)
                    await expect(page.locator('#device-frame-preview img')).to_have_js_property('naturalHeight',640)
                    dimensions = await page.locator('#device-frame-preview img').evaluate('(img)=>[img.naturalWidth,img.naturalHeight]')
                    assert dimensions == [384,640], (dimensions,await page.get_by_label('Mounting orientation').input_value(),await page.locator('#device-frame-preview img').get_attribute('src'))
                    assert await page.locator('#image-url').input_value() == small_url
                    await page.screenshot(path=str(artifacts/'openpaper7-desktop.png'),full_page=True)
                    await page.set_viewport_size({'width':390,'height':844})
                    await page.screenshot(path=str(artifacts/'openpaper7-mobile.png'),full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    # A pre-dithered 7-inch original cannot be assigned to the L model.
                    async with session.post(origin+'/api/assets',data=small_native,headers={'X-Eink-CSRF':small_state['csrf'],'X-File-Name':'Native Seven.bmp'}) as response:
                        assert response.status==201
                        native_asset=(await response.json())['id']
                    large_device=next(d for d in small_state['devices'] if d['profile']=='openpaper_l')
                    await page.goto(origin+f"/#devices/{large_device['id']}")
                    await page.reload()  # The native-BMP fixture was uploaded through the external HTTP client.
                    await page.get_by_role('heading',name='Studio frame',exact=True).wait_for()
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    assert await page.get_by_label('Image version for Native Seven.bmp').locator('option[value="original"]').is_disabled()
                    assert await page.locator(f'[data-add-asset="{native_asset}"]').is_disabled()
                    await page.get_by_role('button',name='Close dialog').click()
                    # Inkplate: native grayscale PNG through the real worker and UI.
                    await page.goto(origin+'/#devices')
                    await page.locator('#add-device').click()
                    await page.get_by_label('Device name').fill('Inkplate desk')
                    await page.get_by_label('Device type').select_option('inkplate_6')
                    await page.locator('#new-device button.primary').click()
                    await page.get_by_role('heading',name='Inkplate desk',exact=True).wait_for()
                    assert await page.get_by_label('Wake on movement').is_disabled()
                    assert await page.get_by_label('Charge NiMH batteries over USB').is_disabled()
                    await page.get_by_text('Connect Inkplate 6 with ESPHome',exact=True).click()
                    example_url=await page.get_by_role('link',name='Download ESPHome example').get_attribute('href')
                    assert (await page.request.get(origin+'/'+example_url)).status==200
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    # A motif assigned to another model is still available here.
                    mountain_asset=next(a['id'] for a in small_state['assets'] if a['filename']=='Blue mountain.jpg')
                    await page.locator(f'[data-prepare-asset="{mountain_asset}"]').click()
                    assert (await page.locator('#target-profile').input_value()).startswith('device:')
                    assert await page.locator('#palette').input_value()=='gray8'
                    assert await page.locator('#palette option').count()==1
                    assert await page.locator('#saturation').is_hidden()
                    assert 'Eight grayscale levels' in await page.locator('#output-dimensions').inner_text()
                    await page.get_by_role('button',name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    await page.get_by_role('button',name='Save as new variant',exact=True).click()
                    await page.get_by_text('Saved a new variant.',exact=True).wait_for()
                    ink_state=await page.evaluate('fetch("api/state").then(r=>r.json())')
                    ink_variant=next(v for v in ink_state['variants'] if v['profile']=='inkplate_6')
                    async with session.get(origin+f"/api/media/variant/{ink_variant['id']}/file") as response:
                        ink_native=await response.read()
                    validate_variant(ink_native,'inkplate_6')
                    ink_image=Image.open(io.BytesIO(ink_native))
                    assert len(set(ink_image.convert('L').tobytes()))>=3
                    # A full ramp must retain all eight levels, including both endpoints.
                    ramp=await page.evaluate('''async()=>{const c=new OffscreenCanvas(600,800),ctx=c.getContext('2d');for(let x=0;x<600;x++){const v=Math.round(x*255/599);ctx.fillStyle=`rgb(${v},${v},${v})`;ctx.fillRect(x,0,1,800);}const {optimizeImage}=await import('./static/optimizer-client.js');const result=await optimizeImage({source:await c.convertToBlob(),recipe:{profile:'inkplate_6',orientation:'portrait',fit:'contain',rotation:0,palette:'gray8',dither:'none',matching:'rgb',automatic:false},signal:new AbortController().signal});const b=await createImageBitmap(result.preview),out=new OffscreenCanvas(600,800),o=out.getContext('2d');o.drawImage(b,0,0);const levels=new Set();const px=o.getImageData(0,0,600,800).data;for(let i=0;i<px.length;i+=4)levels.add(px[i]);return {mime:result.mime,levels:[...levels].sort((a,b)=>a-b),nativeWidth:result.recipe.nativeWidth,nativeHeight:result.recipe.nativeHeight};}''')
                    assert ramp=={'mime':'image/png','levels':[0,36,73,109,146,182,219,255],'nativeWidth':800,'nativeHeight':600}
                    await page.locator(f'[data-edit-variant="{ink_variant["id"]}"]').click()
                    await page.locator('#orientation').select_option('portrait')
                    await page.get_by_role('button',name='Update full-resolution preview').click()
                    await page.locator('#save-variant:not([disabled])').wait_for(timeout=90000)
                    preview_base64=await page.locator('#image-preview').evaluate('''async img=>{await img.decode();const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);return c.toDataURL('image/png').split(',')[1];}''')
                    await page.get_by_role('button',name='Save changes',exact=True).click()
                    await page.get_by_text('Variant updated. All device assignments have been retained.',exact=True).wait_for()
                    async with session.get(origin+f"/api/media/variant/{ink_variant['id']}/file") as response:
                        ink_native=await response.read()
                    validate_variant(ink_native,'inkplate_6')
                    ink_image=Image.open(io.BytesIO(ink_native))
                    native_view=ink_image.transpose(Image.Transpose.ROTATE_270).convert('RGB')
                    assert native_view.size==(600,800)
                    assert native_view.tobytes()==Image.open(io.BytesIO(base64.b64decode(preview_base64))).convert('RGB').tobytes()
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    await page.locator(f'[data-representation="{mountain_asset}"]').select_option(ink_variant['id'])
                    await page.locator(f'[data-add-asset="{mountain_asset}"]').click()
                    await page.get_by_text('Image added to the device list.',exact=True).wait_for()
                    assert await page.locator(f'[data-add-asset="{mountain_asset}"]').count()==0
                    await page.get_by_role('button',name='Close dialog').click()
                    ink_url=await page.locator('#image-url').input_value()
                    ink_json=await page.locator('#settings-url').input_value()
                    async with session.get(ink_json,headers={'X-Display-Battery-Millivolts':'3870'}) as response:
                        settings=await response.json()
                        assert settings['downloadUrl']==ink_url and settings['timeout']==3600
                    async with session.get(ink_url) as response:
                        assert response.content_type=='image/png' and await response.read()==ink_native
                    await page.locator('#device-voltage').filter(has_text='3.870 V').wait_for()
                    await page.get_by_label('Mounting orientation').select_option('portrait')
                    await page.get_by_label('Mounted upside down',exact=False).check()
                    await page.get_by_role('button',name='Save settings',exact=True).click()
                    await page.locator('#device-save-status').filter(has_text='Settings saved.').wait_for()
                    assert await page.locator('#device-voltage').inner_text()=='3.870 V'
                    async with session.get(ink_url) as response:
                        corrected=Image.open(io.BytesIO(await response.read()))
                        assert corrected.tobytes()==ink_image.transpose(Image.Transpose.ROTATE_180).tobytes()
                    await page.locator('#device-frame-preview img').evaluate('(img)=>img.decode()')
                    assert await page.locator('#device-frame-preview img').evaluate('(img)=>[img.naturalWidth,img.naturalHeight]')==[480,640]
                    await page.set_viewport_size({'width':390,'height':844})
                    await page.screenshot(path=str(artifacts/'inkplate6-mobile.png'),full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not errors, errors
                    await browser.close()
            print('Browser smoke passed: upload, full-resolution dithering methods, calibrated palette, variant overwrite, worker startup recovery/cancellation, automatic on/off pixels and manual tone preservation, matching descriptions, visible modal notifications, MQTT settings/secret handling and watchdog display, all three models, Inkplate eight-level PNG/portrait pixels/editing/voltage, assigned-image filtering, native 800×480 BMP delivery/rotation, device orientation/help, fixed-URL original/BMP delivery, CORS, and responsive layouts.')
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
