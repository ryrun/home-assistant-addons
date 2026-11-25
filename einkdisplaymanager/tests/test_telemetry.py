import json

import pytest
import telemetry
from multidict import CIMultiDict
from test_battery import PROFILE, discharge
from test_http import path

HEADERS = {
    'X-OpenPaper-Battery-Millivolts': '5120',
    'X-OpenPaper-USB-Connected': '0',
    'X-OpenPaper-Charging': '0',
    'X-OpenPaper-Firmware-Version': '0.1.35',
    'X-OpenPaper-Display': 'epd13',
    'X-OpenPaper-Wakeup': 'timer',
    'X-OpenPaper-WiFi-RSSI': '-67',
    'X-OpenPaper-Orientation': '0',
}
EXPECTED = {'battery_millivolts': 5120, 'usb_connected': False, 'charging': False,
            'firmware_version': '0.1.35', 'reported_display': 'epd13', 'wakeup_reason': 'timer',
            'wifi_rssi': -67, 'sensor_orientation': 0}


def test_exact_upstream_headers_and_case_insensitivity():
    assert telemetry.parse(CIMultiDict({key.lower(): value for key, value in HEADERS.items()})) == EXPECTED
    assert telemetry.parse({'X-Display-Battery-Millivolts': '3870'}) == {'battery_millivolts': 3870}
    assert telemetry.parse({'X-OpenPaper-Firmware-Version': '0.1.35-dev+abc'}) == {'firmware_version': '0.1.35-dev+abc'}


@pytest.mark.parametrize('suffix,invalid', [
    ('USB-Connected', 'true'), ('Charging', '2'), ('Display', 'epd99'), ('Wakeup', 'other'),
    ('WiFi-RSSI', '-128'), ('WiFi-RSSI', '1'), ('WiFi-RSSI', '-67.5'),
    ('Orientation', '4'), ('Orientation', '-1'), ('Battery-Millivolts', 'NaN'),
    ('Battery-Millivolts', '0'), ('Firmware-Version', '<script>'), ('Firmware-Version', 'v' * 65),
])
def test_invalid_fields_are_independently_ignored(suffix, invalid):
    values = telemetry.parse({'X-OpenPaper-' + suffix: invalid, 'X-Unknown': 'secret'})
    assert values == {}


async def test_telemetry_on_settings_and_image_304_and_partial_snapshots(system, monkeypatch):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Telemetry frame', 'profile': 'openpaper_l'})).json()
    endpoint = '/api/devices/' + device['id']
    url = path(device['urls']['settings'])
    await admin.put(endpoint, json={'battery': {'enabled': True, 'method': 'chemistry', 'chemistry': 'alkaline'}})
    now = 1800000000
    monkeypatch.setattr('server.time.time', lambda: now)
    response = await frames.get(url, headers=HEADERS)
    initial = manager.telemetry(device['id'])
    assert all(initial[key] == value for key, value in EXPECTED.items())
    assert initial['measured_at'] == now
    assert initial['field_updated_at']['sensor_orientation'] == now
    modified = response.headers['ETag']
    now += 3600
    response = await frames.get(url, headers={'If-None-Match': modified, 'X-OpenPaper-WiFi-RSSI': '-50'})
    assert response.status == 304
    current = manager.telemetry(device['id'])
    assert current['wifi_rssi'] == -50 and current['battery_millivolts'] == 5120
    assert current['measured_at'] == initial['measured_at']
    assert current['field_updated_at']['sensor_orientation'] == initial['reported_at']
    assert current['field_updated_at']['wifi_rssi'] == now
    response = await frames.get(path(device['urls']['image']))
    await response.read()
    response = await frames.get(path(device['urls']['image']), headers={
        'If-None-Match': response.headers['ETag'], 'X-OpenPaper-Battery-Millivolts': '5100',
        'X-OpenPaper-Wakeup': 'button', 'X-OpenPaper-Orientation': '3'})
    assert response.status == 304
    public = await (await admin.get(endpoint + '/status')).json()
    assert public['telemetry']['battery_millivolts'] == 5100
    assert public['telemetry']['wakeup_reason'] == 'button'
    assert public['telemetry']['sensor_orientation'] == 3
    payload = manager.mqtt.payload(manager.store.get('device', device['id']))
    assert payload['usb_connected'] is False and payload['wifi_rssi'] == -50
    assert payload['battery_voltage'] == 5.1
    configs = [json.loads(data[0]) for topic, data in manager.mqtt.desired(manager.mqtt.config).items()
               if topic.endswith('/config')]
    usb = next(item for item in configs if item['name'] == 'USB power')
    assert usb['device']['sw_version'] == '0.1.35'
    assert "'ON'" in usb['value_template'] and "'OFF'" in usb['value_template']
    assert next(item for item in configs if item['name'] == 'WiFi signal')['unit_of_measurement'] == 'dBm'


