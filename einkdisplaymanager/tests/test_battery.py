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
    assert payload['charge_estimate'] == 50 and payload['charge_attributes']['estimated']
    messages = manager.mqtt.desired(manager.mqtt.config)
    configs = [json.loads(data[0]) for topic, data in messages.items() if topic.endswith('/config')]
    charge = next(c for c in configs if c['name'] == 'Estimated charge from voltage')
    assert charge['device_class'] == 'battery' and charge['unit_of_measurement'] == '%'
    # Turning estimation off retains raw voltage, while charge becomes unknown.
    await admin.put(endpoint, json={'battery': {'enabled': False}})
    public = await (await admin.get(endpoint)).json()
    assert public['battery_status']['estimated_percent'] is None
    assert public['telemetry']['battery_millivolts'] == cells * 1400
    assert not any(topic.endswith('/charge_estimate/config') for topic in manager.mqtt.desired(manager.mqtt.config))
