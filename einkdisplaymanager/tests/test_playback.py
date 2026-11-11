import copy
import random

import pytest
from playback import advance, completed, initial_state, reconcile, select_for_request


def frame(count=3, **kwargs):
    return dict(entries=[{'id': str(i), 'asset_id': str(i), 'variant_id': None, 'enabled': True} for i in range(count)],
                state=initial_state(), paused=False, shuffle=False, interval=60, **kwargs)


def test_deadlines_pending_retries_long_outage_and_restart():
    device = frame()
    assert select_for_request(device, 100) == '0'
    assert select_for_request(device, 10000) == '0'  # No completed transfer yet.
    completed(device, 'first', 10000)
    assert select_for_request(device, 10059) == '0'
    assert select_for_request(device, 50000) == '1'  # One step, not catch-up.
    restarted = copy.deepcopy(device)
    assert select_for_request(restarted, 60000) == '1'
    completed(restarted, 'second', 60000)
    assert select_for_request(restarted, 60001) == '1'


def test_ordered_first_cycle_then_shuffle_without_boundary_repeat():
    device = frame(8)
    device['shuffle'] = True
    seen = []
    for i in range(8):
        seen.append(select_for_request(device, i * 60))
        completed(device, str(i), i * 60)
    assert seen == list(map(str, range(8)))
    advance(device, rng=random.Random(5))
    assert device['state']['selected'] != '7'
    assert sorted(device['state']['queue']) == sorted(seen)
    assert device['state']['cycle'] == 2
    assert [e['id'] for e in device['entries']] == seen


def test_empty_single_two_pause_and_independent_devices():
    empty = frame(0)
    assert select_for_request(empty, 100) is None
    single = frame(1)
    for i in range(10):
        assert select_for_request(single, i * 60) == '0'
        completed(single, 'same', i * 60)
    two = frame(2)
    two['shuffle'] = True
    for i in range(10):
        assert select_for_request(two, i * 60) == str(i % 2)
        completed(two, str(i), i * 60)
    other = frame(2)
    other['paused'] = True
    assert select_for_request(other, 90000) == '0'
    completed(other, '0', 90000)
    assert select_for_request(other, 99999) == '0'


def test_mid_cycle_additions_wait_until_boundary_removals_apply_now():
    device = frame()
    select_for_request(device, 0)
    completed(device, '0', 0)
    device['entries'].append({'id': 'new', 'asset_id': 'new', 'enabled': True})
    reconcile(device)
    assert 'new' not in device['state']['queue']
    device['entries'][1]['enabled'] = False
    reconcile(device)
    assert device['state']['queue'] == ['0', '2']
    assert select_for_request(device, 60) == '2'
    completed(device, '2', 60)
    select_for_request(device, 120)
    assert device['state']['queue'] == ['0', '2', 'new']


def test_initial_setup_includes_images_added_before_first_delivery():
    device = frame(1)
    reconcile(device)
    device['entries'].append({'id': 'second', 'asset_id': 'second', 'enabled': True})
    reconcile(device)
    assert device['state']['queue'] == ['0', 'second']
    completed(device, '0', 0)
    assert select_for_request(device, 60) == 'second'


@pytest.mark.parametrize('shuffle', [False, True])
@pytest.mark.parametrize('edit_at_last', [False, True])
def test_two_image_cycle_finishes_after_expanding_and_reordering_base_list(shuffle, edit_at_last):
    device = frame(2)
    device['shuffle'] = shuffle
    assert select_for_request(device, 0) == '0'
    completed(device, '0', 0)
    if edit_at_last:
        assert select_for_request(device, 60) == '1'
        completed(device, '1', 60)

    device['entries'].extend(frame(9)['entries'][2:])
    device['entries'].reverse()
    reconcile(device)
    assert device['state']['queue'] == ['0', '1']
    # Persisted queues must retain their boundary across an add-on restart too.
    device = copy.deepcopy(device)
    if not edit_at_last:
        assert select_for_request(device, 60) == '1'
        completed(device, '1', 60)

    first = select_for_request(device, 120)
    assert device['state']['cycle'] == 2
    assert sorted(device['state']['queue']) == list(map(str, range(9)))
    assert first != '1'
    if not shuffle:
        assert device['state']['queue'] == list(map(str, reversed(range(9))))
    # Retrying the first image of the new cycle must not start another cycle.
    assert select_for_request(device, 121) == first
    assert device['state']['cycle'] == 2
    seen = []
    for index in range(9):
        selected = select_for_request(device, 180 + index * 60)
        seen.append(selected)
        completed(device, selected, 180 + index * 60)
    assert len(set(seen)) == 9
    assert device['state']['cycle'] == 2
    select_for_request(device, 720)
    assert device['state']['cycle'] == 3
