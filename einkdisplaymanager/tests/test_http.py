import asyncio
import io
import time
from contextlib import suppress
from urllib.parse import urlsplit

from aiohttp import ClientError
from aiohttp.test_utils import TestClient, TestServer
from media import placeholder
from PIL import Image
from server import FLASHER_ORIGIN, Manager


def picture(fmt='JPEG', color='blue'):
    out = io.BytesIO()
    Image.new('RGB', (30, 40), color).save(out, fmt)
    return out.getvalue()


async def upload(admin, data=None, name='Photo'):
    response = await admin.post('/api/assets', data=data or picture(), headers={'X-File-Name': name})
    assert response.status == 201
    return (await response.json())['id']


async def device(admin, assets):
    response = await admin.post('/api/devices', json={'name': 'Living room'})
    assert response.status == 201
    result = await response.json()
    entries = [{'asset_id': a, 'mode': 'original', 'enabled': True} for a in assets]
    response = await admin.put('/api/devices/' + result['id'], json={'entries': entries, 'interval': 60})
    assert response.status == 200
    return await response.json()


def path(url):
    parsed = urlsplit(url)
    return parsed.path + '?' + parsed.query


async def test_deduplication_variants_and_safe_delete(system):
    _manager, admin, frames = system
    data = picture('PNG')
    identifier = await upload(admin, data)
    duplicate = await admin.post('/api/assets', data=data)
    assert (await duplicate.json()) == {'id': identifier, 'duplicate': True}
    original = await admin.get(f'/api/media/asset/{identifier}/file')
    assert await original.read() == data
    response = await admin.post(f'/api/assets/{identifier}/variants', data=placeholder(), headers={'X-Recipe': '{"fit":"contain"}'})
    assert response.status == 201
    variant = (await response.json())['id']
    d = await device(admin, [])
    response = await admin.put('/api/devices/' + d['id'], json={'entries': [{'asset_id': identifier, 'mode': 'original'}]})
    assert response.status == 400  # PNG is allowed in the library, not on the device.
    response = await admin.put('/api/devices/' + d['id'], json={'entries': [{'asset_id': identifier, 'mode': 'variant', 'variant_id': variant}]})
    assert response.status == 200
    response = await frames.get(path(d['urls']['image']))
    assert response.status == 200 and response.content_type == 'image/bmp'
    assert await response.read() == placeholder()
    assert (await admin.delete(f'/api/media/variant/{variant}')).status == 409
    assert (await admin.delete(f'/api/media/asset/{identifier}')).status == 409
    assert (await admin.delete('/api/devices/' + d['id'])).status == 200
    assert (await admin.delete(f'/api/media/variant/{variant}')).status == 200
    assert (await admin.delete(f'/api/media/asset/{identifier}')).status == 200


async def test_stable_url_cache_head_json_and_concurrent_requests(system):
    manager, admin, frames = system
    a = await upload(admin, picture(color='blue'))
    b = await upload(admin, picture(color='red'))
    d = await device(admin, [a, b])
    image = path(d['urls']['image'])
    response = await frames.get(image)
    first = await response.read()
    etag = response.headers['ETag']
    assert first == picture(color='blue')
    deadline = manager.store.get('device', d['id'])['state']['deadline']
    assert (await frames.get(image, headers={'If-None-Match': etag})).status == 304
    assert manager.store.get('device', d['id'])['state']['deadline'] == deadline
    persisted = manager.store.get('device', d['id'])
    persisted['state']['deadline'] = time.time() - 60
    manager.store.save('device', persisted)
    assert (await frames.head(image)).status == 200
    assert manager.store.get('device', d['id'])['state']['selected'] == d['entries'][0]['id']
    settings = await frames.get(path(d['urls']['settings']))
    settings_body = await settings.json()
    assert settings_body['downloadUrl'] == d['urls']['image']
    assert 'entries' not in settings_body
    assert (await frames.get(path(d['urls']['settings']), headers={'If-Modified-Since': settings.headers['Last-Modified']})).status == 304
    assert manager.store.get('device', d['id'])['state']['selected'] == d['entries'][0]['id']
    async def fetch():
        response = await frames.get(image, headers={'If-None-Match': etag})
        assert response.status == 200  # Old validator cannot freeze the next image.
        return await response.read()
    results = await asyncio.gather(*(fetch() for _ in range(8)))
    assert results == [picture(color='red')] * 8
    assert manager.store.get('device', d['id'])['state']['cycle'] == 1


