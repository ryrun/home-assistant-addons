import io

import pytest
from PIL import Image
from test_http import path, picture, upload

PRESETS = [
    ('srgb', [], None),
    ('gray8', [], {(v, v, v) for v in (0, 36, 73, 109, 146, 182, 219, 255)}),
    ('grayscale', [], {(0, 0, 0), (255, 255, 255)}),
    ('spectra6', [], {(0, 0, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0), (255, 255, 255)}),
    ('custom', ['#123456', '#fedcba'], {(18, 52, 86), (254, 220, 186)}),
]


async def create(admin, **options):
    response = await admin.post('/api/devices', json={
        'name': 'Custom widget', 'profile': 'custom',
        'custom': {'width': 127, 'height': 65, 'color_mode': 'srgb', **options},
    })
    assert response.status == 201, await response.text()
    return await response.json()


@pytest.mark.parametrize('mode,colors,allowed', PRESETS)
async def test_custom_original_png_contract(system, mode, colors, allowed):
    _manager, admin, frames = system
    device = await create(admin, color_mode=mode, colors=colors, dither='floyd')
    url = path(device['urls']['image'])
    assert (await frames.get(url.split('?')[0])).status == 401
    asset = await upload(admin, picture('PNG', '#294992'))
    response = await admin.put('/api/devices/' + device['id'], json={
        'entries': [{'asset_id': asset, 'mode': 'original'}],
    })
    assert response.status == 200, await response.text()
    response = await frames.get(url)
    assert response.status == 200 and response.content_type == 'image/png'
    data = await response.read()
    with Image.open(io.BytesIO(data)) as output:
        assert output.size == (127, 65) and output.mode == 'RGB'
        if allowed is None:
            assert output.getpixel((63, 32)) == (41, 73, 146)
            assert device['custom']['dither'] == 'none'
        else:
            assert set(output.get_flattened_data()) <= allowed
    unchanged = await frames.get(url, headers={'If-None-Match': response.headers['ETag']})
    assert unchanged.status == 304
    preview = await admin.get(f'/api/media/asset/{asset}/thumbnail?device={device["id"]}')
    assert preview.status == 200 and preview.content_type == 'image/jpeg'


@pytest.mark.parametrize('mode,colors', [('srgb', []), ('custom', ['#345678', '#123456'])])
async def test_custom_dynamic_variant_is_delivered_at_widget_dimensions(system, mode, colors):
    manager, admin, frames = system
    device = await create(admin, width=1280, height=600, color_mode=mode, colors=colors, dither='floyd')
    background, accent = ('palette.color0', 'palette.color1') if colors else ("'#345678'", "'#123456'")
    asset = await (await admin.post('/api/dynamic', json={
        'name': 'Widget', 'script': f"screen.clear({background});"
        f"screen.rectangle({{x:screen.width-5,y:screen.height-5,width:5,height:5,fill:{accent}}});",
    })).json()
    target = await admin.post(f'/api/dynamic/{asset["id"]}/targets', json={
        'name': 'Widgy Medium', 'recipe': {'profile': device['profile']},
    })
    assert target.status == 201, await target.text()
    variant = await target.json()
    assert variant['mime'] == 'image/png'
    await manager.dynamic.render(asset['id'])
    response = await admin.put('/api/devices/' + device['id'], json={
        'entries': [{'asset_id': asset['id'], 'mode': 'variant', 'variant_id': variant['id']}],
    })
    assert response.status == 200, await response.text()
    response = await frames.get(path(device['urls']['image']))
    assert response.status == 200 and response.content_type == 'image/png'
    with Image.open(io.BytesIO(await response.read())) as output:
        assert output.size == (1280, 600) and output.mode == 'RGB'
        assert output.getpixel((0, 0)) == (52, 86, 120)
        assert output.getpixel((1279, 599)) == (18, 52, 86)


async def test_custom_resize_preserves_url_and_invalidates_original_cache(system):
    _manager, admin, frames = system
    device = await create(admin)
    endpoint = '/api/devices/' + device['id']
    asset = await upload(admin, picture())
    await admin.put(endpoint, json={'entries': [{'asset_id': asset, 'mode': 'original'}]})
    url = path(device['urls']['image'])
    previous = await frames.get(url)
    assert previous.status == 200
    etag = previous.headers['ETag']
    result = await admin.put(endpoint, json={'custom': device['custom'] | {'width': 197}})
    assert result.status == 200, await result.text()
    assert (await result.json())['urls']['image'] == device['urls']['image']
    response = await frames.get(url, headers={'If-None-Match': etag})
    assert response.status == 200
    with Image.open(io.BytesIO(await response.read())) as image:
        assert image.size == (197, 65)



async def test_custom_variant_upload_rejects_wrong_pixels_and_locks_profile_geometry(system):
    _manager, admin, _frames = system
    device = await create(admin, color_mode='custom', colors=['#000000', '#ffffff'])
    asset = await upload(admin)
    settings = {'X-Recipe': f'{{"profile":"{device["profile"]}","palette":"custom","dither":"none"}}'}
    target = f'/api/assets/{asset}/variants'
    for color in ('#808080', (0, 0, 0, 0), '#000000'):
        size = (127, 66) if color == '#000000' else (127, 65)
        data = io.BytesIO()
        Image.new('RGBA', size, color).save(data, 'PNG')
        assert (await admin.post(target, data=data.getvalue(), headers=settings)).status == 400
    data = io.BytesIO()
    Image.new('RGB', (127, 65), 'black').save(data, 'PNG')
    assert (await admin.post(target, data=data.getvalue(), headers=settings)).status == 201
    endpoint = '/api/devices/' + device['id']
    assert (await admin.put(endpoint, json={'custom': device['custom'] | {'width': 197}})).status == 409
    assert (await admin.delete(endpoint)).status == 409
