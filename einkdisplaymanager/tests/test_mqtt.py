import asyncio
import contextlib
import json
import shutil
import socket
import time

import aiomqtt
import pytest
from aiohttp import ClientError, web
from mqtt_bridge import DEFAULTS, ENTITIES, MQTTBridge, fetch_health, validate_config
from server import VERSION, Manager
from test_http import device, path, upload


def frame():
    return {'enabled': True, 'paused': False, 'entries': [{'enabled': True}], 'interval': 60,
            'state': {'last_served_at': None}}


def test_watchdog_unknown_first_deadline_success_and_overdue_boundary():
    d, watch = frame(), {'started_at': 1000}
    assert fetch_health(d, watch, 1180, 120)['battery_estimate'] is None
    assert fetch_health(d, watch, 1180.1, 120)['battery_estimate'] == 0
    d['state']['last_served_at'] = 1170
    assert fetch_health(d, watch, 1200, 120)['battery_estimate'] == 100
    assert fetch_health(d, watch, 1350.1, 120)['battery_estimate'] == 0


@pytest.mark.parametrize('decay', [300, 86400])
def test_activity_battery_declines_linearly_and_only_alarms_at_zero(decay):
    d, watch = frame(), {'started_at': 1000}
    d['state']['last_served_at'] = 1000
    start = 1180  # 60-second interval plus the existing 120-second tolerance.
    assert fetch_health(d, watch, start, 120, decay)['battery_estimate'] == 100
    for fraction, percent in ((.25, 75), (.5, 50), (.75, 25)):
        result = fetch_health(d, watch, start + decay * fraction, 120, decay)
        assert result['battery_estimate'] == percent
        assert result['frame_status'] == 'late' and not result['update_overdue']
        assert result['decline_starts_at'] == start
        assert result['overdue_at'] == start + decay
    almost = fetch_health(d, watch, start + decay - .01, 120, decay)
    assert almost['battery_estimate'] == 1 and not almost['update_overdue']
    for now in (start + decay, start + decay * 2):
        result = fetch_health(d, watch, now, 120, decay)
        assert result['battery_estimate'] == 0
        assert result['frame_status'] == 'overdue' and result['update_overdue']


def test_new_frame_remains_unknown_during_decline_until_full_alarm_deadline():
    d, watch = frame(), {'started_at': 1000}
    result = fetch_health(d, watch, 1330, 120, 300)
    assert result['frame_status'] == 'late'
    assert result['battery_estimate'] is None and not result['update_overdue']
    assert fetch_health(d, watch, 1480, 120, 300)['battery_estimate'] == 0


def test_increasing_decline_recalculates_existing_zero_and_survives_restart(tmp_path):
    manager = Manager(tmp_path, dev=True)
    d = frame() | {'id': 'decline-test'}
    d['state']['last_served_at'] = 1000
    manager.mqtt.health(d, now=1000)  # Persist the original monitoring anchor.
    assert manager.mqtt.config['battery_decay_seconds'] == 0
    assert manager.mqtt.health(d, now=1780)['battery_estimate'] == 0
    manager.mqtt.configure({'battery_decay_seconds': 1200})
    result = manager.mqtt.health(d, now=1780)
    assert result['battery_estimate'] == 50 and not result['update_overdue']
    manager.store.close()
    restored = Manager(tmp_path, dev=True)
    assert restored.mqtt.config['battery_decay_seconds'] == 1200
    assert restored.mqtt.health(d, now=1780) == result
    assert restored.mqtt.health(d, now=2080)['battery_estimate'] == 25
    restored.mqtt.configure({'battery_decay_seconds': 300})
    assert restored.mqtt.health(d, now=1780)['update_overdue']
    restored.mqtt.configure({'battery_decay_seconds': 0})
    assert restored.mqtt.health(d, now=1780)['battery_estimate'] == 0
    restored.store.close()


@pytest.mark.parametrize('bad', [-1, 2592001, True, '300', 1.5, None])
def test_decline_period_requires_bounded_whole_seconds(bad):
    with pytest.raises(ValueError, match='Activity battery decline period'):
        validate_config({'battery_decay_seconds': bad}, DEFAULTS)