async def test_listener_isolation_csrf_token_rotation_and_networks(system):
    manager, admin, frames = system
    response = await admin.post('/api/devices', json={'name': 'Forbidden'}, headers={'X-Eink-CSRF': ''})
    assert response.status == 403
    d = await device(admin, [])
    assert (await frames.get('/api/state')).status != 200
    assert (await frames.post(path(d['urls']['image']))).status != 200
    assert (await frames.get(path(d['urls']['image']) + 'bad')).status == 401
    assert (await admin.get(path(d['urls']['image']))).status == 404
    assert (await frames.get('/health')).status == 200
    new = await (await admin.post('/api/devices/' + d['id'] + '/rotate-token')).json()
    assert (await frames.get(path(d['urls']['image']))).status == 401
    assert (await frames.get(path(d['urls']['settings']))).status == 401
    assert (await frames.get(path(new['urls']['settings']))).status == 200
    manager.networks = []
    assert (await frames.get(path(new['urls']['image']), headers={'X-Forwarded-For': '127.0.0.1'})).status == 403


async def test_ingress_denies_direct_loopback_outside_dev(tmp_path):
    manager = Manager(tmp_path)
    async with TestClient(TestServer(manager.apps()[0])) as client:
        assert (await client.get('/')).status == 403
        assert (await client.get('/api/state', headers={'X-Remote-User-Id': 'admin'})).status == 403
    manager.store.close()


async def test_limits_charging_conflicts_and_duplicate_device(system):
    _manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin, [a])
    assert (await admin.put('/api/settings', json={'base_url': 'http://' + 'a' * 100})).status == 400
    for interval in [0, 59, 2592001, True, 60.5]:
        assert (await admin.put('/api/devices/' + d['id'], json={'interval': interval})).status == 400
    assert (await admin.put('/api/devices/' + d['id'], json={'settings': {'chargerMode': True}})).status == 400
    assert (await admin.put('/api/devices/' + d['id'], json={'settings': {'chargerMode': True}, 'confirm_nimh': True})).status == 200
    assert (await admin.put('/api/devices/' + d['id'], json={'modified': d['modified'], 'name': 'Stale edit'})).status == 409
    response = await admin.post('/api/devices', json={'name': 'Second frame', 'copy_from': d['id']})
    copy = await response.json()
    assert copy['urls'] != d['urls']
    assert copy['entries'][0]['id'] != d['entries'][0]['id']
    assert copy['state']['last_served_at'] is None
    assert (await admin.put('/api/devices/' + d['id'], json={'enabled': False})).status == 200
    assert (await frames.get(path(d['urls']['image']))).status == 410


async def test_restart_persists_originals_credentials_queue_and_progress(system, tmp_path):
    manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin, [a])
    response = await frames.get(path(d['urls']['image']))
    await response.read()
    saved = manager.store.get('device', d['id'])
    restarted = Manager(tmp_path, dev=True)
    try:
        assert restarted.store.get('device', d['id']) == saved
        assert restarted.store.path(restarted.store.get('asset', a)['file']).read_bytes() == picture()
        assert restarted.urls(saved) == d['urls']
    finally:
        restarted.store.close()


async def test_interrupted_delivery_keeps_pending_selection_for_retry(system, monkeypatch):
    from aiohttp import web
    manager, admin, frames = system
    a = await upload(admin)
    b = await upload(admin, picture(color='red'))
    d = await device(admin, [a, b])
    original_write = web.StreamResponse.write

    async def interrupted_write(self, data):
        raise ConnectionResetError('Synthetic disconnect')

    monkeypatch.setattr(web.StreamResponse, 'write', interrupted_write)
    with suppress(ClientError, ConnectionError):
        async with frames.get(path(d['urls']['image'])) as response:
            await response.read()
    pending = manager.store.get('device', d['id'])
    assert pending['state']['pending'] is True
    assert pending['state']['last_served_at'] is None
    assert 'interrupted' in pending['state']['last_error']
    monkeypatch.setattr(web.StreamResponse, 'write', original_write)
    response = await frames.get(path(d['urls']['image']))
    assert await response.read() == picture()
    assert manager.store.get('device', d['id'])['state']['selected'] == d['entries'][0]['id']


