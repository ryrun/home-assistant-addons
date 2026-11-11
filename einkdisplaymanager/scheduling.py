"""Optional local wall-clock grids and daily quiet hours, independent of playback."""

import math
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = {'anchor_enabled': False, 'anchor_time': '03:00', 'anchor_date': '1970-01-01',
            'quiet_enabled': False, 'quiet_start': '22:00', 'quiet_end': '06:00', 'timezone': 'UTC'}
DAY = 86400


def config(device):
    return DEFAULTS | device.get('schedule', {})


def active(device):
    settings = config(device)
    return settings['anchor_enabled'] or settings['quiet_enabled']


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use a local time in HH:MM format.')
    return time.fromisoformat(value)


def validate(value, interval):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Unsupported refresh schedule setting.')
    result = DEFAULTS | value
    for key in ('anchor_enabled', 'quiet_enabled'):
        if type(result[key]) is not bool:
            raise ValueError('Schedule switches must be true or false.')
    for key in ('anchor_time', 'quiet_start', 'quiet_end'):
        clock(result[key])
    try:
        if not isinstance(result['timezone'], str) or len(result['timezone']) > 80:
            raise ValueError
        ZoneInfo(result['timezone'])
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Choose a valid IANA time zone, such as Europe/Berlin.') from None
    try:
        if not isinstance(result['anchor_date'], str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', result['anchor_date']):
            raise ValueError
        parsed = date.fromisoformat(result['anchor_date'])
        if not 1970 <= parsed.year <= 2100:
            raise ValueError
    except ValueError:
        raise ValueError('Use an anchor date in YYYY-MM-DD format between 1970 and 2100.') from None
    if result['quiet_enabled'] and result['quiet_start'] == result['quiet_end']:
        raise ValueError('Quiet hours must leave part of the day available for refreshes.')
    if result['anchor_enabled'] and result['quiet_enabled']:
        def seconds(value):
            t = clock(value)
            return t.hour * 3600 + t.minute * 60
        start, end = seconds(result['quiet_start']), seconds(result['quiet_end'])
        windows = [(0, start), (end, DAY)] if start < end else [(end, start)]
        step = math.gcd(interval, DAY)
        phase = seconds(result['anchor_time']) % step
        if not any(phase + math.ceil((low - phase) / step) * step < high for low, high in windows):
            raise ValueError('All anchored refresh slots fall inside quiet hours. Change the anchor, interval, or quiet hours.')
    return result


def is_quiet(device, now):
    settings = config(device)
    if not settings['quiet_enabled']:
        return False
    local = datetime.fromtimestamp(now, ZoneInfo(settings['timezone'])).time()
    start, end = clock(settings['quiet_start']), clock(settings['quiet_end'])
    return start <= local < end if start < end else local >= start or local < end


def _quiet_end(settings, local):
    end = clock(settings['quiet_end'])
    day = local.date() + timedelta(days=local.time() >= end)
    return datetime.combine(day, end)


def _timestamp(local, zone, *, fold=0):
    return local.replace(tzinfo=zone, fold=fold).timestamp()


def _end_timestamp(local, zone, not_before):
    # A quiet-hours end in a spring gap moves to the first valid local minute.
    # In an autumn fold, select the first real occurrence still in the future.
    for _ in range(1500):
        candidates = [_timestamp(local, zone, fold=fold) for fold in (0, 1)]
        valid = [stamp for stamp in candidates if stamp >= not_before and
                 datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) == local]
        if valid:
            return min(valid)
        local += timedelta(minutes=1)
    raise ValueError('Quiet hours end could not be resolved in this time zone.')


@lru_cache(maxsize=64)
def _allowed_slots(interval, anchor_seconds, quiet_start, quiet_end):
    """A bounded byte map of one repeating local-clock phase cycle (<=86400)."""
    start, end = clock(quiet_start), clock(quiet_end)
    start, end = start.hour * 3600 + start.minute * 60, end.hour * 3600 + end.minute * 60
    slots = bytearray(DAY // math.gcd(interval, DAY))
    for index in range(len(slots)):
        position = (anchor_seconds + index * interval) % DAY
        quiet = start <= position < end if start < end else position >= start or position < end
        slots[index] = not quiet
    return bytes(slots)


def next_due(device, now):
    """Strictly future target. Anchors use local time; missing DST slots are skipped."""
    settings = config(device)
    interval = device['interval']
    if not active(device):
        return now + interval
    zone = ZoneInfo(settings['timezone'])
    if not settings['anchor_enabled']:
        target = now + interval
        if is_quiet(device, target):
            local = datetime.fromtimestamp(target, zone).replace(tzinfo=None)
            target = _end_timestamp(_quiet_end(settings, local), zone, target)
        return target
    anchor = datetime.combine(date.fromisoformat(settings['anchor_date']), clock(settings['anchor_time']))
    local_now = datetime.fromtimestamp(now, zone).replace(tzinfo=None)
    index = math.floor((local_now - anchor).total_seconds() / interval) + 1
    slots = b'\x01'
    if settings['quiet_enabled']:
        slots = _allowed_slots(interval, anchor.hour * 3600 + anchor.minute * 60,
                               settings['quiet_start'], settings['quiet_end'])
    for _ in range(2000):
        cycle, position = divmod(index, len(slots))
        allowed = slots.find(b'\x01', position)
        if allowed < 0:
            cycle += 1
            allowed = slots.find(b'\x01')
        if allowed < 0:
            raise ValueError('All anchored refresh slots fall inside quiet hours.')
        index = cycle * len(slots) + allowed
        candidate = anchor + timedelta(seconds=index * interval)
        target = _timestamp(candidate, zone)
        normalized = datetime.fromtimestamp(target, zone).replace(tzinfo=None)
        if normalized != candidate:
            # Spring-forward gaps (including date-line changes) have no real slot.
            jump = math.ceil((normalized - anchor).total_seconds() / interval)
            index = max(index + 1, jump)
            continue
        if target <= now:
            index += 1  # Repeated autumn hour: choose the first occurrence once.
            continue
        return target
    raise ValueError('No permitted refresh slot could be found. Adjust the schedule.')


def sleep_seconds(device, now):
    if not active(device):
        return device['interval']
    return min(2592000, max(60, math.ceil(next_due(device, now) - now)))


def view(device, now):
    state = device['state']
    next_request = state.get('next_request_at')
    if not next_request and state.get('last_served_at'):
        next_request = state['last_served_at'] + device['interval']
    return {'enabled': active(device), 'timezone': config(device)['timezone'],
            'quiet_now': is_quiet(device, now),
            'next_connection_at': next_request if device['enabled'] else None,
            'next_slot_at': next_due(device, now), 'sleep_seconds': sleep_seconds(device, now)}