@pytest.mark.parametrize('change,expected', [({'enabled': False}, 'disabled'), ({'paused': True}, 'paused'),
                                            ({'entries': []}, 'no_images'), ({'entries': [{'enabled': False}]}, 'no_images')])
@pytest.mark.parametrize('decay', [0, 300, 86400])
def test_inactive_frames_have_no_fake_empty_battery_alarm(change, expected, decay):
    d = frame() | change
    result = fetch_health(d, {'started_at': 1000}, 999999, 120, decay)
    assert result['frame_status'] == expected
    assert result['battery_estimate'] is None and not result['update_overdue']


def test_legacy_watchdog_config_defaults_to_immediate_decline(tmp_path):
    manager = Manager(tmp_path, dev=True)
    manager.mqtt.configure({'grace_seconds': 300, 'password': 'legacy-secret'})
    saved = manager.store.get('mqtt', 'config')
    saved.pop('battery_decay_seconds')
    manager.store.save('mqtt', saved)
    manager.store.close()
    restored = Manager(tmp_path, dev=True)
    assert restored.mqtt.config['battery_decay_seconds'] == 0
    assert restored.mqtt.config['grace_seconds'] == 300
    assert restored.mqtt.config['password'] == 'legacy-secret'
    restored.store.close()


def test_mqtt_validation_and_private_persistent_password(tmp_path):
    for bad in ({'broker': 'mqtt://example.com'}, {'broker': 'host:1883'}, {'port': True},
                {'enabled': 'yes'}, {'discovery_prefix': 'homeassistant/#'}, {'grace_seconds': 0}):
        with pytest.raises(ValueError):
            validate_config(bad, DEFAULTS)
    m = Manager(tmp_path, dev=True)
    m.mqtt.configure({'broker': '127.0.0.1', 'password': 'private-test-password'})
    instance = m.mqtt.instance
    m.store.close()
    restored = Manager(tmp_path, dev=True)
    assert restored.mqtt.instance == instance
    assert restored.mqtt.config['password'] == 'private-test-password'
    assert 'private-test-password' not in json.dumps(restored.mqtt.public())
    restored.mqtt.configure({'username': 'renamed'})
    assert restored.mqtt.config['password'] == 'private-test-password'
    restored.mqtt.configure({'clear_password': True})
    assert not restored.mqtt.public()['password_set']
    restored.store.close()


async def test_image_fetch_watchdog_ignores_settings_browsers_head_and_failed_auth(system):
    manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin, [a])
    endpoint = '/api/devices/' + d['id']
    response = await frames.get(path(d['urls']['image']))
    await response.read()
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 100
    persisted = manager.store.get('device', d['id'])
    persisted['state']['last_served_at'] = time.time() - 1000
    manager.store.save('device', persisted)
    watch = manager.store.get('mqtt_watch', d['id'])
    watch['started_at'] = time.time() - 1000
    manager.store.save('mqtt_watch', watch)
    await frames.get(path(d['urls']['settings']))
    await frames.head(path(d['urls']['image']))
    await (await frames.get(path(d['urls']['image']), headers={'Sec-Fetch-Mode': 'navigate'})).read()
    assert (await frames.get(path(d['urls']['image']) + 'invalid')).status == 401
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 0
    assert (await frames.get(path(d['urls']['image']), headers={'If-None-Match': response.headers['ETag']})).status == 304
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 100
    await admin.put(endpoint, json={'paused': True})
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] is None
    await admin.put(endpoint, json={'paused': False})
    assert (await (await admin.get(endpoint)).json())['health']['battery_estimate'] == 100


async def test_mqtt_api_does_not_return_passwords_or_expose_device_listener(system):
    _manager, admin, frames = system
    response = await admin.put('/api/mqtt', json={'broker': '192.0.2.10', 'password': 'secret-marker'})
    assert response.status == 200
    assert (await response.json())['password_set']
    assert 'secret-marker' not in await (await admin.get('/api/state')).text()
    assert 'secret-marker' not in await (await admin.get('/api/mqtt')).text()
    assert (await admin.put('/api/mqtt', json={'port': 0})).status == 400
    assert (await admin.put('/api/mqtt', json={'enabled': True}, headers={'X-Eink-CSRF': ''})).status == 403
    assert (await frames.get('/api/mqtt')).status != 200