async def test_device_independence_and_storage_quota(system):
    manager, admin, frames = system
    a = await upload(admin)
    b = await upload(admin, picture(color='red'))
    first = await device(admin, [a, b])
    second = await device(admin, [a, b])
    await admin.post('/api/devices/' + first['id'] + '/next')
    response = await frames.get(path(first['urls']['image']))
    assert await response.read() == picture(color='red')
    response = await frames.get(path(second['urls']['image']))
    assert await response.read() == picture()
    manager.store.quota = manager.store.usage()
    assert (await admin.post('/api/assets', data=picture(color='green'))).status == 400
    assert len(manager.store.all('asset')) == 2


async def test_flasher_cors_preserves_auth_and_does_not_advance_images(system):
    manager, admin, frames = system
    a = await upload(admin)
    b = await upload(admin, picture(color='red'))
    d = await device(admin, [a, b])
    image, settings = path(d['urls']['image']), path(d['urls']['settings'])
    headers = {'Origin': FLASHER_ORIGIN}
    response = await frames.get(settings + '&nocache=123', headers=headers)
    assert response.status == 200
    assert response.headers['Access-Control-Allow-Origin'] == FLASHER_ORIGIN
    assert (await response.json())['downloadUrl'] == d['urls']['image']
    conditional = await frames.get(settings, headers={**headers, 'If-Modified-Since': response.headers['Last-Modified']})
    assert conditional.status == 304
    assert conditional.headers['Access-Control-Allow-Origin'] == FLASHER_ORIGIN
    preflight = await frames.options(settings, headers={**headers, 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'cache-control'})
    assert preflight.status == 204
    assert preflight.headers['Access-Control-Allow-Origin'] == FLASHER_ORIGIN
    assert (await frames.options(settings, headers={**headers, 'Access-Control-Request-Method': 'POST'})).status == 403
    invalid = await frames.get(settings + 'bad', headers=headers)
    assert invalid.status == 401
    assert invalid.headers['Access-Control-Allow-Origin'] == FLASHER_ORIGIN
    evil = await frames.get(settings, headers={'Origin': 'https://example.com'})
    assert evil.status == 403
    assert 'Access-Control-Allow-Origin' not in evil.headers
    # First serve image A as the frame, then make B due. Web-Flasher checks must
    # preview A without consuming B or claiming a new frame delivery.
    await (await frames.get(image)).read()
    saved = manager.store.get('device', d['id'])
    saved['state']['deadline'] = 1
    manager.store.save('device', saved)
    before = manager.store.get('device', d['id'])['state']
    preview = await frames.get(image, headers=headers)
    assert preview.status == 200 and await preview.read() == picture()
    assert preview.headers['Access-Control-Allow-Origin'] == FLASHER_ORIGIN
    assert manager.store.get('device', d['id'])['state'] == before
    browser_image = await frames.get(image, headers={'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Dest': 'image'})
    assert await browser_image.read() == picture()
    assert manager.store.get('device', d['id'])['state'] == before
    response = await frames.get(image)
    assert await response.read() == picture(color='red')


async def test_landscape_variant_keeps_native_bmp_with_landscape_thumbnail(system):
    _manager, admin, _frames = system
    identifier = await upload(admin)
    result = await admin.post(f'/api/assets/{identifier}/variants', data=placeholder(), headers={
        'X-Recipe': '{"orientation":"landscape"}'})
    assert result.status == 201
    variant = (await result.json())['id']
    response = await admin.get(f'/api/media/variant/{variant}/thumbnail')
    thumb = Image.open(io.BytesIO(await response.read()))
    assert thumb.size == (640, 480)
    response = await admin.get(f'/api/media/variant/{variant}/file')
    assert Image.open(io.BytesIO(await response.read())).size == (1200, 1600)


