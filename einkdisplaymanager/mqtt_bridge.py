"""MQTT discovery and an explicitly synthetic image-fetch battery indicator."""

import asyncio
import contextlib
import hashlib
import ipaddress
import json
import logging
import re
import ssl
import time
from datetime import UTC, datetime

import aiomqtt
from storage import new_id

LOGGER = logging.getLogger(__name__)
DEFAULTS = {'enabled': False, 'broker': '', 'port': 1883, 'username': '', 'password': '',
            'tls': False, 'discovery': True, 'discovery_prefix': 'homeassistant',
            'discovery_retain': True, 'grace_seconds': 120}
FRAME_STATES = ['waiting', 'on_schedule', 'overdue', 'paused', 'disabled', 'no_images']
ENTITIES = {
    'battery_estimate': ('sensor', 'Estimated battery', {'device_class': 'battery', 'unit_of_measurement': '%'}),
    'update_overdue': ('binary_sensor', 'Image update overdue', {'device_class': 'problem', 'payload_on': 'ON', 'payload_off': 'OFF'}),
    'frame_status': ('sensor', 'Image fetch status', {'device_class': 'enum', 'options': FRAME_STATES}),
    'last_contact': ('sensor', 'Last contact', {'device_class': 'timestamp'}),
    'last_image_delivery': ('sensor', 'Last image delivery', {'device_class': 'timestamp'}),
    'next_expected_image': ('sensor', 'Next expected image fetch', {'device_class': 'timestamp'}),
    'selected_image': ('sensor', 'Selected image', {'icon': 'mdi:image'}),
    'image_count': ('sensor', 'Enabled images', {'icon': 'mdi:image-multiple'}),
    'update_interval': ('sensor', 'Image interval', {'device_class': 'duration', 'unit_of_measurement': 's'}),
    'transfer_status': ('sensor', 'Image transfer status', {'icon': 'mdi:download-network'}),
}


def validate_config(data, old):
    if not isinstance(data, dict) or set(data) - (set(DEFAULTS) | {'clear_password'}):
        raise ValueError('Unsupported MQTT setting.')
    result = {**DEFAULTS, **old}
    for key, value in data.items():
        if key in ('enabled', 'tls', 'discovery', 'discovery_retain', 'clear_password'):
            if type(value) is not bool:
                raise ValueError('MQTT switches must be true or false.')
        elif key in ('port', 'grace_seconds'):
            bounds = (1, 65535) if key == 'port' else (30, 3600)
            if type(value) is not int or not bounds[0] <= value <= bounds[1]:
                raise ValueError('Use a valid MQTT port and a grace period between 30 and 3600 seconds.')
        elif not isinstance(value, str) or len(value) > (512 if key == 'password' else 253) or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid MQTT connection setting.')
        if key != 'clear_password':
            result[key] = value
    if data.get('clear_password'):
        result['password'] = ''
    host = result['broker'].strip()
    result['broker'] = host
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
            raise ValueError('Enter a broker hostname or IP address without a URL scheme or port.') from None
    if result['enabled'] and not host:
        raise ValueError('Enter an MQTT broker before enabling MQTT.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', result['discovery_prefix']):
        raise ValueError('Use a discovery prefix without wildcards, spaces, or empty topic levels.')
    return result


def destination(config):
    # Credentials/prefix may change without making a second registration on the same broker.
    address = [config['broker'].lower(), config['port'], config['tls']]
    return hashlib.sha256(json.dumps(address).encode()).hexdigest()[:16]


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None


def fetch_health(device, watch, now, grace):
    state = device['state']
    active = device['enabled'] and not device['paused'] and any(e['enabled'] for e in device['entries'])
    if not active:
        status = 'disabled' if not device['enabled'] else 'paused' if device['paused'] else 'no_images'
        return {'frame_status': status, 'battery_estimate': None, 'update_overdue': False, 'expected_at': None, 'overdue_at': None}
    served = state.get('last_served_at')
    anchor = max(watch['started_at'], served or 0)
    expected = anchor + device['interval']
    overdue_at = expected + grace
    overdue = now > overdue_at
    return {'frame_status': 'overdue' if overdue else 'on_schedule' if served else 'waiting',
            'battery_estimate': 0 if overdue else 100 if served else None,
            'update_overdue': overdue, 'expected_at': expected, 'overdue_at': overdue_at}