async def test_interrupted_image_keeps_zero_estimate_until_a_successful_retry(system, monkeypatch):
    manager, admin, frames = system
    d = await device(admin, [await upload(admin)])
    watch = manager.store.get('mqtt_watch', d['id'])
    watch['started_at'] = time.time() - 1000
    manager.store.save('mqtt_watch', watch)
    original = web.StreamResponse.write
    async def interrupted(_response, _data):
        raise ConnectionResetError('Synthetic disconnect')
    monkeypatch.setattr(web.StreamResponse, 'write', interrupted)
    with contextlib.suppress(ClientError, ConnectionError):
        await (await frames.get(path(d['urls']['image']))).read()
    assert manager.mqtt.health(manager.store.get('device', d['id']))['battery_estimate'] == 0
    monkeypatch.setattr(web.StreamResponse, 'write', original)
    await (await frames.get(path(d['urls']['image']))).read()
    assert manager.mqtt.health(manager.store.get('device', d['id']))['battery_estimate'] == 100


class Broker:
    def __init__(self, root):
        self.binary = shutil.which('mosquitto')
        if not self.binary:
            pytest.skip('Install Mosquitto to run real-broker integration checks.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.config = root / 'mosquitto.conf'
        self.config.write_text(f'listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence true\npersistence_location {root}/\npersistence_file broker.db\n')
        self.process = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(self.binary, '-c', str(self.config),
                                                           stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        for _ in range(100):
            try:
                _reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(.02)
        raise RuntimeError('Disposable MQTT broker did not start.')

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()


@pytest.fixture
async def broker(tmp_path):
    result = Broker(tmp_path)
    await result.start()
    try:
        yield result
    finally:
        await result.stop()


class Observe:
    def __init__(self, port, **credentials):
        self.client = aiomqtt.Client('127.0.0.1', port, timeout=3, **credentials)
        self.latest, self.history, self.changed = {}, [], asyncio.Event()

    async def __aenter__(self):
        await self.client.__aenter__()
        await self.client.subscribe('#', qos=1)
        self.task = asyncio.create_task(self.listen())
        return self

    async def __aexit__(self, *args):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, aiomqtt.MqttError):
            await self.task
        await self.client.__aexit__(*args)

    async def listen(self):
        async for message in self.client.messages:
            topic, payload = str(message.topic), bytes(message.payload)
            self.latest[topic] = payload
            self.history.append((topic, payload))
            self.changed.set()

    async def until(self, predicate):
        async with asyncio.timeout(8):
            while True:
                self.changed.clear()
                if predicate():
                    return
                await self.changed.wait()


async def enable(manager, admin, broker, **overrides):
    manager.mqtt.tick = manager.mqtt.retry = .03
    response = await admin.put('/api/mqtt', json={'enabled': True, 'broker': '127.0.0.1', 'port': broker.port, **overrides})
    assert response.status == 200
    return manager.mqtt.base(manager.mqtt.config)


async def test_real_broker_discovery_activity_estimate_birth_and_graceful_offline(system, broker):
    manager, admin, frames = system
    a = await upload(admin)
    d = await device(admin, [a])
    async with Observe(broker.port) as observed:
        base = await enable(manager, admin, broker)
        topic = f"{base}/{d['id']}/state"
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        configs = {t: json.loads(p) for t, p in observed.latest.items() if t.endswith('/config')}
        assert len(configs) == len(ENTITIES)
        assert json.loads(observed.latest[topic])['battery_estimate'] is None
        assert 'token' not in d
        assert manager.store.get('device', d['id'])['token'] not in str(observed.latest)
        assert 'http://' not in json.dumps(configs)
        assert len({tuple(c['device']['identifiers']) for c in configs.values()}) == 1
        assert next(c for c in configs.values() if c['name'] == 'Battery Level')['entity_category'] == 'diagnostic'
        await (await frames.get(path(d['urls']['image']))).read()
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[topic])['battery_estimate'] == 100)
        persisted = manager.store.get('device', d['id'])
        persisted['state']['last_served_at'] = time.time() - 1000
        manager.store.save('device', persisted)
        watch = manager.store.get('mqtt_watch', d['id'])
        watch['started_at'] = time.time() - 1000
        manager.store.save('mqtt_watch', watch)
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[topic])['battery_estimate'] == 0)
        assert json.loads(observed.latest[topic])['update_overdue']
        before = len(observed.history)
        await observed.client.publish('homeassistant/status', 'online', qos=1)
        await observed.until(lambda: sum(t.endswith('/config') for t, _p in observed.history[before:]) == len(ENTITIES))
        await manager.mqtt.stop()
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'offline')
        # Lifecycle cleanup is idempotent.