async def test_device_mounting_previews_match_native_pixels_and_json_contract(system):
    manager, admin, frames = system
    a = await upload(admin)
    data = bytearray(placeholder())
    data[118:118+480000] = b'\x33' * 480000
    data[118+480000:] = b'\x11' * 480000
    response = await admin.post(f'/api/assets/{a}/variants', data=data)
    v = (await response.json())['id']
    d = await device(admin, [])
    response = await admin.put('/api/devices/'+d['id'], json={'orientation': 'landscape', 'entries': [
        {'asset_id': a, 'variant_id': v, 'mode': 'variant'}]})
    assert response.status == 200
    d = await response.json()
    assert d['orientation'] == 'landscape'
    assert d['settings_json'] == {'timeout': 60, 'motionWakeup': False, 'autoRotation': False,
                                 'chargerMode': False, 'httpAuthUser': '', 'httpAuthPassword': '',
                                 'downloadUrl': d['urls']['image']}
    assert (await admin.put('/api/devices/'+d['id'], json={'orientation': 'diagonal'})).status == 400
    for mounting, expected in [('portrait',(480,640)),('landscape',(640,480))]:
        response = await admin.get(f'/api/media/variant/{v}/thumbnail?orientation={mounting}')
        image = Image.open(io.BytesIO(await response.read()))
        assert image.size == expected
        if mounting == 'landscape':
            left = image.getpixel((100,240))
            right = image.getpixel((540,240))
            assert left[2] > 240 and left[0] < 10
            assert right[0] > 240 and right[2] < 10
    response = await frames.get(path(d['urls']['image']))
    assert await response.read() == data  # Preview mounting never rewrites output.
    copied = await (await admin.post('/api/devices', json={'name':'Copy', 'copy_from':d['id']})).json()
    assert copied['orientation'] == 'landscape'
    legacy = manager.store.get('device',d['id'])
    del legacy['orientation']
    manager.store.save('device',legacy)
    assert (await (await admin.get('/api/devices/'+d['id'])).json())['orientation'] == 'portrait'


async def test_editing_variant_creates_revision_without_changing_assignments(system):
    manager, admin, _frames = system
    a = await upload(admin)
    response = await admin.post(f'/api/assets/{a}/variants', data=placeholder(), headers={
        'X-Recipe':'{"profile":"openpaper_l","focusX":20,"dither":"stucki"}'})
    parent = (await response.json())['id']
    d = await device(admin, [])
    await admin.put('/api/devices/'+d['id'], json={'entries':[
        {'asset_id':a,'variant_id':parent,'mode':'variant'}]})
    before = manager.store.get('variant',parent)
    response = await admin.post(f'/api/assets/{a}/variants', data=placeholder(), headers={
        'X-Recipe':'{"profile":"openpaper_l","focusX":80,"dither":"jarvis"}', 'X-Parent-Variant':parent})
    assert response.status == 201
    child = (await response.json())['id']
    assert child != parent
    assert manager.store.get('variant',child)['parent_variant_id'] == parent
    assert manager.store.get('variant',parent) == before
    assert manager.store.get('device',d['id'])['entries'][0]['variant_id'] == parent
    different = await upload(admin,picture(color='green'))
    assert (await admin.post(f'/api/assets/{different}/variants', data=placeholder(),headers={'X-Parent-Variant':parent})).status == 400
    assert (await admin.post(f'/api/assets/{a}/variants', data=placeholder(), headers={
        'X-Recipe':'{"profile":"unknown_small_display"}'})).status == 400
    incompatible = manager.store.get('variant',child)
    incompatible['profile'] = 'other_size'
    manager.store.save('variant', incompatible)
    assert (await admin.put('/api/devices/'+d['id'],json={'entries':[
        {'asset_id':a,'mode':'variant','variant_id':child}]})).status == 400


async def test_settings_validator_tracks_content_changes_not_only_device_edits(system, monkeypatch):
    manager, admin, frames = system
    d = await device(admin, [])
    url = path(d['urls']['settings'])
    response = await frames.get(url)
    old_modified = response.headers['Last-Modified']
    await response.read()
    original_generator = manager.firmware_settings
    def changed_generator(device):
        # Simulate an add-on upgrade changing supported JSON output while the
        # stored device's configuration timestamp remains unchanged.
        result = original_generator(device)
        result['motionWakeup'] = True
        return result
    monkeypatch.setattr(manager, 'firmware_settings', changed_generator)
    response = await frames.get(url, headers={'If-Modified-Since':old_modified})
    assert response.status == 200
    assert (await response.json())['motionWakeup'] is True
    new_modified = response.headers['Last-Modified']
    assert new_modified != old_modified
    response = await frames.get(url, headers={'If-Modified-Since':new_modified})
    assert response.status == 304


