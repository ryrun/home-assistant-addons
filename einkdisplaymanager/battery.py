"""Per-cell capacity curves and RAM-only forecasts, separate from fetch health."""

import math
from itertools import pairwise

from profiles import device_profile

CHEMISTRIES = {'custom', 'alkaline', 'nimh', 'li_ion', 'lifepo4'}
# Coarse engineering reference profiles, not standardized cell calibrations.
# Source context and limitations: DOCS.md, "Battery estimation methods".
CURVES = {
    'alkaline': ((1.00, 0), (1.10, 10), (1.20, 25), (1.25, 40), (1.30, 55),
                 (1.35, 70), (1.40, 80), (1.45, 90), (1.50, 95), (1.60, 100)),
    'nimh': ((1.00, 0), (1.10, 5), (1.18, 10), (1.22, 20), (1.25, 40),
             (1.28, 60), (1.31, 80), (1.35, 90), (1.40, 100)),
    'li_ion': ((3.00, 0), (3.30, 5), (3.50, 10), (3.60, 20), (3.70, 35),
               (3.80, 55), (3.90, 75), (4.00, 85), (4.10, 95), (4.20, 100)),
    'lifepo4': ((2.80, 0), (3.10, 5), (3.20, 10), (3.25, 20), (3.28, 40),
                (3.30, 60), (3.32, 80), (3.35, 90), (3.40, 100)),
}
DEFAULTS = {'enabled': False, 'chemistry': 'custom', 'series_cells': 1,
            'empty_voltage': None, 'full_voltage': None, 'method': 'linear', 'curve': []}


def curve(settings):
    if settings['method'] == 'chemistry':
        return CURVES[settings['chemistry']]
    if settings['method'] == 'custom':
        return settings['curve']
    return ((settings['empty_voltage'], 0), (settings['full_voltage'], 100))


def signature(settings):
    return tuple((key, tuple(tuple(point) for point in value) if key == 'curve' else value)
                 for key, value in sorted(settings.items()))


def capacity(settings, millivolts):
    """Unrounded percentage; clamp outside the selected per-cell curve."""
    voltage = millivolts / 1000 / settings['series_cells']
    points = curve(settings)
    if voltage <= points[0][0]:
        return 0.0
    for (low_v, low_p), (high_v, high_p) in pairwise(points):
        if voltage <= high_v:
            return low_p + (high_p - low_p) * (voltage - low_v) / (high_v - low_v)
    return 100.0



def config(device):
    return DEFAULTS | {'series_cells': device_profile(device).get('battery_cells', 1)} | device.get('battery', {})


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Unsupported battery profile setting.')
    result = DEFAULTS | value
    if type(result['enabled']) is not bool or not isinstance(result['chemistry'], str) or result['chemistry'] not in CHEMISTRIES:
        raise ValueError('Choose a supported battery chemistry and enable switch.')
    count = result['series_cells']
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError('Use between 1 and 32 cells in series. Parallel cells do not increase this count.')
    if result['method'] not in ('linear', 'chemistry', 'custom'):
        raise ValueError('Choose Chemistry profile, Linear, or Custom curve.')
    if result['enabled'] and result['method'] == 'chemistry' and result['chemistry'] not in CURVES:
        raise ValueError('Choose a supported cell chemistry for the chemistry profile.')
    for key in ('empty_voltage', 'full_voltage'):
        number = result[key]
        if number is None and (not result['enabled'] or result['method'] != 'linear'):
            continue
        if type(number) not in (int, float) or not 0.1 <= number <= 6 or not math.isfinite(number):
            raise ValueError('Enter the empty and full voltage per cell, between 0.1 and 6 V.')
    if result['empty_voltage'] is not None and result['full_voltage'] is not None and result['empty_voltage'] >= result['full_voltage']:
        raise ValueError('Full voltage must be greater than empty voltage.')
    points = result['curve']
    if not isinstance(points, list) or len(points) > 32:
        raise ValueError('Use 2 to 32 custom curve points.')
    if points or (result['enabled'] and result['method'] == 'custom'):
        if len(points) < 2:
            raise ValueError('Use 2 to 32 custom curve points.')
        for point in points:
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or any(type(number) not in (int, float) or not 0 <= number <= 6_000 or not math.isfinite(number)
                           for number in point)
                    or not .1 <= point[0] <= 6 or not 0 <= point[1] <= 100):
                raise ValueError('Each curve point must contain voltage per cell (0.1–6 V) and percent (0–100).')
        if points[0][1] != 0 or points[-1][1] != 100:
            raise ValueError('The curve must start at 0% and end at 100%.')
        if any(a[0] >= b[0] or a[1] >= b[1] for a, b in pairwise(points)):
            raise ValueError('Curve voltage and percentage must both increase strictly, without duplicates.')
    return result


def status(device, telemetry):
    settings = config(device)
    millivolts = telemetry.get('battery_millivolts')
    cell_voltage = millivolts / 1000 / settings['series_cells'] if millivolts is not None else None
    percentage = None
    if settings['enabled'] and cell_voltage is not None:
        percentage = round(capacity(settings, millivolts))
    return {'estimated_percent': percentage, 'cell_voltage': cell_voltage,
            'measured_at': telemetry.get('measured_at'),
            'source': {'linear': 'linear_voltage', 'chemistry': 'chemistry_curve', 'custom': 'custom_curve'}[settings['method']],
            'method': settings['method'],
            'chemistry': settings['chemistry'], 'estimated': True}


MIN_READING_GAP = 1800
HISTORY_SECONDS = 90 * 86400
FORECAST_SAVED_READINGS = 256
POWER_FIELDS = ('usb_connected', 'charging')