async def test_real_broker_decline_changes_restore_estimate_without_reconnect(system, broker):
    manager, admin, frames = system
    d = await device(admin, [await upload(admin)])
    async with Observe(broker.port) as observed:
        base = await enable(manager, admin, broker)
        topic = f"{base}/{d['id']}/state"
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        response = await frames.get(path(d['urls']['image']))
        await response.read()
        etag = response.headers['ETag']
        persisted = manager.store.get('device', d['id'])
        persisted['state']['last_served_at'] = time.time() - 1000
        persisted['state']['last_settings_timeout'] = 60
        persisted['state']['expected_image_at'] = persisted['state']['last_served_at'] + 60
        manager.store.save('device', persisted)
        watch = manager.store.get('mqtt_watch', d['id'])
        watch['started_at'] = persisted['state']['last_served_at']
        manager.store.save('mqtt_watch', watch)
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[topic])['battery_estimate'] == 0)
        connected_at = manager.mqtt.connected_at
        before = len(observed.history)
        response = await admin.put('/api/mqtt', json={'battery_decay_seconds': 3600})
        assert response.status == 200
        await observed.until(lambda: 70 < json.loads(observed.latest[topic])['battery_estimate'] < 90)
        payload = json.loads(observed.latest[topic])
        assert payload['frame_status'] == 'late' and not payload['update_overdue']
        assert payload['battery_attributes']['battery_decay_seconds'] == 3600
        assert payload['battery_attributes']['decline_starts_at']
        status = await (await admin.get('/api/devices/' + d['id'] + '/status')).json()
        assert status['health']['battery_estimate'] == payload['battery_estimate']
        assert manager.mqtt.connected_at == connected_at
        assert not any(t == base + '/availability' for t, _p in observed.history[before:])
        response = await admin.put('/api/mqtt', json={'battery_decay_seconds': 300})
        assert response.status == 200
        await observed.until(lambda: json.loads(observed.latest[topic])['battery_estimate'] == 0)
        assert json.loads(observed.latest[topic])['update_overdue']
        await admin.put('/api/mqtt', json={'battery_decay_seconds': 86400})
        await observed.until(lambda: json.loads(observed.latest[topic])['frame_status'] == 'late')
        # Settings checks cannot repair image health, but an unchanged image can.
        await frames.get(path(d['urls']['settings']))
        assert manager.mqtt.health(manager.store.get('device', d['id']))['frame_status'] == 'late'
        assert (await frames.get(path(d['urls']['image']), headers={'If-None-Match': etag})).status == 304
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[topic])['battery_estimate'] == 100
                             and json.loads(observed.latest[topic])['frame_status'] == 'on_schedule')


async def test_retained_cleanup_prefix_change_discovery_toggle_and_device_deletion(system, broker):
    manager, admin, _frames = system
    d = await device(admin, [])
    async with Observe(broker.port) as observed:
        base = await enable(manager, admin, broker)
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        old_configs = {t: p for t, p in observed.latest.items() if t.endswith('/config')}
        response = await admin.put('/api/mqtt', json={'discovery_prefix': 'customha'})
        assert response.status == 200
        await observed.until(lambda: all(observed.latest[t] == b'' for t in old_configs))
        await observed.until(lambda: len([t for t, p in observed.latest.items() if t.startswith('customha/') and p]) == len(ENTITIES))
        new_configs = {t: p for t, p in observed.latest.items() if t.startswith('customha/') and p}
        assert {json.loads(p)['unique_id'] for p in new_configs.values()} == {json.loads(p)['unique_id'] for p in old_configs.values()}
        before = len(observed.history)
        await observed.client.publish('homeassistant/status', 'online', qos=1)
        await observed.until(lambda: len([t for t, p in observed.history[before:] if t.startswith('customha/') and p]) == len(ENTITIES))
        await admin.put('/api/mqtt', json={'discovery': False})
        await observed.until(lambda: all(observed.latest[t] == b'' for t in new_configs))
        assert observed.latest[f"{base}/{d['id']}/state"]
        await admin.delete('/api/devices/' + d['id'])
        await observed.until(lambda: observed.latest[f"{base}/{d['id']}/state"] == b'')
        await admin.put('/api/mqtt', json={'enabled': False})
        await observed.until(lambda: observed.latest[base + '/availability'] == b'')
        assert not manager.store.all('mqtt_registration')


