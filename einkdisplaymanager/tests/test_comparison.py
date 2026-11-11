import io
import json

import pytest
from media import composition_thumbnail, placeholder
from PIL import Image
from test_http import upload


def source_image():
    image = Image.new('RGB', (160, 80), 'red')
    image.paste('blue', (80, 0, 160, 80))
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


@pytest.mark.parametrize('profile,mounting,size', [
    ('openpaper_l', 'portrait', (480, 640)), ('openpaper_l', 'landscape', (640, 480)),
    ('openpaper_7', 'portrait', (384, 640)), ('openpaper_7', 'landscape', (640, 384)),
    ('inkplate_6', 'portrait', (480, 640)), ('inkplate_6', 'landscape', (640, 480)),
])
async def test_original_composition_comparison_matches_device_geometry_and_keeps_colors(system, profile, mounting, size):
    _manager, admin, _frames = system
    original = await upload(admin, source_image())
    device = await (await admin.post('/api/devices', json={'name': 'Compare', 'profile': profile})).json()
    await admin.put('/api/devices/' + device['id'], json={'orientation': mounting, 'upside_down': True})
    recipe = {'profile': profile, 'orientation': mounting, 'fit': 'cover', 'focusX': 50, 'focusY': 50}
    response = await admin.post(f'/api/assets/{original}/variants', data=placeholder(profile), headers={'X-Recipe': json.dumps(recipe)})
    variant = (await response.json())['id']
    url = f'/api/media/variant/{variant}/thumbnail?device={device["id"]}'
    source = await admin.get(url + '&comparison=source')
    prepared = await admin.get(url)
    assert source.content_type == prepared.content_type == 'image/jpeg'
    with Image.open(io.BytesIO(await source.read())) as before, Image.open(io.BytesIO(await prepared.read())) as after:
        assert before.size == after.size == size
        assert before.convert('RGB').getpixel((10, size[1] // 2))[0] > 200
        assert before.convert('RGB').getpixel((size[0] - 10, size[1] // 2))[2] > 200
        assert before.tobytes() != after.tobytes()


def test_source_comparison_applies_crop_focus_and_source_rotation():
    for focus, channel in [(0, 0), (100, 2)]:
        data = composition_thumbnail(source_image(), {'orientation': 'portrait', 'fit': 'cover', 'focusX': focus}, 'inkplate_6', 'portrait')
        with Image.open(io.BytesIO(data)) as image:
            assert image.getpixel((240, 320))[channel] > 200
    data = composition_thumbnail(source_image(), {'orientation': 'landscape', 'fit': 'cover', 'rotation': 180}, 'inkplate_6', 'landscape')
    with Image.open(io.BytesIO(data)) as image:
        assert image.getpixel((10, 240))[2] > 200
