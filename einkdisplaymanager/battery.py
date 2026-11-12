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
        if type(number) not in (int, float) or not 0.1 <= number <= 6 or not math.isfinite(number):
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


class Forecast:
    """Bounded, RAM-only discharge observations; never use synthetic charge."""

    def __init__(self):
        self.histories = {}

    def record(self, device, millivolts, now):
        from statistics import median

        settings = config(device)
        if not settings['enabled']:
            self.histories.pop(device['id'], None)
            return
        signature = tuple(settings[key] for key in sorted(settings))
        history = self.histories.get(device['id'])
        span = 1000 * settings['series_cells'] * (settings['full_voltage'] - settings['empty_voltage'])
        if history is None or history['signature'] != signature:
            history = {'signature': signature, 'samples': {}}
            self.histories[device['id']] = history
        samples = history['samples']
        recent = [v for t, v in samples.values() if now - t < 3 * 86400]
        # Charging or replacement invalidates the previous discharge cycle.
        if recent and millivolts > median(recent) + span * .1:
            samples.clear()
        # At most one observation per hour, for at most 90 days.
        hour = int(now // 3600)
        samples[hour] = (now, millivolts)
        for key in list(samples):
            if key < hour - 90 * 24:
                del samples[key]

    def estimate(self, device, now):
        from statistics import median

        import scheduling

        history = self.histories.get(device['id'])
        settings = config(device)
        if (not history or not settings['enabled'] or device.get('paused') or not device.get('enabled', True)
                or history['signature'] != tuple(settings[key] for key in sorted(settings))):
            return None
        samples = list(history['samples'].values())
        if not samples or now - max(t for t, _ in samples) > max(2 * device['interval'], 2 * 86400):
            return None
        daily = {}
        for timestamp, voltage in samples:
            daily.setdefault(int(timestamp // 86400), []).append((timestamp, voltage))
        points = [(median(t for t, _ in values) / 86400, median(v for _, v in values))
                  for _, values in sorted(daily.items())]
        if len(points) < 5 or points[-1][0] - points[0][0] < 4:
            return None
        mean_x = sum(x for x, _ in points) / len(points)
        mean_y = sum(y for _, y in points) / len(points)
        xx = sum((x - mean_x) ** 2 for x, _ in points)
        yy = sum((y - mean_y) ** 2 for _, y in points)
        xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
        slope = xy / xx
        span = 1000 * settings['series_cells'] * (settings['full_voltage'] - settings['empty_voltage'])
        if slope >= 0 or yy == 0 or xy * xy / (xx * yy) < .8 or -slope * (points[-1][0] - points[0][0]) < span * .03:
            return None
        empty = settings['empty_voltage'] * settings['series_cells'] * 1000
        remaining = (mean_y + slope * (now / 86400 - mean_x) - empty) / -slope
        # Do not extrapolate distant horizons from a short observation period.
        if not 0 < remaining <= min(365, 3 * (points[-1][0] - points[0][0])):
            return None
        cutoff = now + remaining * 86400
        cursor, refreshes = now, 0
        # Bound computation for short refresh intervals and long forecasts.
        for _ in range(256):
            following = scheduling.next_due(device, cursor)
            if following > cutoff:
                break
            refreshes += 1
            cursor = following
        else:
            refreshes = round(remaining * 86400 / ((cursor - now) / refreshes))
        return {'remaining_days': round(remaining, 1), 'remaining_refreshes': refreshes,
                'estimated': True, 'source': 'voltage_trend'}