async def test_offline_deletion_survives_bridge_restart_and_cleans_retained_broker_data(system, broker):
    manager, admin, _frames = system
    d = await device(admin, [])
    async with Observe(broker.port) as observed:
        base = await enable(manager, admin, broker)
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
    await broker.stop()
    await admin.delete('/api/devices/' + d['id'])
    await manager.mqtt.stop()
    instance = manager.mqtt.instance
    manager.mqtt = MQTTBridge(manager, VERSION, tick=.03, retry=.03)
    manager.mqtt.start()
    assert manager.mqtt.instance == instance
    assert manager.store.all('mqtt_registration')
    await broker.start()
    async with Observe(broker.port) as observed:
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        # The durable topic manifest drives deletion despite an empty device list.
        assert not [t for t in manager.store.all('mqtt_registration')[0]['topics'] if t.endswith('/config')]
        assert not [t for t, p in observed.latest.items() if p and t.endswith('/config')]


async def test_nonretained_discovery_replays_after_home_assistant_birth(system, broker):
    manager, admin, _frames = system
    await device(admin, [])
    async with Observe(broker.port) as observed:
        base = await enable(manager, admin, broker, discovery_retain=False)
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        before = len(observed.history)
        await observed.client.publish('homeassistant/status', 'online', qos=1)
        await observed.until(lambda: len([t for t, p in observed.history[before:] if t.endswith('/config') and p]) == len(ENTITIES))
        async with Observe(broker.port) as fresh:
            # Broker subscription replay contains retained state/availability, not configs.
            await fresh.client.publish('test/subscription-barrier', 'received', qos=1)
            await fresh.until(lambda: fresh.latest.get('test/subscription-barrier') == b'received')
            assert not any(t.endswith('/config') for t in fresh.latest)


