"""Exercise the isolated editor, font library, preview, RAM delivery and fallback UI."""

import asyncio
import io
import sys
import tempfile
from pathlib import Path

import aiohttp
from browser_smoke import free_port, sample_image
from PIL import Image, ImageFont
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    admin_port,device_port = free_port(),free_port()
    origin = f'http://127.0.0.1:{admin_port}'
    artifacts = Path('/private/tmp/eink-browser-artifacts')
    artifacts.mkdir(exist_ok=True)
    errors = []
    with tempfile.TemporaryDirectory(prefix='eink-dynamic-browser-') as data:
        process = await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'server.py'),'--dev','--data',data,
                        '--admin-port',str(admin_port),'--device-port',str(device_port),
                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        try:
            async with aiohttp.ClientSession() as session:
                for _ in range(100):
                    try:
                        async with session.get(origin+'/api/state') as response:
                            if response.status == 200:
                                state = await response.json()
                                if state['dynamic']['isolation']:
                                    break
                    except aiohttp.ClientError:
                        pass
                    await asyncio.sleep(.1)
                else:
                    raise RuntimeError('Dynamic service did not start with verified isolation.')
                headers={'X-Eink-CSRF':state['csrf']}
                async with session.post(origin+'/api/assets',data=sample_image(),headers={**headers,'X-File-Name':'Backdrop.jpg'}) as response:
                    asset=(await response.json())['id']
                await session.put(origin+'/api/settings',json={'base_url':f'http://127.0.0.1:{device_port}'},headers=headers)
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch()
                    page = await browser.new_page(viewport={'width':1440,'height':1100})
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    await page.goto(origin)
                    await page.get_by_role('link',name='Fonts',exact=True).click()
                    font_bytes=ImageFont.load_default(size=20).font_bytes
                    await page.locator('#font-upload').set_input_files({'name':'Aileron.ttf','mimeType':'font/ttf','buffer':font_bytes})
                    await page.get_by_text('Fonts uploaded.',exact=True).wait_for()
                    font_id=await page.locator('.font-row code').inner_text()
                    await page.get_by_role('link',name='Dynamic images',exact=True).click()
                    await page.locator('#new-dynamic').click()
                    await page.get_by_label('Name',exact=True).fill('Morning canvas')
                    await page.locator('#dynamic-interval').fill('10')
                    await page.locator('#dynamic-profile').select_option('inkplate_6')
                    assert await page.locator('#dynamic-orientation').input_value()=='landscape'
                    assert await page.locator('#dynamic-palette').input_value()=='gray8'
                    source=f'''screen.clear("#ffffff");
screen.image("{asset}", {{x:20,y:20,width:160,height:120}});
screen.rectangle({{x:200,y:200,width:400,height:200,stroke:palette.black,strokeWidth:2}});
screen.text("Hello World", {{x:400,y:300,font:"{font_id}",fontSize:40,color:palette.black,align:"center",verticalAlign:"middle"}});
'''
                    await page.get_by_role('textbox',name='JavaScript source').fill(source)
                    assert await page.locator('.cm-line span').count()>0
                    await page.locator('#dynamic-preview').click()
                    await page.locator('#dynamic-preview-stage img').wait_for(timeout=90000)
                    await page.locator('#dynamic-preview-stage img').evaluate('(img)=>img.decode()')
                    assert await page.locator('#dynamic-preview-stage img').evaluate('(img)=>img.naturalWidth>img.naturalHeight')
                    assert 'current draft' in await page.locator('#dynamic-render-status').inner_text()
                    await page.screenshot(path=str(artifacts/'dynamic-editor-desktop.png'),full_page=True)
                    await page.locator('#dynamic-save').click()
                    await page.locator('#notice').filter(has_text='Dynamic image and target saved.').wait_for()
                    await page.locator('#dynamic-render-status').filter(has_text='Ready').wait_for(timeout=90000)
                    await page.locator('#dynamic-preview-stage img').wait_for()
                    assert await page.locator('#dynamic-profile').is_disabled()
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.get_by_role('button',name='Edit Morning canvas',exact=True).wait_for()
                    await page.reload()
                    await page.get_by_role('button',name='Edit Morning canvas',exact=True).click()
                    assert 'Hello World' in await page.get_by_role('textbox',name='JavaScript source').inner_text()
                    assert await page.locator('#dynamic-interval').input_value()=='10'
                    await page.set_viewport_size({'width':390,'height':844})
                    await page.screenshot(path=str(artifacts/'dynamic-editor-mobile.png'),full_page=True)
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    await page.get_by_role('button',name='Close dialog').click()
                    await page.get_by_role('link',name='Devices',exact=False).click()
                    await page.locator('#add-device').click()
                    await page.get_by_label('Device name').fill('Dynamic desk')
                    await page.get_by_label('Device type').select_option('inkplate_6')
                    await page.locator('#new-device button.primary').click()
                    await page.get_by_role('heading',name='Dynamic desk',exact=True).wait_for()
                    url=await page.locator('#image-url').input_value()
                    await page.get_by_role('button',name='Add images',exact=False).click()
                    versions=page.get_by_label('Image version for Morning canvas')
                    assert await versions.locator('option[value="original"]').is_disabled()
                    assert await versions.input_value()!='original'
                    await versions.locator('..').get_by_role('button',name='Add to device',exact=True).click()
                    await page.get_by_text('Image added to the device list.',exact=True).wait_for()
                    await page.get_by_role('button',name='Close dialog').click()
                    async with session.get(url) as response:
                        image=await response.read()
                        assert response.status==200 and response.content_type=='image/png'
                        etag=response.headers['ETag']
                    assert Image.open(io.BytesIO(image)).size==(800,600)
                    async with session.get(url,headers={'If-None-Match':etag}) as response:
                        assert response.status==304
                    await page.get_by_role('link',name='Media Library',exact=False).click()
                    await page.get_by_role('link',name='Dynamic images',exact=True).click()
                    await page.get_by_role('button',name='Edit Morning canvas',exact=True).click()
                    await page.get_by_role('textbox',name='JavaScript source').fill('throw new Error("Check this draft");')
                    await page.locator('#dynamic-preview').click()
                    await page.locator('#notice').filter(has_text='Check this draft').wait_for()
                    # Saving a failing script retains the last successful device output.
                    await page.locator('#dynamic-save').click()
                    await page.locator('#notice').filter(has_text='Dynamic image and target saved.').wait_for()
                    await page.locator('#dynamic-render-status').filter(has_text='Last render failed').wait_for(timeout=90000)
                    async with session.get(url,headers={'If-None-Match':etag}) as response:
                        assert response.status==304
                    # Persistent media contains just the original, thumbnail and font.
                    paths=list((Path(data)/'media').iterdir())
                    assert len(paths)==3,paths
                    assert not errors,errors
                    await browser.close()
            print('Dynamic browser smoke passed: library sections, real CodeMirror highlighting/CSP, font upload and IDs, source editing, native preview, saved target rendering, reload/mobile, device picker and PNG/304 delivery, visible errors, last-good output, and RAM-only generated images.')
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(),15)
            except TimeoutError:
                process.kill()
                await process.wait()
            log=(await process.stderr.read()).decode()
            if process.returncode not in (0,-15):
                print(log,file=sys.stderr)


if __name__=='__main__':
    asyncio.run(main())