async def test_image_name_changes_preserve_original_file_variants_and_assignments(system, tmp_path):
    manager, admin, frames = system
    a = await upload(admin, name='original.jpg')
    v = (await (await admin.post(f'/api/assets/{a}/variants',data=placeholder())).json())['id']
    d = await device(admin,[a])
    before = manager.store.get('asset',a)
    variant_before = manager.store.get('variant',v)
    entries_before = manager.store.get('device',d['id'])['entries']
    assert (await admin.patch(f'/api/assets/{a}',json={'name':'Forbidden'},headers={'X-Eink-CSRF':''})).status == 403
    response = await admin.patch(f'/api/assets/{a}',json={'name':'  Summer by the lake  '})
    assert response.status == 200
    assert (await response.json())['name'] == 'Summer by the lake'
    after = manager.store.get('asset',a)
    assert after == {**before,'name':'Summer by the lake'}
    assert after['filename'] == 'original.jpg'
    assert manager.store.get('variant',v) == variant_before
    assert manager.store.get('device',d['id'])['entries'] == entries_before
    assert await (await frames.get(path(d['urls']['image']))).read() == picture()
    for bad_name in ['', ' ', 'x'*121, 'bad\nname', None]:
        assert (await admin.patch(f'/api/assets/{a}',json={'name':bad_name})).status == 400
    duplicate = await admin.post('/api/assets',data=picture(),headers={'X-File-Name':'different.jpg'})
    assert (await duplicate.json())['id'] == a
    assert manager.store.get('asset',a)['name'] == 'Summer by the lake'
    # Existing installations did not store filename separately. Preserve it on
    # first rename, and keep the chosen display name after reopening the store.
    legacy = manager.store.get('asset',a)
    del legacy['filename']
    legacy['name'] = 'legacy.jpg'
    manager.store.save('asset',legacy)
    assert (await admin.patch(f'/api/assets/{a}',json={'name':'Renamed legacy photo'})).status == 200
    restarted = Manager(tmp_path,dev=True)
    try:
        stored = restarted.store.get('asset',a)
        assert stored['name'] == 'Renamed legacy photo' and stored['filename'] == 'legacy.jpg'
    finally:
        restarted.store.close()


async def test_image_headers_do_not_trigger_firmware_empty_validator_shortcut(system):
    _manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin, [a])
    for url in [path(d['urls']['image'])]:
        response = await frames.get(url)
        await response.read()
        etag, last_modified = response.headers['ETag'], response.headers['Last-Modified']
        # Firmware: with an existing image and an empty settings.lastModified,
        # an empty response Last-Modified would compare equal even with an ETag.
        cached = ''
        assert not (('etag:' + etag) == cached or last_modified == cached)
        unchanged = await frames.get(url, headers={'If-None-Match':etag})
        assert unchanged.status == 304 and unchanged.headers['Last-Modified'] == last_modified
    empty = await device(admin, [])
    response = await frames.get(path(empty['urls']['image']))
    assert response.headers['Last-Modified']
    await response.read()


async def test_last_modified_fallback_revalidates_current_image_without_freezing_next(system):
    manager, admin, frames = system
    a = await upload(admin)
    b = await upload(admin,picture(color='red'))
    d = await device(admin,[a,b])
    url = path(d['urls']['image'])
    first = await frames.get(url)
    await first.read()
    old_modified = first.headers['Last-Modified']
    assert (await frames.get(url,headers={'If-Modified-Since':old_modified})).status == 304
    stored = manager.store.get('device',d['id'])
    stored['state']['deadline'] = 1
    manager.store.save('device',stored)
    next_image = await frames.get(url,headers={'If-Modified-Since':old_modified})
    assert next_image.status == 200
    assert await next_image.read() == picture(color='red')
    assert next_image.headers['Last-Modified'] != old_modified


