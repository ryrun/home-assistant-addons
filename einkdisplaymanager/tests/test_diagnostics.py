from diagnostics import Diagnostics
from storage import Store


def test_device_events_are_bounded_separate_persistent_and_filter_request_details(tmp_path):
    store = Store(tmp_path)
    diagnostics = Diagnostics(store)
    for i in range(120):
        diagnostics.event('first', 'test_event', 'Static message.', http_status=200,
                          token='secret-token', url='http://host/image?k=secret-token')
    diagnostics.event('second', 'other_event', 'Other device.')
    first = diagnostics.view('first')
    assert len(first['events']) == 100
    assert first['events'][0]['id'] == 21 and first['events'][-1]['id'] == 120
    assert 'secret-token' not in str(first)
    assert len(diagnostics.view('second')['events']) == 1
    store.close()
    reopened = Store(tmp_path)
    try:
        assert Diagnostics(reopened).view('first') == first
    finally:
        reopened.close()


def test_restart_marks_unfinished_transfer_without_claiming_a_byte_count(tmp_path):
    store = Store(tmp_path)
    diagnostics = Diagnostics(store)
    diagnostics.start('device', 960118, 'entry', 'asset', 'image/bmp')
    diagnostics.update('device', bytes_written=65536)
    assert diagnostics.view('device')['transfer']['bytes_written'] == 65536
    store.close()
    reopened = Store(tmp_path)
    try:
        recovered = Diagnostics(reopened).view('device')
        assert recovered['transfer']['status'] == 'interrupted'
        assert recovered['transfer']['error_code'] == 'restart'
        assert recovered['transfer']['progress_known'] is False
        assert recovered['events'][-1]['event'] == 'image_interrupted'
    finally:
        reopened.close()
