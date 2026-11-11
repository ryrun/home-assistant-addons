from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import scheduling
from aiohttp import web
from mqtt_bridge import fetch_health
from playback import completed, select_for_request
from test_http import path, picture, upload
from test_playback import frame


def stamp(value, fold=0):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Europe/Berlin'), fold=fold).timestamp()


def scheduled(interval=21600, **options):
    device = frame()
    device['interval'] = interval
    device['schedule'] = scheduling.validate({'timezone': 'Europe/Berlin', 'anchor_enabled': True,
                                            'anchor_time': '03:00', 'anchor_date': '2026-11-11'} | options, interval)
    return device


@pytest.mark.parametrize('interval,now,target', [
    (86400, '2026-11-11T10:00', '2026-11-12T03:00'),
    (21600, '2026-11-11T10:00', '2026-11-11T15:00'),
    (21600, '2026-11-11T03:00', '2026-11-11T09:00'),
    (25200, '2026-11-11T10:30', '2026-11-11T17:00'),
    (172800, '2026-11-11T04:00', '2026-11-13T03:00'),
])
def test_local_anchor_grid_and_arbitrary_intervals(interval, now, target):
    device = scheduled(interval)
    assert scheduling.next_due(device, stamp(now)) == stamp(target)


@pytest.mark.parametrize('now,target', [
    ('2026-11-11T21:00', '2026-11-12T09:00'),
    ('2026-11-12T03:00', '2026-11-12T09:00'),
    ('2026-11-12T08:00', '2026-11-12T09:00'),
    ('2026-11-12T09:00', '2026-11-12T15:00'),
])
def test_quiet_hours_skip_anchored_slots(now, target):
    device = scheduled(quiet_enabled=True, quiet_start='22:00', quiet_end='08:00')
    assert scheduling.next_due(device, stamp(now)) == stamp(target)


def test_relative_quiet_hours_midnight_and_boundaries():
    device = scheduled(900, anchor_enabled=False, quiet_enabled=True)
    assert scheduling.next_due(device, stamp('2026-11-11T21:55')) == stamp('2026-11-12T06:00')
    assert scheduling.is_quiet(device, stamp('2026-11-11T22:00'))
    assert not scheduling.is_quiet(device, stamp('2026-11-12T06:00'))
    device = scheduled(900, anchor_enabled=False, quiet_enabled=True, quiet_start='12:00', quiet_end='14:00')
    assert scheduling.next_due(device, stamp('2026-11-11T11:55')) == stamp('2026-11-11T14:00')


def test_sparse_second_based_grid_does_not_exhaust_search_and_break_device_reads():
    device = scheduled(86401, quiet_enabled=True, quiet_start='03:01', quiet_end='03:00')
    anchor = stamp('2026-11-11T03:00')
    # Each daily slot shifts by one second. Once the one-minute allowed window
    # is exhausted, the next phase can be far away; the API must remain usable.
    after_window = anchor + 60 * 86401
    expected_local = datetime(2026, 11, 11, 3) + timedelta(seconds=86400 * 86401)
    expected = expected_local.replace(tzinfo=ZoneInfo('Europe/Berlin')).timestamp()
    assert scheduling.next_due(device, after_window) == expected
    assert scheduling.sleep_seconds(device, after_window) == 2592000


