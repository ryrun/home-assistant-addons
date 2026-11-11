import io
import json

import pytest
from correction import rotate_delivery
from media import device_thumbnail, inspect_image, placeholder, validate_bmp
from PIL import Image
from profiles import PROFILES, device_orientation, original_compatible, view_size
from test_http import device, path, picture, upload


@pytest.mark.parametrize('identifier,size,length', [('openpaper_l', (1200,1600), 960118),
                                                   ('openpaper_7', (800,480), 192118)])
def test_model_native_contract_and_exact_upside_down_pixels(identifier,size,length):
    data = bytearray(placeholder(identifier))
    data[118:122] = b'\x01\x23\x56\x33'
    data[-4:] = b'\x66\x55\x11\x22'
    data = bytes(data)
    assert len(data) == length
    validate_bmp(data,identifier)
    metadata,_thumb = inspect_image(data)
    assert metadata['native_profile'] == identifier and metadata['original_supported']
    corrected = rotate_delivery(data,'image/bmp')
    assert corrected[:118] == data[:118]
    with Image.open(io.BytesIO(data)) as source, Image.open(io.BytesIO(corrected)) as rotated:
        assert source.size == rotated.size == size
        assert rotated.tobytes() == source.transpose(Image.Transpose.ROTATE_180).tobytes()
    assert rotate_delivery(corrected,'image/bmp') == data
    damaged = bytearray(data)
    damaged[118] = 0x44
    with pytest.raises(ValueError):
        rotate_delivery(bytes(damaged),'image/bmp')
    other = next(key for key in PROFILES if key != identifier)
    with pytest.raises(ValueError):
        validate_bmp(data,other)
    assert original_compatible(metadata,identifier) and not original_compatible(metadata,other)
    del metadata['native_profile']
    assert not original_compatible(metadata,other)  # Existing saved metadata remains safe.


@pytest.mark.parametrize('identifier,mounting,expected', [
    ('openpaper_l','portrait',(480,640)), ('openpaper_l','landscape',(640,480)),
    ('openpaper_7','portrait',(384,640)), ('openpaper_7','landscape',(640,384))])
def test_mounting_dimensions_and_compensated_thumbnails(identifier,mounting,expected):
    data = bytearray(placeholder(identifier))
    profile = PROFILES[identifier]
    midpoint = profile['width']*profile['height']//4
    data[118:118+midpoint] = b'\x33'*midpoint
    corrected = rotate_delivery(bytes(data),'image/bmp')
    before = device_thumbnail(data,mounting=='landscape',True,False,identifier)
    after = device_thumbnail(corrected,mounting=='landscape',True,True,identifier)
    with Image.open(io.BytesIO(before)) as normal, Image.open(io.BytesIO(after)) as inverted:
        assert normal.size == inverted.size == expected
        assert normal.tobytes() == inverted.tobytes()
    width,height = view_size(identifier,mounting)
    assert (width>height) == (mounting=='landscape')
    generic = Image.open(io.BytesIO(device_thumbnail(picture(),mounting=='landscape',profile_id=identifier)))
    assert generic.size == expected


async def test_openpaper7_creation_defaults_copy_placeholder_and_firmware_json(system):
    manager, admin, frames = system
    response = await admin.post('/api/devices',json={'name':'Small frame','profile':'openpaper_7'})
    assert response.status == 201
    small = await response.json()
    assert small['profile'] == 'openpaper_7' and small['orientation'] == 'landscape'
    response = await frames.get(path(small['urls']['image']))
    assert response.content_type == 'image/bmp'
    assert await response.read() == placeholder('openpaper_7')
    large = await device(admin,[])
    assert large['profile'] == 'openpaper_l' and large['orientation'] == 'portrait'
    response = await frames.get(path(large['urls']['image']))
    assert await response.read() == placeholder()
    settings = await (await frames.get(path(small['urls']['settings']))).json()
    assert settings['downloadUrl'] == small['urls']['image']
    assert set(settings) == {'downloadUrl','timeout','motionWakeup','autoRotation','chargerMode','httpAuthUser','httpAuthPassword'}
    copied = await (await admin.post('/api/devices',json={'name':'Small copy','copy_from':small['id']})).json()
    assert copied['profile'] == 'openpaper_7' and copied['orientation'] == 'landscape'
    assert (await admin.post('/api/devices',json={'name':'Wrong copy','copy_from':small['id'],'profile':'openpaper_l'})).status == 400
    assert (await admin.post('/api/devices',json={'name':'Unknown','profile':'unknown'})).status == 400
    assert (await admin.put('/api/devices/'+small['id'],json={'profile':'openpaper_l'})).status == 400
    legacy = manager.store.get('device',small['id'])
    del legacy['orientation']
    assert device_orientation(legacy) == 'landscape'