async def test_untrusted_and_invalid_telemetry_cannot_replace_status(system):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Validation frame', 'profile': 'openpaper_l'})).json()
    url = path(device['urls']['settings'])
    await frames.get(url, headers=HEADERS)
    initial = manager.telemetry(device['id'])
    for method, target, headers in [('HEAD', url, HEADERS), ('GET', url, HEADERS | {'Origin': 'http://example.test'}),
                                     ('GET', url.split('?')[0] + '?k=invalid', HEADERS),
                                     ('GET', url, {'X-OpenPaper-Wakeup': '<script>', 'X-OpenPaper-Battery-Millivolts': '-1'})]:
        response = await frames.request(method, target, headers=headers)
        await response.read()
        assert manager.telemetry(device['id']) == initial


async def test_usb_and_charging_reset_discharge_forecast_without_voltage(system, monkeypatch):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Charging frame', 'profile': 'openpaper_l'})).json()
    endpoint = '/api/devices/' + device['id']
    await admin.put(endpoint, json={'battery': PROFILE})
    stored = manager.store.get('device', device['id'])
    now = discharge(manager.battery_forecast, stored)
    monkeypatch.setattr('server.time.time', lambda: now)
    assert manager.battery_status(stored)['forecast']
    await frames.get(path(device['urls']['settings']), headers={'X-OpenPaper-USB-Connected': '1'})
    assert manager.battery_status(stored)['forecast'] is None
    await frames.get(path(device['urls']['settings']), headers={'X-OpenPaper-Battery-Millivolts': '5600'})
    assert stored['id'] not in manager.battery_forecast.histories
    await frames.get(path(device['urls']['settings']), headers={
        'X-OpenPaper-USB-Connected': '0', 'X-OpenPaper-Charging': '0', 'X-OpenPaper-Battery-Millivolts': '5600'})
    assert len(manager.battery_forecast.histories[stored['id']]['samples']) == 1
    await frames.get(path(device['urls']['settings']), headers={'X-OpenPaper-Charging': '1'})
    assert stored['id'] not in manager.battery_forecast.histories



@pytest.mark.parametrize('delay', [1800, 7 * 86400])
async def test_older_usb_report_does_not_block_new_voltage_only_readings(system, monkeypatch, delay):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Frame with older power report'})).json()
    await admin.put('/api/devices/' + device['id'], json={'battery': PROFILE})
    now = 1800000000
    monkeypatch.setattr('server.time.time', lambda: now)
    url = path(device['urls']['settings'])
    await frames.get(url, headers={'X-OpenPaper-USB-Connected': '1', 'X-OpenPaper-Battery-Millivolts': '5600'})
    detail_url = '/api/devices/' + device['id']
    status = (await (await admin.get(detail_url)).json())['battery_status']
    assert status['forecast_progress']['reason'] == 'external_power'
    now += delay
    await frames.get(url, headers={'X-Display-Battery-Millivolts': '5500'})
    detail = await (await admin.get(detail_url)).json()
    assert detail['telemetry']['usb_connected'] is True
    assert detail['battery_status']['stale_power_fields'] == ['usb_connected']
    assert detail['battery_status']['forecast_progress']['sample_count'] == 1
    assert detail['battery_status']['forecast_progress']['reason'] == 'collecting'
    now += 1800
    await frames.get(url, headers={'X-Display-Battery-Millivolts': '5490'})
    status = (await (await admin.get(detail_url)).json())['battery_status']
    assert status['forecast'] and status['forecast_progress']['sample_count'] == 2