def test_dst_keeps_daily_local_time_skips_missing_slots_and_does_not_repeat_fold():
    device = scheduled(86400)
    spring = stamp('2026-03-28T03:00')
    autumn = stamp('2026-10-24T03:00')
    assert scheduling.next_due(device, spring) - spring == 23 * 3600
    assert scheduling.next_due(device, autumn) - autumn == 25 * 3600
    device['schedule']['anchor_time'] = '02:30'
    assert scheduling.next_due(device, stamp('2026-03-29T00:00')) == stamp('2026-03-30T02:30')
    first = scheduling.next_due(device, stamp('2026-10-25T00:00'))
    assert first == stamp('2026-10-25T02:30', fold=0)
    assert scheduling.next_due(device, first + 1) == stamp('2026-10-26T02:30')
    device['schedule'].update(anchor_enabled=False, quiet_enabled=True, quiet_start='00:00', quiet_end='02:30')
    device['interval'] = 60
    assert scheduling.next_due(device, stamp('2026-10-25T02:10', fold=1)) == stamp('2026-10-25T02:30', fold=1)
    assert scheduling.next_due(device, stamp('2026-10-25T02:10', fold=0)) == stamp('2026-10-25T02:30', fold=0)
    assert scheduling.next_due(device, stamp('2026-03-29T01:40')) == stamp('2026-03-29T03:00')


@pytest.mark.parametrize('options', [
    {'timezone': '../invalid'}, {'timezone': 'Not/A_Zone'}, {'anchor_time': '25:00'},
    {'anchor_enabled': 'yes'}, {'anchor_date': 'bad'}, {'anchor_date': '2026-W46-3'},
    {'quiet_enabled': True, 'quiet_start': '06:00', 'quiet_end': '06:00'},
    {'quiet_enabled': True, 'quiet_start': '22:00', 'quiet_end': '06:00'},
])
def test_invalid_or_fully_blocked_schedules_are_rejected(options):
    with pytest.raises(ValueError):
        scheduled(86400, **options)


def test_playback_quiet_hours_and_health_use_the_same_next_slot():
    device = scheduled(quiet_enabled=True, quiet_start='22:00', quiet_end='08:00')
    device['enabled'] = True
    start = stamp('2026-11-11T21:00')
    select_for_request(device, start)
    completed(device, 'first', start)
    assert device['state']['deadline'] == stamp('2026-11-12T09:00')
    # An unsolicited wake in quiet hours does not automatically consume an entry.
    assert select_for_request(device, stamp('2026-11-12T03:00')) == '0'
    health = fetch_health(device, {'started_at': start}, stamp('2026-11-12T08:59'), 120)
    assert not health['update_overdue'] and health['battery_estimate'] == 100
    assert health['expected_at'] == stamp('2026-11-12T09:00')
    assert select_for_request(device, stamp('2026-11-12T09:00')) == '1'


@pytest.mark.parametrize('profile', ['openpaper_l', 'openpaper_7', 'inkplate_6'])
async def test_dynamic_json_no_stale_304_and_next_connection_independent_of_watchdog(system, monkeypatch, profile):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Scheduled', 'profile': profile})).json()
    first, second = await upload(admin), await upload(admin, picture(color='red'))
    endpoint = '/api/devices/' + device['id']
    now = [stamp('2026-11-11T21:00')]
    monkeypatch.setattr('server.time.time', lambda: now[0])
    response = await admin.put(endpoint, json={'interval': 21600, 'schedule': scheduled(quiet_enabled=True, quiet_start='22:00', quiet_end='08:00')['schedule'],
                                             'entries': [{'asset_id': first, 'mode': 'original'}, {'asset_id': second, 'mode': 'original'}]})
    assert response.status == 200
    await (await frames.get(path(device['urls']['image']))).read()
    response = await frames.get(path(device['urls']['settings']))
    body = await response.json()
    assert body['timeout'] == 43200 and set(body) == {'timeout', 'downloadUrl', 'motionWakeup', 'autoRotation', 'chargerMode', 'httpAuthUser', 'httpAuthPassword'}
    assert 'no-store' in response.headers['Cache-Control']
    validators = {'If-None-Match': response.headers['ETag'], 'If-Modified-Since': response.headers['Last-Modified']}
    now[0] += 300
    response = await frames.get(path(device['urls']['settings']), headers=validators)
    assert response.status == 200 and (await response.json())['timeout'] == 42900
    saved = manager.store.get('device', device['id'])
    assert saved['state']['last_served_at'] == stamp('2026-11-11T21:00')
    assert saved['state']['next_request_at'] == stamp('2026-11-12T09:00')
    status = await (await admin.get(endpoint + '/status')).json()
    assert status['timing']['next_connection_at'] == stamp('2026-11-12T09:00')
    # JSON checks after a missed image cannot restore the fetch-health indicator.
    now[0] = stamp('2026-11-12T09:10')
    last_dynamic = await frames.get(path(device['urls']['settings']))
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0
    # Default interval behavior and conditional JSON remain available when disabled.
    await admin.put(endpoint, json={'schedule': {'anchor_enabled': False, 'quiet_enabled': False}})
    response = await frames.get(path(device['urls']['settings']), headers={'If-Modified-Since': last_dynamic.headers['Last-Modified']})
    assert response.status == 200
    assert (await response.json())['timeout'] == 21600
    response = await frames.get(path(device['urls']['settings']), headers={'If-None-Match': response.headers['ETag']})
    assert response.status == 304