async def test_live_transfer_progress_and_logs_are_readable_without_the_transfer_lock(system, monkeypatch):
    from aiohttp import web
    manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin,[a])
    entered, release = asyncio.Event(), asyncio.Event()
    original_write = web.StreamResponse.write

    async def slow_write(self, data):
        if data.startswith(b'\xff\xd8'):
            entered.set()
            await release.wait()
        return await original_write(self,data)

    monkeypatch.setattr(web.StreamResponse,'write',slow_write)
    async def download():
        response = await frames.get(path(d['urls']['image']))
        return await response.read()
    transfer = asyncio.create_task(download())
    try:
        await asyncio.wait_for(entered.wait(),timeout=2)
        response = await asyncio.wait_for(admin.get('/api/devices/'+d['id']+'/status'),timeout=1)
        active = await response.json()
        assert active['transfer']['status'] == 'sending'
        assert active['transfer']['total_bytes'] == len(picture())
        assert active['transfer']['bytes_written'] == 0
        assert active['events'][-1]['event'] == 'image_started'
        token = manager.store.get('device',d['id'])['token']
        assert token not in str(active)
        assert (await admin.post('/api/devices/'+d['id']+'/next')).status == 409
    finally:
        release.set()
        assert await transfer == picture()
    finished = await (await admin.get('/api/devices/'+d['id']+'/status')).json()
    assert finished['transfer']['status'] == 'completed'
    assert finished['transfer']['bytes_written'] == len(picture())
    assert finished['events'][-1]['event'] == 'image_completed'


async def test_transfer_timeout_has_distinct_diagnostic_category(system,monkeypatch):
    from aiohttp import web
    _manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin,[a])
    async def timed_out(self,data):
        raise TimeoutError('Synthetic timeout; do not log raw exception data')
    monkeypatch.setattr(web.StreamResponse,'write',timed_out)
    with suppress(ClientError,ConnectionError):
        response = await frames.get(path(d['urls']['image']))
        await response.read()
    status = await (await admin.get('/api/devices/'+d['id']+'/status')).json()
    assert status['transfer']['status'] == 'interrupted'
    assert status['transfer']['error_code'] == 'timeout'
    assert status['state']['pending'] is True
    assert 'Synthetic timeout' not in str(status)


async def test_upside_down_delivery_keeps_shared_variant_queue_and_fixed_url(system):
    from correction import rotate_delivery
    from media import digest
    from test_correction import asymmetric_bmp

    manager, admin, frames = system
    a = await upload(admin)
    data = asymmetric_bmp()
    v = await (await admin.post(f'/api/assets/{a}/variants', data=data)).json()
    stored_variant = manager.store.get('variant', v['id'])
    d = await device(admin, [a])
    update = await admin.put('/api/devices/' + d['id'], json={'entries': [
        {'asset_id': a, 'variant_id': v['id'], 'mode': 'variant'},
        {'asset_id': a, 'mode': 'original'}]})
    d = await update.json()
    peer = await (await admin.post('/api/devices', json={'name': 'Peer', 'copy_from': d['id']})).json()
    url = path(d['urls']['image'])
    first = await frames.get(url)
    assert await first.read() == data
    before_preview = await (await admin.get(f"/api/media/variant/{v['id']}/thumbnail?device={d['id']}")).read()
    persisted = manager.store.get('device', d['id'])
    persisted['state']['deadline'] = time.time() - 1
    manager.store.save('device', persisted)
    updated = await (await admin.put('/api/devices/' + d['id'], json={'upside_down': True})).json()
    assert updated['upside_down'] and updated['state']['pending']
    assert updated['urls'] == d['urls']
    assert updated['entries'] == d['entries']
    for mounting in ('portrait', 'landscape'):
        await admin.put('/api/devices/' + d['id'], json={'orientation': mounting})
        preview = await admin.get(f"/api/media/variant/{v['id']}/thumbnail?device={d['id']}")
        image = Image.open(io.BytesIO(await preview.read()))
        assert image.size == ((480,640) if mounting == 'portrait' else (640,480))
        if mounting == 'portrait':
            assert image.tobytes() == Image.open(io.BytesIO(before_preview)).tobytes()
    second = await frames.get(url, headers={'If-None-Match': first.headers['ETag']})
    assert second.status == 200
    corrected = await second.read()
    assert corrected == rotate_delivery(data, 'image/bmp')
    assert second.headers['ETag'] == '"' + digest(corrected) + '"'
    assert second.headers['Last-Modified'] != first.headers['Last-Modified']
    assert manager.store.get('device', d['id'])['state']['selected'] == d['entries'][0]['id']
    assert (await frames.get(url, headers={'If-None-Match': second.headers['ETag']})).status == 304
    assert await (await frames.get(path(peer['urls']['image']))).read() == data
    assert await (await admin.get(f"/api/media/variant/{v['id']}/file")).read() == data
    assert manager.store.get('variant', v['id']) == stored_variant
    assert manager.delivery_cache_bytes == len(data) + len(corrected)
    await admin.put('/api/devices/' + d['id'], json={'upside_down': False})
    assert await (await frames.get(url, headers={'If-None-Match': second.headers['ETag']})).read() == data