class MQTTBridge:
    def __init__(self, manager, version, *, tick=5, retry=5):
        self.manager, self.store, self.version = manager, manager.store, version
        try:
            saved = self.store.get('mqtt', 'config')
        except KeyError:
            saved = {'instance': new_id()}
        self.instance = saved['instance']
        self.config = {key: saved.get(key, default) for key, default in DEFAULTS.items()}
        self.store.save('mqtt', {'id': 'config', 'instance': self.instance, **self.config})
        self.status = 'disabled'
        self.error = None
        self.connected_at = None
        self.tick, self.retry = tick, retry
        self.wake, self.cleanup_wake = asyncio.Event(), asyncio.Event()
        self.task = self.cleanup_task = None
        self.stopping = False
        self.generation = 0
        self.force = False
        self.cleanup_active = None
        self.active_destination = None

    def public(self):
        return {**{k: v for k, v in self.config.items() if k != 'password'},
                'password_set': bool(self.config['password']), 'status': self.status,
                'error': self.error, 'connected_at': self.connected_at,
                'pending_cleanup': sum(r['id'] != self.current_destination for r in self.store.all('mqtt_registration'))}

    @property
    def current_destination(self):
        return destination(self.config) if self.config['enabled'] else None

    def configure(self, data):
        updated = validate_config(data, self.config)
        if updated == self.config:
            self.wake.set()
            return
        # Bound retained cleanup history; it contains protected credentials needed
        # to remove registrations on a temporarily unreachable previous broker.
        registrations = self.store.all('mqtt_registration')
        if updated['enabled'] and len(registrations) >= 8 and destination(updated) not in {r['id'] for r in registrations}:
            raise ValueError('Old MQTT registrations need cleanup before adding another broker.')
        self.config = updated
        self.store.save('mqtt', {'id': 'config', 'instance': self.instance, **updated})
        self.generation += 1
        self.status = 'connecting' if updated['enabled'] else 'disabled'
        self.error = None
        self.wake.set()
        self.cleanup_wake.set()

    def health(self, device, now=None):
        now = time.time() if now is None else now
        active = device['enabled'] and not device['paused'] and any(e['enabled'] for e in device['entries'])
        try:
            watch = self.store.get('mqtt_watch', device['id'])
        except KeyError:
            watch = {'id': device['id'], 'active': active, 'started_at': device['state'].get('last_served_at') or now}
            self.store.save('mqtt_watch', watch)
        if watch['active'] != active:
            watch.update(active=active, started_at=now)
            self.store.save('mqtt_watch', watch)
        return fetch_health(device, watch, now, self.config['grace_seconds'])

    def payload(self, device):
        health = self.health(device)
        state = device['state']
        entry = next((e for e in device['entries'] if e['id'] == state['selected']), None)
        try:
            image_name = self.store.get('asset', entry['asset_id'])['name'] if entry else None
        except KeyError:
            image_name = None
        return {key: health[key] for key in ('frame_status', 'battery_estimate', 'update_overdue')} | {
            'last_contact': iso(max(state.get('last_image_request') or 0, state.get('last_settings_request') or 0)),
            'last_image_delivery': iso(state.get('last_served_at')), 'next_expected_image': iso(health['expected_at']),
            'selected_image': image_name, 'image_count': sum(e['enabled'] for e in device['entries']),
            'update_interval': device['interval'], 'transfer_status': self.manager.diagnostics.transfer(device['id'])['status'],
            'battery_attributes': {'estimated': True, 'source': 'image_fetch_watchdog',
                                   'meaning': '100 means recent successful HTTP image delivery; 0 means overdue, not measured empty.',
                                   'grace_seconds': self.config['grace_seconds'], 'overdue_at': iso(health['overdue_at'])},
            'transfer_attributes': {'last_error': state.get('last_error'), 'physical_refresh_confirmed': False}}

    def base(self, config):
        return f'einkdisplaymanager/{self.instance}/{destination(config)}'

    def desired(self, config):
        base = self.base(config)
        messages = {}
        for device in self.store.all('device'):
            identifier = device['id']
            state_topic = f'{base}/{identifier}/state'
            payload = json.dumps(self.payload(device), separators=(',', ':'), allow_nan=False)
            messages[state_topic] = (payload, True)
            if not config['discovery']:
                continue
            for key, (domain, name, extra) in ENTITIES.items():
                discovery = {'name': name, 'unique_id': f'einkdisplaymanager_{self.instance}_{identifier}_{key}',
                             'state_topic': state_topic, 'value_template': '{{ value_json.' + key + ' }}',
                             'availability_topic': f'{base}/availability', 'qos': 1,
                             'device': {'identifiers': [f'einkdisplaymanager_{self.instance}_{identifier}'],
                                        'name': device['name'], 'manufacturer': 'paperlesspaper', 'model': 'OpenPaper L'},
                             'origin': {'name': 'E-Ink Display Manager', 'sw_version': self.version,
                                        'support_url': 'https://github.com/ryrun/home-assistant-addons'}, **extra}
                if key != 'selected_image':
                    discovery['entity_category'] = 'diagnostic'
                if key == 'update_overdue':
                    discovery['value_template'] = "{{ 'ON' if value_json.update_overdue else 'OFF' }}"
                if key in ('battery_estimate', 'transfer_status'):
                    discovery.update(json_attributes_topic=state_topic,
                                     json_attributes_template='{{ value_json.' + ('battery_attributes' if key == 'battery_estimate' else 'transfer_attributes') + ' | tojson }}')
                topic = f"{config['discovery_prefix']}/{domain}/{self.instance}_{destination(config)}_{identifier}/{key}/config"
                messages[topic] = (json.dumps(discovery, separators=(',', ':')), config['discovery_retain'])
        return messages

    def start(self):
        self.task = asyncio.create_task(self.run())
        self.cleanup_task = asyncio.create_task(self.cleanup_loop())

    async def stop(self):
        self.stopping = True
        self.wake.set()
        self.cleanup_wake.set()
        for task in (self.task, self.cleanup_task):
            if task:
                try:
                    await asyncio.wait_for(task, timeout=8)
                except TimeoutError:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    def client(self, config, *, cleanup=False):
        base = self.base(config)
        return aiomqtt.Client(config['broker'], config['port'], username=config['username'] or None,
                              password=config['password'] or None, timeout=5, keepalive=30,
                              identifier=f'eink-{self.instance}' + ('-cleanup' if cleanup else ''),
                              tls_context=ssl.create_default_context() if config['tls'] else None,
                              max_queued_incoming_messages=8,
                              will=None if cleanup else aiomqtt.Will(f'{base}/availability', 'offline', qos=1, retain=True))

    async def wait(self, event, delay):
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=delay)
        event.clear()

    async def listen(self, client, config):
        async for message in client.messages:
            if str(message.topic) in {'homeassistant/status', config['discovery_prefix'] + '/status'} and message.payload == b'online':
                self.force = True
                self.wake.set()

    async def publish(self, client, registration, topic, payload, retain):
        topics = registration['topics']
        if topic not in topics or topics[topic] != retain:
            if topics.get(topic) and not retain:
                await client.publish(topic, b'', qos=1, retain=True)
            topics[topic] = retain
            self.store.save('mqtt_registration', registration)
        await client.publish(topic, payload, qos=1, retain=retain)

    async def sync(self, client, config, registration, sent):
        force, self.force = self.force, False
        desired = self.desired(config)
        availability = self.base(config) + '/availability'
        # Remember every published topic so deleted devices/prefix changes can
        # clear retained config and state after an offline restart, too.
        for topic in sorted(set(registration['topics']) - set(desired) - {availability}):
            await client.publish(topic, b'', qos=1, retain=True)
            sent.pop(topic, None)
        for topic, (_payload, retain) in desired.items():
            if registration['topics'].get(topic) and not retain:
                await client.publish(topic, b'', qos=1, retain=True)
        topics = {topic: retain for topic, (_payload, retain) in desired.items()} | {availability: True}
        if topics != registration['topics']:
            # One durable write for the whole topic set, before publishing. A
            # crash during publication can therefore never orphan unseen topics.
            registration['topics'] = topics
            self.store.save('mqtt_registration', registration)
        # Config first, state second: HA can subscribe before state is updated.
        for topic in sorted(desired, key=lambda value: not value.endswith('/config')):
            payload, retain = desired[topic]
            signature = (payload, retain)
            if force or sent.get(topic) != signature:
                await self.publish(client, registration, topic, payload, retain)
                sent[topic] = signature

    async def run(self):
        delay = self.retry
        while not self.stopping:
            config, generation = self.config.copy(), self.generation
            if not config['enabled'] or self.cleanup_active == destination(config):
                if not config['enabled']:
                    self.status = 'disabled'
                await self.wait(self.wake, self.tick)
                continue
            self.status = 'connecting'
            self.active_destination = destination(config)
            try:
                async with self.client(config) as client:
                    identifier = destination(config)
                    try:
                        registration = self.store.get('mqtt_registration', identifier)
                    except KeyError:
                        registration = {'id': identifier, 'topics': {}}
                    registration['config'] = config
                    self.store.save('mqtt_registration', registration)
                    listener = asyncio.create_task(self.listen(client, config))
                    try:
                        if config['discovery']:
                            for topic in sorted({'homeassistant/status', config['discovery_prefix'] + '/status'}):
                                await client.subscribe(topic, qos=1)
                        sent = {}
                        await self.sync(client, config, registration, sent)
                        await self.publish(client, registration, self.base(config) + '/availability', 'online', True)
                        self.status, self.error, self.connected_at = 'connected', None, time.time()
                        delay = self.retry
                        while not self.stopping and generation == self.generation:
                            if listener.done():
                                listener.result()
                                raise aiomqtt.MqttError('Connection ended.')
                            await self.sync(client, config, registration, sent)
                            await self.wait(self.wake, self.tick)
                    finally:
                        listener.cancel()
                        with contextlib.suppress(asyncio.CancelledError, aiomqtt.MqttError):
                            await listener
                        with contextlib.suppress(aiomqtt.MqttError, OSError, TimeoutError):
                            await client.publish(self.base(config) + '/availability', 'offline', qos=1, retain=True, timeout=2)
            except (aiomqtt.MqttError, OSError, TimeoutError):
                # Do not log raw exceptions: client libraries may include credentials.
                if generation == self.generation and not self.stopping:
                    self.status = 'disconnected'
                    self.error = 'MQTT connection or publishing failed. Check broker, port, credentials, TLS, and topic permissions.'
                    await self.wait(self.wake, delay)
                    delay = min(30, delay * 2)
            finally:
                self.active_destination = None
            self.cleanup_wake.set()

    async def cleanup_loop(self):
        while not self.stopping:
            for registration in self.store.all('mqtt_registration'):
                if registration['id'] in (self.current_destination, self.active_destination):
                    continue
                self.cleanup_active = registration['id']
                try:
                    async with self.client(registration['config'], cleanup=True) as client:
                        # A config change can reactivate this destination during connect.
                        if registration['id'] == self.current_destination:
                            continue
                        for topic in registration['topics']:
                            await client.publish(topic, b'', qos=1, retain=True)
                        self.store.delete('mqtt_registration', registration['id'])
                except (aiomqtt.MqttError, OSError, TimeoutError):
                    LOGGER.info('MQTT retained-topic cleanup is pending for a previous connection.')
                finally:
                    self.cleanup_active = None
                    self.wake.set()
            await self.wait(self.cleanup_wake, 30)