def power_status(telemetry, interval, now):
    """An older power report describes past state, not the current voltage reading."""
    updated = telemetry.get('field_updated_at', {})
    measured = telemetry.get('measured_at') or 0
    stale = []
    external = False
    for key in POWER_FIELDS:
        if telemetry.get(key) is None:
            continue
        reported = updated.get(key)
        if (reported is None or now - reported > max(2 * interval, 2 * 86400)
                or measured - reported >= MIN_READING_GAP):
            stale.append(key)
        elif telemetry[key]:
            external = True
    return external, stale


class Forecast:
    """Bounded discharge history with a compact checkpoint for restarts."""

    def __init__(self):
        self.histories = {}

    def restore(self, device, telemetry, now):
        settings = config(device)
        if not settings['enabled'] or device['id'] in self.histories:
            return
        samples = telemetry.get('forecast_readings', [])
        if not samples and (seed := telemetry.get('forecast_seed')):
            samples = [(seed['measured_at'], seed['battery_millivolts'])]
        if samples and 0 <= now - samples[-1][0] <= max(2 * device['interval'], 2 * 86400):
            retained = {t: (t, voltage) for t, voltage in samples[-FORECAST_SAVED_READINGS:]
                        if now - HISTORY_SECONDS <= t <= now}
            self.histories[device['id']] = {'signature': signature(settings), 'samples': retained}

    def checkpoint(self, identifier):
        samples = self.histories[identifier]['samples']
        return list(samples.values())[-FORECAST_SAVED_READINGS:]

    def record(self, device, millivolts, now):
        from statistics import median

        settings = config(device)
        if not settings['enabled']:
            self.histories.pop(device['id'], None)
            return False
        current_signature = signature(settings)
        history = self.histories.get(device['id'])
        points = curve(settings)
        span = 1000 * settings['series_cells'] * (points[-1][0] - points[0][0])
        if history is None or history['signature'] != current_signature:
            history = {'signature': current_signature, 'samples': {}}
            self.histories[device['id']] = history
        samples = history['samples']
        # Keep the first reading from a short burst, even across clock hours.
        if samples and now - next(reversed(samples)) < MIN_READING_GAP:
            return False
        recent = [v for t, v in samples.values() if now - t < 3 * 86400]
        # Charging or replacement invalidates the previous discharge cycle.
        if recent and millivolts > median(recent) + span * .1:
            samples.clear()
        samples[now] = (now, millivolts)
        for timestamp in list(samples):
            if timestamp < now - HISTORY_SECONDS:
                del samples[timestamp]
        return True

    def estimate(self, device, now):
        forecast, _ = self.assess(device, now)
        return forecast

    def assess(self, device, now):
        """Return the forecast and the reason or evidence behind its availability."""
        from statistics import median

        import scheduling

        history = self.histories.get(device['id'])
        settings = config(device)
        samples = sorted(history['samples'].values()) if (
            history and settings['enabled'] and history['signature'] == signature(settings)
        ) else []
        span = samples[-1][0] - samples[0][0] if samples else 0
        progress = {'sample_count': len(samples), 'minimum_samples': 2,
                    'observation_seconds': span, 'minimum_observation_seconds': MIN_READING_GAP}

        def waiting(reason):
            return None, progress | {'reason': reason}

        if device.get('paused') or not device.get('enabled', True):
            return waiting('inactive')
        if samples and now - samples[-1][0] > max(2 * device['interval'], 2 * 86400):
            return waiting('stale')
        if len(samples) < 2:
            return waiting('collecting')
        if span < progress['minimum_observation_seconds']:
            return waiting('too_close')
        daily = {}
        for timestamp, voltage in samples:
            daily.setdefault(int(timestamp // 86400), []).append((timestamp, capacity(settings, voltage)))
        points = [(median(t for t, _ in values) / 86400, median(v for _, v in values))
                  for _, values in sorted(daily.items())]
        established = len(points) >= 5 and points[-1][0] - points[0][0] >= 4
        if not established:
            points = sorted((timestamp / 86400, capacity(settings, voltage)) for timestamp, voltage in samples)
        mean_x = sum(x for x, _ in points) / len(points)
        mean_y = sum(y for _, y in points) / len(points)
        xx = sum((x - mean_x) ** 2 for x, _ in points)
        yy = sum((y - mean_y) ** 2 for _, y in points)
        xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
        slope = xy / xx
        fit = xy * xy / (xx * yy) if yy else 0
        decline = -slope * (points[-1][0] - points[0][0])
        if slope >= 0 or decline < .2 or max(v for _, v in samples) - min(v for _, v in samples) < 5:
            return waiting('no_decline')
        if fit < .6:
            # Confirm that the early and late portions agree with the overall
            # direction. Their medians are less sensitive to middle fluctuations.
            recent_points = points[-7:]
            window = max(1, len(recent_points) // 3)
            early = recent_points[:window]
            late = recent_points[-window:]
            start_day = median(day for day, _ in early)
            mean_x = median(day for day, _ in late)
            mean_y = median(value for _, value in late)
            change = median(value for _, value in early) - mean_y
            if change < .2:
                return waiting('noisy')
            slope = -change / (mean_x - start_day)
        established = established and fit >= .8 and decline >= 3
        remaining = (mean_y + slope * (now / 86400 - mean_x)) / -slope
        if remaining <= 0:
            return waiting('below_range')
        beyond_horizon = remaining > 365
        remaining = min(remaining, 365)
        if beyond_horizon:
            established = False
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
                'estimated': True, 'source': 'capacity_trend', 'method': settings['method'],
                'confidence': 'established' if established else 'preliminary',
                'sample_count': len(samples), 'observation_days': round(span / 86400, 2),
                'beyond_horizon': beyond_horizon, 'noisy_readings': fit < .6}, progress | {'reason': 'estimated'}