async def test_upside_down_settings_sensor_conflict_copy_and_legacy_default(system):
    manager, admin, frames = system
    d = await device(admin, [])
    endpoint = '/api/devices/' + d['id']
    assert d['upside_down'] is False
    await admin.put(endpoint, json={'settings': {'autoRotation': True}})
    response = await admin.put(endpoint, json={'upside_down': True, 'settings': {'autoRotation': True}})
    assert response.status == 400
    assert not manager.store.get('device', d['id'])['upside_down']
    assert (await admin.put(endpoint, json={'upside_down': 'yes'})).status == 400
    updated = await (await admin.put(endpoint, json={'upside_down': True})).json()
    assert updated['settings']['autoRotation'] is False
    assert (await (await frames.get(path(d['urls']['settings']))).json())['autoRotation'] is False
    copied = await (await admin.post('/api/devices', json={'name':'Inverted copy', 'copy_from':d['id']})).json()
    assert copied['upside_down'] is True
    legacy = manager.store.get('device', d['id'])
    del legacy['upside_down']
    manager.store.save('device', legacy)
    assert (await (await admin.get(endpoint)).json())['upside_down'] is False


async def test_original_upside_down_delivery_and_correction_failure_diagnostics(system, monkeypatch):
    import server
    from correction import rotate_delivery

    manager, admin, frames = system
    original = picture()
    a = await upload(admin, original)
    d = await device(admin, [a])
    await admin.put('/api/devices/' + d['id'], json={'upside_down': True})
    response = await frames.get(path(d['urls']['image']))
    assert response.content_type == 'image/jpeg'
    assert await response.read() == rotate_delivery(original, 'image/jpeg')
    assert await (await admin.get(f'/api/media/asset/{a}/file')).read() == original
    manager.delivery_cache.clear()
    manager.delivery_cache_bytes = 0
    def invalid(*_args):
        raise ValueError('private processing detail')
    monkeypatch.setattr(server, 'rotate_delivery', invalid)
    failed = await frames.get(path(d['urls']['image']))
    assert failed.status == 503
    assert 'private processing detail' not in await failed.text()
    activity = await (await admin.get('/api/devices/' + d['id'] + '/status')).json()
    assert activity['transfer']['error_code'] == 'correction_failed'
    assert 'private processing detail' not in str(activity)