async def test_real_broker_authentication_failure_is_redacted_and_recovers(system, broker, tmp_path):
    manager, admin, _frames = system
    password_tool = shutil.which('mosquitto_passwd')
    if not password_tool:
        pytest.skip('Mosquitto password tool is required for the authentication check.')
    await broker.stop()
    password_file = tmp_path / 'broker-passwords'
    process = await asyncio.create_subprocess_exec(password_tool, '-c', '-b', str(password_file),
                                                   'mqtt-test-user', 'broker-test-secret',
                                                   stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    assert await process.wait() == 0
    broker.config.write_text(broker.config.read_text().replace('allow_anonymous true', 'allow_anonymous false') + f'password_file {password_file}\n')
    await broker.start()
    await device(admin, [])
    await enable(manager, admin, broker, username='mqtt-test-user', password='wrong-test-secret')
    async with asyncio.timeout(5):
        while manager.mqtt.status != 'disconnected':
            await asyncio.sleep(.01)
    public = await (await admin.get('/api/mqtt')).json()
    assert public['error'] and 'wrong-test-secret' not in str(public)
    async with Observe(broker.port, username='mqtt-test-user', password='broker-test-secret') as observed:
        response = await admin.put('/api/mqtt', json={'password': 'broker-test-secret'})
        assert response.status == 200
        base = manager.mqtt.base(manager.mqtt.config)
        await observed.until(lambda: observed.latest.get(base + '/availability') == b'online')
        assert 'broker-test-secret' not in str(observed.latest)
        assert not manager.mqtt.error


async def test_switching_brokers_preserves_new_availability_and_retries_old_cleanup(system, broker, tmp_path):
    manager, admin, _frames = system
    await device(admin, [])
    second_root = tmp_path / 'second-broker'
    second_root.mkdir()
    second = Broker(second_root)
    await second.start()
    try:
        async with Observe(broker.port) as old:
            old_base = await enable(manager, admin, broker)
            await old.until(lambda: old.latest.get(old_base + '/availability') == b'online')
            old_ids = {json.loads(p)['unique_id'] for t, p in old.latest.items() if t.endswith('/config')}
        await broker.stop()
        async with Observe(second.port) as current:
            new_base = await enable(manager, admin, second)
            await current.until(lambda: current.latest.get(new_base + '/availability') == b'online')
            assert manager.mqtt.public()['pending_cleanup'] == 1
            assert {json.loads(p)['unique_id'] for t, p in current.latest.items() if t.endswith('/config')} == old_ids
            await broker.start()
            async with Observe(broker.port) as old:
                manager.mqtt.cleanup_wake.set()
                await old.until(lambda: old.latest.get(old_base + '/availability') == b'')
                async with asyncio.timeout(5):
                    while manager.mqtt.public()['pending_cleanup']:
                        await asyncio.sleep(.01)
                assert not [t for t, p in old.latest.items() if p and t.endswith('/config')]
                assert current.latest[new_base + '/availability'] == b'online'
            await admin.put('/api/mqtt', json={'enabled': False})
            await current.until(lambda: current.latest.get(new_base + '/availability') == b'')
    finally:
        await second.stop()


async def test_single_battery_level_prefers_voltage_and_cleans_old_charge_discovery(system, broker):
    from mqtt_bridge import destination
    from test_battery import PROFILE

    manager, admin, frames = system
    d = await device(admin, [await upload(admin)])
    config = validate_config({'enabled':True, 'broker':'127.0.0.1', 'port':broker.port},manager.mqtt.config)
    old_topic = f"homeassistant/sensor/{manager.mqtt.instance}_{destination(config)}_{d['id']}/charge_estimate/config"
    manager.store.save('mqtt_registration', {'id':destination(config), 'config':config, 'topics':{old_topic:True}})
    async with Observe(broker.port) as observed:
        await observed.client.publish(old_topic,json.dumps({'name':'Estimated charge from voltage'}),qos=1,retain=True)
        base = await enable(manager,admin,broker)
        state_topic = f"{base}/{d['id']}/state"
        await observed.until(lambda: observed.latest.get(old_topic)==b'' and state_topic in observed.latest)
        configs = [json.loads(p) for t,p in observed.latest.items() if t.endswith('/config') and p]
        batteries = [c for c in configs if c.get('device_class')=='battery']
        assert len(batteries)==1 and batteries[0]['name']=='Battery Level'
        assert batteries[0]['unique_id'].endswith('_battery_estimate')  # Preserve existing HA identity.
        assert old_topic not in manager.store.get('mqtt_registration',destination(config))['topics']
        await (await frames.get(path(d['urls']['image']))).read()
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[state_topic])['battery_estimate']==100)
        endpoint='/api/devices/'+d['id']
        assert (await admin.put(endpoint,json={'battery':PROFILE})).status==200
        await frames.get(path(d['urls']['settings']),headers={'X-Display-Battery-Millivolts':'5600'})
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[state_topic])['battery_estimate']==50)
        payload=json.loads(observed.latest[state_topic])
        assert payload['battery_attributes']['source']=='linear_voltage'
        assert payload['battery_attributes']['measurement_time']
        assert 'charge_estimate' not in payload
        await frames.get(path(d['urls']['settings']),headers={'X-Display-Battery-Millivolts':'4800'})
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[state_topic])['battery_estimate']==0)
        assert manager.mqtt.health(manager.store.get('device',d['id']))['battery_estimate']==100
        assert (await admin.put(endpoint,json={'battery':{'enabled':False}})).status==200
        manager.mqtt.wake.set()
        await observed.until(lambda: json.loads(observed.latest[state_topic])['battery_estimate']==100)
        payload=json.loads(observed.latest[state_topic])
        assert payload['battery_attributes']['source']=='image_fetch_watchdog'
        assert payload['battery_voltage']==4.8
