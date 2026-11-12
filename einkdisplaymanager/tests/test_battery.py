import json

import battery
import pytest
from test_http import path

PROFILE = {'enabled': True, 'chemistry': 'custom', 'series_cells': 4, 'empty_voltage': 1.2, 'full_voltage': 1.6}


@pytest.mark.parametrize('millivolts,expected', [(4800, 0), (5600, 50), (6400, 100), (4000, 0), (7000, 100), (None, None)])
def test_pack_to_cell_calibrated_estimate_is_bounded_and_unknown_without_reading(millivolts, expected):
    result = battery.status({'profile': 'openpaper_l', 'battery': PROFILE}, {'battery_millivolts': millivolts, 'measured_at': 1000})
    assert result['estimated_percent'] == expected and result['estimated']
    assert result['source'] == 'linear_voltage' and result['measured_at'] == 1000


@pytest.mark.parametrize('change', [
    {'series_cells': True}, {'series_cells': 0}, {'series_cells': 33}, {'enabled': 'yes'},
    {'empty_voltage': float('nan')}, {'full_voltage': float('inf')}, {'full_voltage': 1.1},
    {'empty_voltage': 10**400}, {'full_voltage': 10**400},
    {'chemistry': 'unsupported'}, {'empty_voltage': None}, {'arbitrary': True},
])
def test_invalid_battery_profiles(change):
    with pytest.raises(ValueError):
        battery.validate(PROFILE | change)


@pytest.mark.parametrize('model,cells', [('openpaper_l', 4), ('openpaper_7', 4), ('inkplate_6', 1)])
async def test_optional_profiles_and_generic_voltage_reporting_do_not_change_firmware_json(system, model, cells):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Voltage frame', 'profile': model})).json()
    assert device['battery']['series_cells'] == cells and not device['battery']['enabled']
    endpoint = '/api/devices/' + device['id']
    profile = PROFILE | {'series_cells': cells}
    response = await admin.put(endpoint, json={'battery': profile})
    assert response.status == 200
    assert (await response.json())['battery_status']['estimated_percent'] is None
    settings_url = path(device['urls']['settings'])
    before = await (await frames.get(settings_url)).json()
    response = await frames.get(settings_url, headers={'X-Display-Battery-Millivolts': str(cells * 1400)})
    assert await response.json() == before
    public = await (await admin.get(endpoint)).json()
    assert public['battery_status']['estimated_percent'] == 50
    assert public['health']['battery_estimate'] is None  # No completed image delivery.
    payload = manager.mqtt.payload(manager.store.get('device', device['id']))
    assert payload['battery_estimate'] == 50 and payload['battery_attributes']['source'] == 'linear_voltage'
    assert payload['battery_attributes']['measurement_time']
    assert 'charge_estimate' not in payload and 'charge_attributes' not in payload
    messages = manager.mqtt.desired(manager.mqtt.config)
    configs = [json.loads(data[0]) for topic, data in messages.items() if topic.endswith('/config')]
    charge = next(c for c in configs if c['name'] == 'Battery Level')
    assert len([c for c in configs if c.get('device_class') == 'battery']) == 1
    assert charge['device_class'] == 'battery' and charge['unit_of_measurement'] == '%'
    # Turning estimation off retains raw voltage and falls back to activity health.
    await admin.put(endpoint, json={'battery': {'enabled': False}})
    public = await (await admin.get(endpoint)).json()
    assert public['battery_status']['estimated_percent'] is None
    assert public['telemetry']['battery_millivolts'] == cells * 1400
    assert not any(topic.endswith('/charge_estimate/config') for topic in manager.mqtt.desired(manager.mqtt.config))

    payload = manager.mqtt.payload(manager.store.get('device', device['id']))
    assert payload['battery_estimate'] is None
    assert payload['battery_attributes']['source'] == 'image_fetch_watchdog'


def forecast_device(**changes):
    return {'id': 'test', 'profile': 'openpaper_l', 'battery': PROFILE,
            'interval': 21600, 'paused': False, 'enabled': True} | changes


def discharge(forecast, device, *, count=11, slope=40):
    start = 1800000000
    for day in range(count):
        forecast.record(device, 5800 - day * slope, start + day * 86400)
    return start + (count - 1) * 86400


def test_forecast_requires_reliable_data_and_is_ram_only():
    device = forecast_device()
    forecast = battery.Forecast()
    assert forecast.estimate(device, 1800000000) is None
    now = discharge(forecast, device)
    result = forecast.estimate(device, now)
    assert result['remaining_days'] == 15
    assert result['remaining_refreshes'] == 60
    assert battery.Forecast().estimate(device, now) is None
    assert forecast.estimate(device, now + 3 * 86400) is None
    assert forecast.estimate(device | {'paused': True}, now) is None
    assert forecast.estimate(device | {'battery': PROFILE | {'full_voltage': 1.7}}, now) is None
    forecast.record(device, 6200, now + 3600)
    assert forecast.estimate(device, now + 3600) is None


@pytest.mark.parametrize('slope,count', [(0, 11), (-10, 11), (40, 3), (1, 11)])
def test_forecast_hides_flat_rising_short_and_small_changes(slope, count):
    device = forecast_device()
    forecast = battery.Forecast()
    now = discharge(forecast, device, count=count, slope=slope)
    assert forecast.estimate(device, now) is None


def test_forecast_uses_quiet_hours_and_bounds_history():
    device = forecast_device(schedule={'quiet_enabled': True, 'quiet_start': '00:00',
                                       'quiet_end': '12:00', 'timezone': 'UTC'})
    forecast = battery.Forecast()
    now = discharge(forecast, device)
    assert forecast.estimate(device, now)['remaining_refreshes'] < 60
    for hour in range(2400):
        forecast.record(device, 5400, now + hour * 3600)
    assert len(forecast.histories['test']['samples']) <= 2161


def test_forecast_hides_noisy_discharge():
    device = forecast_device()
    forecast = battery.Forecast()
    now = discharge(forecast, device)
    for day in range(11):
        forecast.record(device, 5600 + (day % 2) * 100, now + day * 86400)
    assert forecast.estimate(device, now + 10 * 86400) is None


async def test_forecast_is_exposed_in_device_status_and_mqtt_attributes(system, monkeypatch):
    manager, admin, frames = system
    device = await (await admin.post('/api/devices', json={'name': 'Forecast frame', 'profile': 'openpaper_l'})).json()
    endpoint = '/api/devices/' + device['id']
    await admin.put(endpoint, json={'battery': PROFILE, 'interval': 21600})
    stored = manager.store.get('device', device['id'])
    now = discharge(manager.battery_forecast, stored)
    monkeypatch.setattr('server.time.time', lambda: now)
    response = await frames.get(path(device['urls']['settings']), headers={'X-Display-Battery-Millivolts': '5400'})
    assert response.status == 200
    detail = await (await admin.get(endpoint)).json()
    assert detail['battery_status']['forecast']['remaining_days'] == 15
    status = await (await admin.get(endpoint + '/status')).json()
    assert status['battery_status']['forecast'] == detail['battery_status']['forecast']
    payload = manager.mqtt.payload(stored)
    assert payload['battery_attributes']['forecast']['remaining_refreshes'] == 60
    await admin.delete(endpoint)
    assert stored['id'] not in manager.battery_forecast.histories