async def test_overwrite_variant_preserves_assignments_and_revalidates_current_delivery(system):
    from correction import rotate_delivery
    from test_correction import asymmetric_bmp

    manager, admin, frames = system
    a = await upload(admin)
    original = await (await admin.get(f'/api/media/asset/{a}/file')).read()
    old = asymmetric_bmp()
    v = (await (await admin.post(f'/api/assets/{a}/variants', data=old)).json())['id']
    shared = (await (await admin.post(f'/api/assets/{a}/variants', data=old)).json())['id']
    before = manager.store.get('variant', v)
    d = await device(admin, [a])
    d = await (await admin.put('/api/devices/'+d['id'], json={'entries':[
        {'asset_id':a,'variant_id':v,'mode':'variant'}, {'asset_id':a,'mode':'original'}]})).json()
    peer = await (await admin.post('/api/devices', json={'name':'Inverted peer','copy_from':d['id']})).json()
    await admin.put('/api/devices/'+peer['id'], json={'upside_down':True})
    validators = {}
    for frame in (d, peer):
        response = await frames.get(path(frame['urls']['image']))
        await response.read()
        validators[frame['id']] = response.headers['ETag']
        persisted = manager.store.get('device',frame['id'])
        persisted['state']['deadline'] = time.time()-1
        manager.store.save('device',persisted)
    new = bytearray(placeholder())
    new[118:718] = b'\x33'*600
    response = await admin.put(f'/api/assets/{a}/variants/{v}',data=new,headers={
        'X-Variant-Version':'0','X-Variant-Name':'Updated variant','X-Recipe':'{"dither":"stucki","orientation":"landscape"}'})
    assert response.status == 200
    assert await response.json() == {'id':v,'revision':1}
    updated = manager.store.get('variant',v)
    assert updated['id'] == before['id'] and updated['created_at'] == before['created_at']
    assert updated['name'] == 'Updated variant' and updated['recipe']['dither'] == 'stucki'
    assert len(manager.store.all('variant')) == 2
    for frame in (d, peer):
        persisted = manager.store.get('device',frame['id'])
        assert persisted['entries'] == frame['entries']
        assert persisted['state']['selected'] == frame['entries'][0]['id'] and persisted['state']['pending']
        response = await frames.get(path(frame['urls']['image']),headers={'If-None-Match':validators[frame['id']]})
        assert response.status == 200
        assert await response.read() == (bytes(new) if frame is d else rotate_delivery(bytes(new),'image/bmp'))
        assert response.headers['ETag'] != validators[frame['id']]
        assert manager.store.get('device',frame['id'])['state']['selected'] == frame['entries'][0]['id']
    assert await (await admin.get(f'/api/media/asset/{a}/file')).read() == original
    assert await (await admin.get(f'/api/media/variant/{shared}/file')).read() == old
    assert Image.open(io.BytesIO(await (await admin.get(f'/api/media/variant/{v}/thumbnail')).read())).size == (640,480)


async def test_overwrite_variant_rejects_stale_foreign_invalid_and_quota_failures(system):
    from test_correction import asymmetric_bmp

    manager, admin, _frames = system
    a = await upload(admin)
    v = (await (await admin.post(f'/api/assets/{a}/variants', data=placeholder())).json())['id']
    before = manager.store.get('variant',v)
    headers = {'X-Variant-Version':'0'}
    endpoint = f'/api/assets/{a}/variants/{v}'
    assert (await admin.put(endpoint,data=placeholder())).status == 409
    other = await upload(admin,picture(color='green'))
    assert (await admin.put(f'/api/assets/{other}/variants/{v}',data=placeholder(),headers=headers)).status == 400
    assert (await admin.put(endpoint,data=b'invalid',headers=headers)).status == 400
    manager.store.quota = manager.store.usage()
    assert (await admin.put(endpoint,data=asymmetric_bmp(),headers=headers)).status == 400
    assert manager.store.get('variant',v) == before
    manager.store.quota += 2*1024*1024
    assert (await admin.put(endpoint,data=asymmetric_bmp(),headers=headers)).status == 200
    assert (await admin.put(endpoint,data=placeholder(),headers=headers)).status == 409
    assert manager.store.get('variant',v)['revision'] == 1


async def test_variant_overwrite_waits_for_an_active_transfer(system, monkeypatch):
    from aiohttp import web
    from test_correction import asymmetric_bmp

    manager, admin, frames = system
    a = await upload(admin)
    old = placeholder()
    v = (await (await admin.post(f'/api/assets/{a}/variants',data=old)).json())['id']
    d = await device(admin, [])
    await admin.put('/api/devices/'+d['id'],json={'entries':[{'asset_id':a,'variant_id':v,'mode':'variant'}]})
    started, release = asyncio.Event(), asyncio.Event()
    write = web.StreamResponse.write
    async def blocked(response,chunk):
        if response.content_type == 'image/bmp' and not started.is_set():
            started.set()
            await release.wait()
        return await write(response,chunk)
    monkeypatch.setattr(web.StreamResponse,'write',blocked)
    download = await frames.get(path(d['urls']['image']))
    await started.wait()
    replacing = asyncio.create_task(admin.put(f'/api/assets/{a}/variants/{v}',data=asymmetric_bmp(),headers={'X-Variant-Version':'0'}))
    try:
        await asyncio.sleep(.05)
        assert not replacing.done()
        assert manager.store.get('variant',v)['hash'] == manager.representation(manager.store.get('device',d['id']))['hash']
    finally:
        release.set()
    assert await download.read() == old
    assert (await replacing).status == 200
    assert manager.store.get('device',d['id'])['state']['pending']
    assert await (await frames.get(path(d['urls']['image']))).read() == asymmetric_bmp()
