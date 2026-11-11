"""Persisted, request-aware queues. Network delivery completion is tracked separately."""

import random

from scheduling import is_quiet, next_due, sleep_seconds


def enabled(device):
    return [e['id'] for e in device['entries'] if e['enabled']]


def initial_state():
    return {'queue': [], 'selected': None, 'pending': False, 'deadline': 0,
            'cycle': 1, 'last_served_entry': None, 'last_served_hash': None,
            'last_served_at': None, 'last_image_request': None, 'last_settings_request': None,
            'last_error': None}


def reconcile(device):
    state = device['state']
    eligible = enabled(device)
    state['queue'] = [i for i in state['queue'] if i in eligible]
    if state['last_served_at'] is None and state['cycle'] == 1:
        state['queue'] = eligible.copy()
    if state['selected'] not in eligible:
        state.update(selected=None, pending=False, deadline=0)
    if not state['queue']:
        state['queue'] = eligible.copy()
    if state['selected'] is None and state['queue']:
        state.update(selected=state['queue'][0], pending=True)


def advance(device, direction=1, rng=None):
    state = device['state']
    reconcile(device)
    queue = state['queue']
    if not queue:
        return
    index = queue.index(state['selected'])
    if direction < 0:
        selected = queue[max(0, index - 1)]
    elif index + 1 < len(queue):
        selected = queue[index + 1]
    else:
        previous = state['selected']
        queue = enabled(device)
        if device['shuffle'] and len(queue) > 1:
            (rng or random.SystemRandom()).shuffle(queue)
            previous_entry = next(e for e in device['entries'] if e['id'] == previous)
            def identity(identifier):
                entry = next(e for e in device['entries'] if e['id'] == identifier)
                return entry.get('variant_id') or entry['asset_id']
            old_image = previous_entry.get('variant_id') or previous_entry['asset_id']
            alternative = next((i for i, item in enumerate(queue) if identity(item) != old_image), None)
            if identity(queue[0]) == old_image and alternative is not None:
                queue[0], queue[alternative] = queue[alternative], queue[0]
        state['queue'] = queue
        state['cycle'] += 1
        selected = queue[0]
    state.update(selected=selected, pending=True)


def select_for_request(device, now):
    reconcile(device)
    state = device['state']
    if not device['paused'] and not is_quiet(device, now) and not state['pending'] and now >= state['deadline']:
        advance(device)
    return state['selected']


def completed(device, output_hash, now):
    state = device['state']
    state.update(last_served_entry=state['selected'], last_served_hash=output_hash,
                 last_served_at=now, last_error=None)
    if state['pending']:
        state.update(pending=False, deadline=next_due(device, now))
    state['expected_image_at'] = next_due(device, now)
    state['next_request_at'] = now + sleep_seconds(device, now)
