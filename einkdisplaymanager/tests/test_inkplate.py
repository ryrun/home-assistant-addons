import io
import json

import pytest
from correction import rotate_delivery
from media import GRAY8, inkplate_original, placeholder, validate_variant
from PIL import Image
from profiles import original_compatible
from test_http import path, picture, upload


def gray_png(size=(800, 600), value=109):
    output = io.BytesIO()
    Image.new('L', size, value).save(output, 'PNG')
    return output.getvalue()


def test_inkplate_pixel_contract_and_lossless_correction():
    source = Image.new('L', (800, 600))
    source.putdata([GRAY8[x // 100] for _y in range(600) for x in range(800)])
    output = io.BytesIO()
    source.save(output, 'PNG')
    data = output.getvalue()
    validate_variant(data, 'inkplate_6')
    assert set(source.tobytes()) == set(GRAY8)
    rotated = rotate_delivery(data, 'image/png')
    with Image.open(io.BytesIO(rotated)) as image:
        assert image.size == (800, 600)
        assert image.tobytes() == source.transpose(Image.Transpose.ROTATE_180).tobytes()
    for bad in (gray_png((600, 800)), gray_png(value=128), placeholder()):
        with pytest.raises(ValueError):
            validate_variant(bad, 'inkplate_6')
    with pytest.raises(ValueError):
        validate_variant(data, 'openpaper_l')
    assert original_compatible({'mime': 'image/png', 'original_supported': False, 'width': 320, 'height': 240, 'bytes': 100}, 'inkplate_6')


@pytest.mark.parametrize('mounting', ['portrait', 'landscape'])
async def test_original_png_delivery_fixed_url_orientation_and_cache(system, mounting):
    _manager, admin, frames = system
    response = await admin.post('/api/devices', json={'name': 'Inkplate', 'profile': 'inkplate_6'})
    assert response.status == 201
    device = await response.json()
    assert device['orientation'] == 'landscape'
    url = path(device['urls']['image'])
    blank = await frames.get(url)
    assert blank.content_type == 'image/png'
    validate_variant(await blank.read(), 'inkplate_6')
    source = Image.open(io.BytesIO(picture('PNG')))
    source.paste('white', (0, 0, 10, 8))
    output = io.BytesIO()
    source.save(output, 'PNG')
    original = output.getvalue()
    asset = await upload(admin, original, name='Photo.png')
    response = await admin.put('/api/devices/' + device['id'], json={
        'orientation': mounting, 'entries': [{'asset_id': asset, 'mode': 'original'}]})
    assert response.status == 200
    response = await frames.get(url)
    first = await response.read()
    assert response.content_type == 'image/png'
    assert first == inkplate_original(original, mounting)
    validate_variant(first, 'inkplate_6')
    etag = response.headers['ETag']
    response = await frames.get(url, headers={'If-None-Match': etag})
    assert response.status == 304
    await admin.put('/api/devices/' + device['id'], json={'upside_down': True})
    response = await frames.get(url, headers={'If-None-Match': etag})
    corrected = await response.read()
    assert response.status == 200
    assert Image.open(io.BytesIO(corrected)).tobytes() == Image.open(io.BytesIO(first)).transpose(Image.Transpose.ROTATE_180).tobytes()
    thumb = await admin.get(f'/api/media/asset/{asset}/thumbnail?device={device["id"]}')
    assert Image.open(io.BytesIO(await thumb.read())).size == ((480, 640) if mounting == 'portrait' else (640, 480))
    # A prepared OpenPaper raster cannot be mistaken for an Inkplate original.
    native = await upload(admin, placeholder('openpaper_7'))
    assert (await admin.put('/api/devices/' + device['id'], json={'entries': [{'asset_id': native, 'mode': 'original'}]})).status == 400


async def test_inkplate_variant_edit_and_settings_telemetry_contract(system):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Inkplate', 'profile': 'inkplate_6'})).json()
    identifier = device['id']
    asset = await upload(admin)
    data = gray_png()
    headers = {'X-Recipe': json.dumps({'profile': 'inkplate_6'})}
    response = await admin.post(f'/api/assets/{asset}/variants', data=data, headers=headers)
    assert response.status == 201
    variant = (await response.json())['id']
    entry = {'asset_id': asset, 'mode': 'variant', 'variant_id': variant}
    assigned = await (await admin.put('/api/devices/' + identifier, json={'entries': [entry]})).json()
    response = await frames.get(path(device['urls']['image']))
    assert response.content_type == 'image/png' and await response.read() == data
    response = await admin.put(f'/api/assets/{asset}/variants/{variant}', data=gray_png(value=219), headers={**headers, 'X-Variant-Version': '0'})
    assert response.status == 200
    assert manager.store.get('device', identifier)['entries'] == assigned['entries']
    assert await (await frames.get(path(device['urls']['image']))).read() == gray_png(value=219)
    # Keep the OpenPaper JSON schema. Telemetry travels in the incoming request.
    last_served = manager.store.get('device', identifier)['state']['last_served_at']
    settings_url = path(device['urls']['settings'])
    response = await frames.get(settings_url, headers={'X-Display-Battery-Millivolts': '3870'})
    settings = await response.json()
    assert set(settings) == {'downloadUrl', 'timeout', 'motionWakeup', 'autoRotation', 'chargerMode', 'httpAuthUser', 'httpAuthPassword'}
    assert settings['timeout'] == 3600 and settings['downloadUrl'] == device['urls']['image']
    first = manager.telemetry(identifier)
    assert first['battery_millivolts'] == 3870 and first['measured_at']
    status = await (await admin.get('/api/devices/' + identifier + '/status')).json()
    assert status['telemetry'] == first
    assert status['state']['last_served_at'] == last_served
    for bad in ('NaN', '-1', '3.87', '123456', '499', '20001', ''):
        assert (await frames.get(settings_url, headers={'X-Display-Battery-Millivolts': bad})).status == 200
        assert manager.telemetry(identifier) == first
    for request in (
        frames.head(settings_url, headers={'X-Display-Battery-Millivolts': '3900'}),
        frames.get(settings_url, headers={'X-Display-Battery-Millivolts': '3900', 'Sec-Fetch-Mode': 'cors'}),
        frames.get(settings_url.replace('?k=', '?k=wrong'), headers={'X-Display-Battery-Millivolts': '3900'}),
    ):
        await request
        assert manager.telemetry(identifier) == first
    response = await frames.get(settings_url, headers={'If-None-Match': response.headers['ETag'], 'X-Display-Battery-Millivolts': '3950'})
    assert response.status == 304 and manager.telemetry(identifier)['battery_millivolts'] == 3950
    payload = manager.mqtt.payload(manager.store.get('device', identifier))
    assert payload['battery_voltage'] == 3.95 and payload['battery_measured_at']
    configs = [json.loads(value[0]) for topic, value in manager.mqtt.desired(manager.mqtt.config).items() if topic.endswith('/config')]
    measured = next(config for config in configs if config['name'] == 'Battery voltage')
    assert measured['unit_of_measurement'] == 'V' and measured['device']['manufacturer'] == 'Soldered'
    assert (await admin.put('/api/devices/' + identifier, json={'settings': {'chargerMode': True}, 'confirm_nimh': True})).status == 400
    assert (await admin.delete('/api/devices/' + identifier)).status == 200
    assert manager.telemetry(identifier)['battery_millivolts'] is None
