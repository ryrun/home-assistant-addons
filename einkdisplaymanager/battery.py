"""User-calibrated pack voltage estimates, kept separate from fetch health."""

import math

from profiles import display_profile

CHEMISTRIES = {'custom', 'alkaline', 'nimh', 'li_ion', 'lifepo4'}
DEFAULTS = {'enabled': False, 'chemistry': 'custom', 'series_cells': 1, 'empty_voltage': None, 'full_voltage': None}


def config(device):
    return DEFAULTS | {'series_cells': display_profile(device['profile']).get('battery_cells', 1)} | device.get('battery', {})


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Unsupported battery profile setting.')
    result = DEFAULTS | value
    if type(result['enabled']) is not bool or result['chemistry'] not in CHEMISTRIES:
        raise ValueError('Choose a supported battery chemistry and enable switch.')
    count = result['series_cells']
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError('Use between 1 and 32 cells in series. Parallel cells do not increase this count.')
    for key in ('empty_voltage', 'full_voltage'):
        number = result[key]
        if number is None and not result['enabled']:
            continue
        if type(number) not in (int, float) or not math.isfinite(number) or not 0.1 <= number <= 6:
            raise ValueError('Enter the empty and full voltage per cell, between 0.1 and 6 V.')
    if result['empty_voltage'] is not None and result['full_voltage'] is not None and result['empty_voltage'] >= result['full_voltage']:
        raise ValueError('Full voltage must be greater than empty voltage.')
    return result


def status(device, telemetry):
    settings = config(device)
    millivolts = telemetry.get('battery_millivolts')
    cell_voltage = millivolts / 1000 / settings['series_cells'] if millivolts is not None else None
    percentage = None
    if settings['enabled'] and cell_voltage is not None:
        percentage = round(max(0, min(100, (cell_voltage - settings['empty_voltage']) /
                                      (settings['full_voltage'] - settings['empty_voltage']) * 100)))
    return {'estimated_percent': percentage, 'cell_voltage': cell_voltage,
            'measured_at': telemetry.get('measured_at'), 'source': 'linear_voltage',
            'chemistry': settings['chemistry'], 'estimated': True}