async def test_prepared_images_cannot_cross_models_and_7_variants_can_be_updated(system):
    manager, admin, frames = system
    a = await upload(admin)
    small = await (await admin.post('/api/devices',json={'name':'Seven','profile':'openpaper_7'})).json()
    large = await device(admin,[])
    small_data = bytearray(placeholder('openpaper_7'))
    small_data[118:518] = b'\x33'*400
    small_data = bytes(small_data)
    small_headers = {'X-Recipe':json.dumps({'profile':'openpaper_7'})}
    response = await admin.post(f'/api/assets/{a}/variants',data=small_data,headers=small_headers)
    assert response.status == 201
    v = (await response.json())['id']
    assert manager.store.get('variant',v)['recipe']['orientation'] == 'landscape'
    assert (await admin.post(f'/api/assets/{a}/variants',data=placeholder(),headers=small_headers)).status == 400
    assert (await admin.post(f'/api/assets/{a}/variants',data=small_data)).status == 400
    entry = {'asset_id':a,'mode':'variant','variant_id':v}
    assert (await admin.put('/api/devices/'+large['id'],json={'entries':[entry]})).status == 400
    assigned = await (await admin.put('/api/devices/'+small['id'],json={'entries':[entry]})).json()
    first = await frames.get(path(small['urls']['image']))
    assert await first.read() == small_data
    await admin.put('/api/devices/'+small['id'],json={'upside_down':True,'orientation':'portrait'})
    rotated = await frames.get(path(small['urls']['image']))
    assert await rotated.read() == rotate_delivery(small_data,'image/bmp')
    thumb = await admin.get(f"/api/media/variant/{v}/thumbnail?device={small['id']}")
    assert Image.open(io.BytesIO(await thumb.read())).size == (384,640)
    assert (await admin.get(f"/api/media/variant/{v}/thumbnail?device={large['id']}")).status == 400
    # Changing an assigned variant to a different model must preserve the old record.
    old = manager.store.get('variant',v)
    response = await admin.put(f'/api/assets/{a}/variants/{v}',data=placeholder(),headers={'X-Variant-Version':'0'})
    assert response.status == 400 and manager.store.get('variant',v) == old
    updated = await admin.put(f'/api/assets/{a}/variants/{v}',data=placeholder('openpaper_7'),headers={**small_headers,'X-Variant-Version':'0'})
    assert updated.status == 200
    assert manager.store.get('device',small['id'])['entries'] == assigned['entries']
    # A native 7-inch BMP remains eligible as Original only on matching devices.
    native_original = await upload(admin,small_data,name='Prepared small BMP')
    original_entry = {'asset_id':native_original,'mode':'original'}
    assert (await admin.put('/api/devices/'+large['id'],json={'entries':[original_entry]})).status == 400
    assert (await admin.put('/api/devices/'+small['id'],json={'entries':[original_entry]})).status == 200
    assert await (await frames.get(path(small['urls']['image']))).read() == rotate_delivery(small_data,'image/bmp')
    legacy = manager.store.get('asset',native_original)
    del legacy['native_profile']
    manager.store.save('asset',legacy)
    assert (await admin.put('/api/devices/'+large['id'],json={'entries':[original_entry]})).status == 400
    for target in (small,large):
        assert (await admin.put('/api/devices/'+target['id'],json={'entries':[{'asset_id':a,'mode':'original'}]})).status == 200


async def test_mqtt_discovery_reports_each_actual_model(system):
    manager,admin,_frames = system
    await admin.post('/api/devices',json={'name':'Seven','profile':'openpaper_7'})
    await device(admin,[])
    messages = manager.mqtt.desired(manager.mqtt.config)
    models = {json.loads(payload)['device']['model'] for topic,(payload,_retain) in messages.items() if topic.endswith('/config')}
    assert models == {'OpenPaper L','OpenPaper 7'}


async def test_reupload_refreshes_previously_unsupported_seven_original_without_renaming(system):
    manager,admin,_frames = system
    data = placeholder('openpaper_7')
    identifier = await upload(admin,data,name='Existing image name')
    old = manager.store.get('asset',identifier)
    old['original_supported'] = False
    old['original_note'] = 'Create a variant.'
    old.pop('native_profile')
    manager.store.save('asset',old)
    response = await admin.post('/api/assets',data=data,headers={'X-File-Name':'Different upload name'})
    assert await response.json() == {'id':identifier,'duplicate':True}
    refreshed = manager.store.get('asset',identifier)
    assert refreshed['name'] == 'Existing image name' and refreshed['file'] == old['file']
    assert refreshed['original_supported'] and refreshed['native_profile'] == 'openpaper_7'
