"""Allowlisted device-request telemetry. Invalid fields never block delivery."""

import re

FIELDS = {
    'usb_connected': ('USB-Connected', {'0': False, '1': True}),
    'charging': ('Charging', {'0': False, '1': True}),
    'reported_display': ('Display', {'epd7': 'epd7', 'epd13': 'epd13'}),
    'wakeup_reason': ('Wakeup', {key: key for key in ('timer', 'button', 'motion', 'reset')}),
    'sensor_orientation': ('Orientation', {str(value): value for value in range(4)}),
}


def parse(headers):
    result = {}
    for key, (suffix, choices) in FIELDS.items():
        value = headers.get('X-OpenPaper-' + suffix)
        if value in choices:
            result[key] = choices[value]
    # Preserve the generic Inkplate contract and the original OpenPaper alias.
    voltage = headers.get('X-Display-Battery-Millivolts', headers.get('X-OpenPaper-Battery-Millivolts', ''))
    if 1 <= len(voltage) <= 6 and voltage.isascii() and voltage.isdecimal() and 500 <= int(voltage) <= 200000:
        result['battery_millivolts'] = int(voltage)
    version = headers.get('X-OpenPaper-Firmware-Version', '')
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}', version):
        result['firmware_version'] = version
    rssi = headers.get('X-OpenPaper-WiFi-RSSI', '')
    if re.fullmatch(r'-?[0-9]{1,3}', rssi) and -127 <= int(rssi) <= 0:
        result['wifi_rssi'] = int(rssi)
    return result