async def test_transfer_across_anchor_uses_issued_sleep_for_forecast_and_watchdog(system, monkeypatch):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Slow frame'})).json()
    a = await upload(admin)
    now = [stamp('2026-11-11T03:00')]
    monkeypatch.setattr('server.time.time', lambda: now[0])
    endpoint = '/api/devices/' + device['id']
    await admin.put(endpoint, json={'interval': 21600, 'schedule': scheduled()['schedule'],
                                   'entries': [{'asset_id': a, 'mode': 'original'}]})
    await (await frames.get(path(device['urls']['image']))).read()
    now[0] = stamp('2026-11-11T08:59:50')
    response = await frames.get(path(device['urls']['settings']))
    assert (await response.json())['timeout'] == 60
    original = web.StreamResponse.write
    async def slow_transfer(response, data):
        await original(response, data)
        now[0] = stamp('2026-11-11T09:00:10')
    monkeypatch.setattr(web.StreamResponse, 'write', slow_transfer)
    now[0] = stamp('2026-11-11T08:59:55')
    await (await frames.get(path(device['urls']['image']))).read()
    monkeypatch.setattr(web.StreamResponse, 'write', original)
    saved = manager.store.get('device', device['id'])
    expected = stamp('2026-11-11T09:01:10')
    assert saved['state']['next_request_at'] == saved['state']['expected_image_at'] == expected
    assert saved['state']['deadline'] == stamp('2026-11-11T09:00')
    now[0] = expected + 121
    assert manager.mqtt.health(saved)['battery_estimate'] == 0
    # Saving desired settings cannot make an overdue device healthy again.
    await admin.put(endpoint, json={'interval': 43200})
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0
    await frames.get(path(device['urls']['settings']))
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0


async def test_shorter_json_sleep_can_shorten_but_never_postpone_outstanding_image_deadline(system, monkeypatch):
    manager, admin, frames = system
    d = await (await admin.post('/api/devices', json={'name': 'Changed interval'})).json()
    a = await upload(admin)
    endpoint = '/api/devices/' + d['id']
    now = [stamp('2026-11-11T03:00')]
    monkeypatch.setattr('server.time.time', lambda: now[0])
    await admin.put(endpoint, json={'interval': 21600, 'entries': [{'asset_id': a, 'mode': 'original'}]})
    await frames.get(path(d['urls']['settings']))
    await (await frames.get(path(d['urls']['image']))).read()
    now[0] = stamp('2026-11-11T04:00')
    await admin.put(endpoint, json={'interval': 60})
    await frames.get(path(d['urls']['settings']))
    assert manager.store.get('device', d['id'])['state']['expected_image_at'] == now[0] + 60
    now[0] += 181
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0
    await admin.put(endpoint, json={'interval': 21600})
    await frames.get(path(d['urls']['settings']))
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0
    await (await frames.get(path(d['urls']['image']))).read()
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 100
