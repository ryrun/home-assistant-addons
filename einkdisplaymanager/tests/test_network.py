from network import network_details


def test_suggested_host_and_changed_host_port():
    assert network_details({'hostname': 'homeassistant'}, {'network': {'8098/tcp': 8129}}) == {
        'host': 'homeassistant.local', 'device_port': 8129, 'detected': True}
    assert network_details({'hostname': 'ha.example.local'}, {'network': {'8098/tcp': None}}) == {
        'host': 'ha.example.local', 'device_port': None, 'detected': True}


def test_invalid_or_unavailable_discovery_keeps_safe_defaults():
    assert network_details({}, {}) == {'host': 'homeassistant.local', 'device_port': 8098, 'detected': False}
    assert network_details({'hostname': 'unsafe/host'}, {'network': {'8098/tcp': True}}) == network_details({}, {})
