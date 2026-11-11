"""Ingress-only management and isolated, authenticated LAN frame delivery."""

import argparse
import asyncio
import copy
import hmac
import ipaddress
import json
import logging
import os
import secrets
import signal
import time
from collections import defaultdict
from contextlib import AsyncExitStack
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from aiohttp import web
from diagnostics import Diagnostics
from media import (
    MAX_UPLOAD,
    device_thumbnail,
    digest,
    inspect_image,
    landscape_thumbnail,
    placeholder,
    source_png,
    validate_bmp,
)
from network import discover_network, network_defaults
from playback import advance, completed, initial_state, reconcile, select_for_request
from profiles import PROFILES, device_orientation, orientation
from storage import Store, new_id

VERSION = '0.1.4'
FLASHER_ORIGIN = 'https://paperlesspaper.github.io'
LOGGER = logging.getLogger(__name__)
WEB = Path(__file__).parent / 'web'
DEFAULT_NETWORKS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7']


def boolean(value):
    if type(value) is not bool:
        raise ValueError('Expected a true or false value.')
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'Expected a whole number between {low} and {high}.')
    return value


def title(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or any(ord(c) < 32 for c in value):
        raise ValueError('Use a name between 1 and 120 characters.')
    return value.strip()


def base_url(value):
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError('Enter a short LAN base URL, including the exposed device port.')
    value = value.rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or
            parsed.password or parsed.path or parsed.query or parsed.fragment or not value.isascii()):
        raise ValueError('Use a LAN origin such as http://192.168.1.10:8098, without a path or credentials.')
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid device port.')
    return value


def browser_request(request):
    return any(request.headers.get(key) for key in ('Origin', 'Sec-Fetch-Mode', 'Sec-Fetch-Dest'))


@web.middleware
async def errors(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = web.json_response({'error': exc.reason}, status=exc.status)
    except KeyError:
        response = web.json_response({'error': 'Item not found.'}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        response = web.json_response({'error': str(exc) if isinstance(exc, ValueError) else 'Invalid request data.'}, status=400)
    except (OSError, RuntimeError):
        LOGGER.error('Request failed because storage or a service is unavailable.')
        response = web.json_response({'error': 'Storage is unavailable. Check free space and add-on logs.'}, status=503)
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                             'Cache-Control': response.headers.get('Cache-Control', 'no-store')})
    return response


class Manager:
    def __init__(self, root, options=None, *, dev=False):
        self.options = options or {}
        self.dev = dev
        self.network = network_defaults()
        self.store = Store(root, integer(self.options.get('storage_limit_mb', 1024), 64, 32768))
        self.diagnostics = Diagnostics(self.store)
        self.networks = [ipaddress.ip_network(n, strict=False) for n in self.options.get('allowed_networks', DEFAULT_NETWORKS)]
        if not self.networks:
            raise ValueError('Configure at least one allowed device network.')
        self.locks = defaultdict(asyncio.Lock)
        self.media_lock = asyncio.Lock()
        self.workers = asyncio.Semaphore(2)
        self.transfers = asyncio.Semaphore(4)
        self.blank = placeholder()
        self.csrf = secrets.token_urlsafe(32)
        try:
            self.settings = self.store.get('settings', 'global')
        except KeyError:
            self.settings = {'id': 'global', 'base_url': ''}
        if self.options.get('lan_base_url'):
            self.settings['base_url'] = base_url(self.options['lan_base_url'])

    def urls(self, device, base=None):
        origin = self.settings['base_url'] if base is None else base
        if not origin:
            return {'image': '', 'settings': ''}
        prefix = f"{origin}/d/{device['id']}"
        result = {'image': f"{prefix}/image?k={device['token']}",
                  'settings': f"{prefix}/settings.json?k={device['token']}"}
        if any(len(v) > 128 for v in result.values()):
            raise ValueError('Generated device URLs exceed the firmware limit of 128 characters. Use a shorter LAN hostname.')
        return result

    def public_device(self, device, *, detail=False):
        result = copy.deepcopy(device)
        result.pop('token')
        result['orientation'] = device_orientation(device)
        result['transfer'] = self.diagnostics.transfer(device['id'])
        if detail:
            result['events'] = self.diagnostics.record(device['id'])['events']
            result['urls'] = self.urls(device)
            result['settings_json'] = self.firmware_settings(device)
        return result

    def firmware_settings(self, device):
        url = self.urls(device)['image']
        result = {'timeout': device['interval'], 'motionWakeup': False, 'autoRotation': False,
                  'chargerMode': False, **device['settings'], 'httpAuthUser': '', 'httpAuthPassword': ''}
        if url:
            result['downloadUrl'] = url
        return result

    @web.middleware
    async def ingress(self, request, handler):
        expected = '127.0.0.1' if self.dev else '172.30.32.2'
        if request.remote != expected:
            raise web.HTTPForbidden(reason='Home Assistant Ingress required.')
        if self.dev and urlsplit('http://' + request.host).hostname not in ('127.0.0.1', 'localhost'):
            raise web.HTTPForbidden(reason='Use a loopback host for local development.')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and (
                not hmac.compare_digest(request.headers.get('X-Eink-CSRF', ''), self.csrf) or
                request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise web.HTTPForbidden(reason='Refresh the page before making changes.')
        response = await handler(request)
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
            "worker-src 'self'; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'")
        return response

    @web.middleware
    async def device_auth(self, request, handler):
        try:
            address = ipaddress.ip_address(request.remote)
        except ValueError:
            raise web.HTTPForbidden(reason='Device network is not allowed.') from None
        if request.path == '/health':
            if not address.is_loopback:
                raise web.HTTPForbidden()
            return web.json_response({'status': 'ok', 'version': VERSION})
        if not any(address in network for network in self.networks):
            raise web.HTTPForbidden(reason='Device network is not allowed.')
        if request.headers.get('Origin') not in (None, FLASHER_ORIGIN):
            raise web.HTTPForbidden(reason='This browser origin is not allowed. Use the official offline firmware Web UI.')
        identifier = request.match_info.get('device')
        try:
            device = self.store.get('device', identifier)
        except KeyError:
            raise web.HTTPUnauthorized(reason='Invalid device credential.') from None
        supplied = request.query.get('k', '')
        if len(supplied) > 100 or not hmac.compare_digest(supplied, device['token']):
            raise web.HTTPUnauthorized(reason='Invalid device credential.')
        if not device['enabled']:
            raise web.HTTPGone(reason='Device is disabled.')
        return await handler(request)

    async def cors_headers(self, request, response):
        if request.headers.get('Origin') == FLASHER_ORIGIN:
            response.headers.update({'Access-Control-Allow-Origin': FLASHER_ORIGIN,
                                     'Access-Control-Expose-Headers': 'ETag, Last-Modified',
                                     'Vary': 'Origin'})

    async def device_preflight(self, request):
        allowed = {'cache-control', 'pragma', 'if-none-match', 'if-modified-since'}
        headers = {h.strip().lower() for h in request.headers.get('Access-Control-Request-Headers', '').split(',') if h.strip()}
        if (request.headers.get('Origin') != FLASHER_ORIGIN or
                request.headers.get('Access-Control-Request-Method') not in ('GET', 'HEAD') or headers - allowed):
            raise web.HTTPForbidden(reason='Only read-only Web UI requests are allowed.')
        return web.Response(status=204, headers={
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': ', '.join(sorted(allowed)),
            'Access-Control-Max-Age': '600'})

    async def json(self, request):
        if request.content_type != 'application/json':
            raise ValueError('Use application/json.')
        data = await request.json()
        if not isinstance(data, dict):
            raise TypeError('Expected a JSON object.')
        return data

    async def snapshot(self, request):
        assets, variants = self.store.all('asset'), self.store.all('variant')
        devices = self.store.all('device')
        entries = [entry for d in devices for entry in d['entries']]
        for item in assets + variants:
            item.pop('file', None)
            item.pop('thumbnail', None)
        for asset in assets:
            asset.setdefault('filename', asset['name'])
            asset['usage'] = sum(e['asset_id'] == asset['id'] for e in entries)
        for variant in variants:
            variant['usage'] = sum(e.get('variant_id') == variant['id'] for e in entries)
        return web.json_response({'assets': assets, 'variants': variants,
                                  'devices': [self.public_device(d) for d in devices],
                                  'settings': self.settings, 'version': VERSION, 'csrf': self.csrf,
                                  'network': self.network,
                                  'profiles': list(PROFILES.values()),
                                  'storage_bytes': self.store.usage(), 'storage_limit': self.store.quota,
                                  'base_url_locked': bool(self.options.get('lan_base_url'))})

    async def global_settings(self, request):
        data = await self.json(request)
        if self.options.get('lan_base_url'):
            raise ValueError('Change lan_base_url in the Home Assistant add-on configuration.')
        origin = base_url(data.get('base_url'))
        for device in self.store.all('device'):
            self.urls(device, origin)
        async with AsyncExitStack() as stack:
            for device in self.store.all('device'):
                await stack.enter_async_context(self.locks[device['id']])
            self.settings['base_url'] = origin
            self.store.save('settings', self.settings)
            for device in self.store.all('device'):
                device['modified'] = max(time.time(), device['modified'] + 1)
                self.store.save('device', device)
                self.diagnostics.event(device['id'], 'connection_settings_saved', 'LAN connection settings changed.')
        return web.json_response(self.settings)

    async def upload(self, request):
        async with self.media_lock:
            raw = await request.read()
            async with self.workers:
                metadata, thumb = await asyncio.to_thread(inspect_image, raw)
            name = title(unquote(request.headers.get('X-File-Name', 'Untitled image')))
            # Writes precede metadata publication; startup removes interrupted leftovers.
            existing = next((a for a in self.store.all('asset') if a['hash'] == metadata['hash']), None)
            if existing:
                return web.json_response({'id': existing['id'], 'duplicate': True})
            if len(self.store.all('asset')) >= 2000:
                raise ValueError('The library limit of 2000 originals has been reached.')
            file = await asyncio.to_thread(self.store.put_file, raw, '.original')
            thumbnail = await asyncio.to_thread(self.store.put_file, thumb, '.jpg')
            asset = dict(metadata, id=new_id(), name=name, filename=name, created_at=time.time(), file=file, thumbnail=thumbnail)
            self.store.save('asset', asset)
            return web.json_response({'id': asset['id'], 'duplicate': False}, status=201)

    async def rename_asset(self, request):
        data = await self.json(request)
        if set(data) != {'name'}:
            raise ValueError('Provide only the image name.')
        name = title(data['name'])
        async with self.media_lock:
            asset = self.store.get('asset', request.match_info['asset'])
            asset.setdefault('filename', asset['name'])
            asset['name'] = name
            self.store.save('asset', asset)
        return web.json_response({'id': asset['id'], 'name': name, 'filename': asset['filename']})

    async def media_file(self, request):
        kind, identifier, output = request.match_info['kind'], request.match_info['item'], request.match_info['output']
        if kind not in ('asset', 'variant') or output not in ('thumbnail', 'file', 'source'):
            raise web.HTTPNotFound()
        item = self.store.get(kind, identifier)
        if output == 'thumbnail' and request.query.get('orientation'):
            mounting = orientation(request.query['orientation'])
            if kind == 'variant' and mounting == item.get('recipe', {}).get('orientation', 'portrait'):
                return web.FileResponse(self.store.path(item['thumbnail']), headers={'Content-Type': 'image/jpeg'})
            async with self.workers:
                data = await asyncio.to_thread(self.store.path(item['file']).read_bytes)
                data = await asyncio.to_thread(device_thumbnail, data, mounting == 'landscape', kind == 'variant')
            return web.Response(body=data, content_type='image/jpeg')
        if output == 'source':
            async with self.workers:
                data = await asyncio.to_thread(self.store.path(item['file']).read_bytes)
                data = await asyncio.to_thread(source_png, data)
            return web.Response(body=data, content_type='image/png')
        path = self.store.path(item['thumbnail'] if output == 'thumbnail' else item['file'])
        return web.FileResponse(path, headers={'Content-Type': 'image/jpeg' if output == 'thumbnail' else item['mime']})

    async def create_variant(self, request):
        async with self.media_lock:
            asset_id = request.match_info['asset']
            self.store.get('asset', asset_id)
            data = await request.read()
            async with self.workers:
                await asyncio.to_thread(validate_bmp, data)
                metadata, thumb = await asyncio.to_thread(inspect_image, data)
            recipe = json.loads(request.headers.get('X-Recipe', '{}'))
            if not isinstance(recipe, dict) or len(json.dumps(recipe)) > 8192:
                raise ValueError('Invalid processing recipe.')
            if recipe.get('profile', 'openpaper_l') not in PROFILES:
                raise ValueError('Unsupported conversion target profile.')
            parent_id = request.headers.get('X-Parent-Variant')
            if parent_id and self.store.get('variant', parent_id)['asset_id'] != asset_id:
                raise ValueError('The edited variant belongs to a different original.')
            orientation = recipe.get('orientation', 'portrait')
            if orientation not in ('portrait', 'landscape'):
                raise ValueError('Choose portrait or landscape for the variant orientation.')
            if orientation == 'landscape':
                async with self.workers:
                    thumb = await asyncio.to_thread(landscape_thumbnail, data)
            name = title(unquote(request.headers.get('X-Variant-Name', 'Optimized for OpenPaper L')))
            if len(self.store.all('variant')) >= 4000:
                raise ValueError('The library limit of 4000 saved variants has been reached.')
            file = await asyncio.to_thread(self.store.put_file, data, '.bmp')
            thumbnail = await asyncio.to_thread(self.store.put_file, thumb, '.jpg')
            doc = dict(metadata, id=new_id(), asset_id=asset_id, name=name, recipe=recipe,
                       parent_variant_id=parent_id, profile=recipe.get('profile', 'openpaper_l'),
                       optimizer='epdoptimize@1.2.0', created_at=time.time(), file=file, thumbnail=thumbnail)
            self.store.save('variant', doc)
            return web.json_response({'id': doc['id']}, status=201)

    async def delete_media(self, request):
        kind, identifier = request.match_info['kind'], request.match_info['item']
        if kind not in ('asset', 'variant'):
            raise web.HTTPNotFound()
        async with self.media_lock:
            for device in self.store.all('device'):
                if any(e['asset_id'] == identifier or e.get('variant_id') == identifier for e in device['entries']):
                    raise web.HTTPConflict(reason='Remove this image from device lists before deleting it.')
            if kind == 'asset' and any(v['asset_id'] == identifier for v in self.store.all('variant')):
                raise web.HTTPConflict(reason='Delete saved variants before deleting their original.')
            self.store.delete(kind, identifier)
            # Active transfers hold the device lock; deletion only reaches unreferenced assets.
            self.store.cleanup()
        return web.json_response({'deleted': True})

    def new_device(self, name):
        return {'id': new_id(), 'name': title(name), 'profile': 'openpaper_l',
                'orientation': 'portrait',
                'token': secrets.token_urlsafe(24), 'interval': 3600, 'shuffle': False,
                'paused': False, 'enabled': True, 'settings': {'motionWakeup': False, 'autoRotation': False},
                'entries': [], 'state': initial_state(), 'modified': time.time()}

    async def add_device(self, request):
        data = await self.json(request)
        if len(self.store.all('device')) >= 32:
            raise ValueError('The limit of 32 devices has been reached.')
        device = self.new_device(data.get('name'))
        if data.get('copy_from'):
            source = self.store.get('device', data['copy_from'])
            for key in ('interval', 'shuffle', 'settings', 'entries'):
                device[key] = copy.deepcopy(source[key])
            device['orientation'] = device_orientation(source)
            for entry in device['entries']:
                entry['id'] = new_id()
            reconcile(device)
        self.urls(device)
        self.store.save('device', device)
        self.diagnostics.event(device['id'], 'device_created', 'Device registered in the add-on.')
        return web.json_response(self.public_device(device, detail=True), status=201)

    async def get_device(self, request):
        device = self.store.get('device', request.match_info['device'])
        return web.json_response(self.public_device(device, detail=True))

    async def update_device(self, request):
        identifier = request.match_info['device']
        data = await self.json(request)
        async with self.media_lock, self.locks[identifier]:
            device = self.store.get('device', identifier)
            if 'modified' in data and data['modified'] != device['modified']:
                raise web.HTTPConflict(reason='This device changed in another window. Refresh before editing.')
            if 'name' in data:
                device['name'] = title(data['name'])
            if 'profile' in data and data['profile'] != 'openpaper_l':
                raise ValueError('Only OpenPaper L is supported.')
            if 'orientation' in data:
                device['orientation'] = orientation(data['orientation'])
            for key in ('shuffle', 'paused', 'enabled'):
                if key in data:
                    device[key] = boolean(data[key])
            if 'interval' in data:
                device['interval'] = integer(data['interval'], 60, 2592000)
                device['state']['deadline'] = time.time() + device['interval']
            if 'settings' in data:
                settings = data['settings']
                if not isinstance(settings, dict) or set(settings) - {'motionWakeup', 'autoRotation', 'chargerMode'}:
                    raise ValueError('Unsupported firmware setting.')
                settings = {key: boolean(val) for key, val in settings.items()}
                if settings.get('chargerMode') and not device['settings'].get('chargerMode') and data.get('confirm_nimh') is not True:
                    raise ValueError('Confirm that this device contains NiMH batteries before enabling charging.')
                device['settings'].update(settings)
            if 'entries' in data:
                if not isinstance(data['entries'], list) or len(data['entries']) > 1000:
                    raise ValueError('A device list may contain at most 1000 entries.')
                old = {e['id']: e for e in device['entries']}
                entries, seen = [], set()
                for item in data['entries']:
                    if not isinstance(item, dict):
                        raise TypeError('Invalid image list entry.')
                    asset = self.store.get('asset', item.get('asset_id'))
                    mode = item.get('mode')
                    variant_id = item.get('variant_id') if mode == 'variant' else None
                    if mode == 'variant':
                        variant = self.store.get('variant', variant_id)
                        if variant['asset_id'] != asset['id']:
                            raise ValueError('Variant does not belong to this original.')
                        if variant.get('profile') != device['profile']:
                            raise ValueError('Choose a variant prepared for this device model and resolution.')
                    elif mode != 'original' or not asset['original_supported']:
                        raise ValueError(asset['original_note'])
                    entry_id = item.get('id') or new_id()
                    if item.get('id') and entry_id not in old:
                        raise ValueError('Unknown image list entry. Reload the device.')
                    if entry_id in seen:
                        raise ValueError('Image list entry IDs must be unique.')
                    seen.add(entry_id)
                    entry = {'id': entry_id, 'asset_id': asset['id'], 'mode': mode,
                             'variant_id': variant_id, 'enabled': boolean(item.get('enabled', True))}
                    if entry_id in old and any(entry[k] != old[entry_id][k] for k in ('asset_id', 'mode', 'variant_id')):
                        entry['id'] = new_id()  # A different representation is a new queue entry.
                    entries.append(entry)
                device['entries'] = entries
                reconcile(device)
            device['modified'] = max(time.time(), device['modified'] + 1)
            self.store.save('device', device)
            self.diagnostics.event(identifier, 'settings_saved', 'Device settings or image list saved.')
            return web.json_response(self.public_device(device, detail=True))

    async def device_action(self, request):
        identifier, action = request.match_info['device'], request.match_info['action']
        if self.diagnostics.running(identifier):
            raise web.HTTPConflict(reason='An image transfer is in progress. Wait for it to finish before changing the selection or token.')
        async with self.locks[identifier]:
            device = self.store.get('device', identifier)
            if action in ('next', 'previous'):
                reconcile(device)
                advance(device, -1 if action == 'previous' else 1)
                device['state']['deadline'] = time.time() + device['interval']
            elif action == 'choose':
                data = await self.json(request)
                reconcile(device)
                selected = data.get('entry_id')
                entry = next((e for e in device['entries'] if e['id'] == selected and e['enabled']), None)
                if entry is None:
                    raise ValueError('Choose an enabled entry.')
                if selected not in device['state']['queue']:
                    device['state']['queue'].append(selected)
                device['state'].update(selected=selected, pending=True, deadline=time.time() + device['interval'])
            elif action == 'rotate-token':
                device['token'] = secrets.token_urlsafe(24)
                device['modified'] = max(time.time(), device['modified'] + 1)
            else:
                raise web.HTTPNotFound()
            self.store.save('device', device)
            self.diagnostics.event(identifier, 'manual_' + action.replace('-', '_'), {
                'next': 'Next image selected in the add-on; the frame has not been woken.',
                'previous': 'Previous image selected in the add-on; the frame has not been woken.',
                'choose': 'Image selected manually; the frame has not been woken.',
                'rotate-token': 'Device access token rotated; update the frame settings URL.'}[action])
            return web.json_response(self.public_device(device, detail=True))

    async def device_status(self, request):
        identifier = request.match_info['device']
        device = self.store.get('device', identifier)
        return web.json_response({'id': identifier, 'state': device['state'], 'paused': device['paused'],
                                  **self.diagnostics.view(identifier)})

    async def remove_device(self, request):
        identifier = request.match_info['device']
        async with self.locks[identifier]:
            self.store.delete('device', identifier)
            self.diagnostics.remove(identifier)
            for kind in ('settings_response', 'image_response'):
                try:
                    self.store.delete(kind, identifier)
                except KeyError:
                    pass
        return web.json_response({'deleted': True})

    async def settings_json(self, request):
        identifier = request.match_info['device']
        async with self.locks[identifier]:
            device = self.store.get('device', identifier)
            if not hmac.compare_digest(request.query.get('k', ''), device['token']):
                raise web.HTTPUnauthorized()
            if not device['enabled']:
                raise web.HTTPGone(reason='Device is disabled.')
            if not self.settings['base_url']:
                raise web.HTTPServiceUnavailable(reason='Configure the LAN base URL in the manager.')
            data = json.dumps(self.firmware_settings(device), sort_keys=True, separators=(',', ':')).encode()
            content_hash = digest(data)
            try:
                validator = self.store.get('settings_response', identifier)
            except KeyError:
                validator = {'id': identifier, 'hash': None, 'modified': device['modified']}
            if validator['hash'] != content_hash:
                validator.update(hash=content_hash, modified=max(time.time(), validator['modified'] + 1))
                self.store.save('settings_response', validator)
            headers = {'ETag': '"' + content_hash + '"', 'Last-Modified': formatdate(validator['modified'], usegmt=True),
                       'Cache-Control': 'private, no-cache'}
            unchanged = request.headers.get('If-None-Match') == headers['ETag']
            if not request.headers.get('If-None-Match') and request.headers.get('If-Modified-Since'):
                try:
                    unchanged = int(validator['modified']) <= parsedate_to_datetime(request.headers['If-Modified-Since']).timestamp()
                except (ValueError, TypeError, OverflowError):
                    pass
            if request.method == 'GET' and not browser_request(request):
                device['state']['last_settings_request'] = time.time()
                self.store.save('device', device)
                self.diagnostics.event(identifier, 'settings_unchanged' if unchanged else 'settings_served',
                                       'Settings checked; unchanged.' if unchanged else 'Settings JSON delivered (application on the frame is unconfirmed).',
                                       http_status=304 if unchanged else 200)
            return web.Response(status=304 if unchanged else 200, body=None if unchanged else data,
                                content_type='application/json', headers=headers)

    def representation(self, device):
        selected = device['state']['selected']
        entry = next((e for e in device['entries'] if e['id'] == selected), None)
        if entry is None:
            return None
        return self.store.get('variant', entry['variant_id']) if entry['mode'] == 'variant' else self.store.get('asset', entry['asset_id'])

    async def frame_image(self, request):
        identifier = request.match_info['device']
        async with self.transfers, self.locks[identifier]:
            device = self.store.get('device', identifier)
            if not hmac.compare_digest(request.query.get('k', ''), device['token']):
                raise web.HTTPUnauthorized()
            if not device['enabled']:
                raise web.HTTPGone(reason='Device is disabled.')
            frame_fetch = request.method == 'GET' and not browser_request(request)
            if frame_fetch:
                select_for_request(device, time.time())
                device['state']['last_image_request'] = time.time()
                self.store.save('device', device)
            try:
                item = self.representation(device)
                if frame_fetch:
                    self.diagnostics.start(identifier, item['bytes'] if item else len(self.blank),
                                           device['state']['selected'],
                                           item.get('asset_id', item['id']) if item else None,
                                           item['mime'] if item else 'image/bmp')
                data = await asyncio.to_thread(self.store.path(item['file']).read_bytes) if item else self.blank
            except (KeyError, OSError):
                if frame_fetch:
                    if not self.diagnostics.running(identifier):
                        self.diagnostics.start(identifier, 0, device['state']['selected'], None, None)
                    device['state']['last_error'] = 'Selected image is unavailable; restore the file or choose another image.'
                    self.store.save('device', device)
                    self.diagnostics.finish(identifier, 'failed', 'Selected image file is unavailable.',
                                            http_status=503, error_code='file_unavailable')
                raise web.HTTPServiceUnavailable(reason='Selected image is unavailable.') from None
            except asyncio.CancelledError:
                if frame_fetch:
                    self.diagnostics.finish(identifier, 'interrupted', 'Request stopped while preparing the image.',
                                            error_code='cancelled')
                raise
            output_hash = item['hash'] if item else digest(data)
            etag = '"' + output_hash + '"'
            # Offline firmware can mistake an empty Last-Modified and empty cached
            # validator for a match even when an ETag is present. Supply both.
            try:
                validator = self.store.get('image_response', identifier)
            except KeyError:
                validator = {'id': identifier, 'hash': None, 'modified': 0}
            if validator['hash'] != output_hash:
                validator.update(hash=output_hash, modified=max(time.time(), validator['modified'] + 1))
                self.store.save('image_response', validator)
            headers = {'ETag': etag, 'Last-Modified': formatdate(validator['modified'], usegmt=True),
                       'Cache-Control': 'private, no-cache', 'Referrer-Policy': 'no-referrer',
                       'X-Content-Type-Options': 'nosniff'}
            unchanged = etag in [v.strip() for v in request.headers.get('If-None-Match', '').split(',')]
            if not request.headers.get('If-None-Match') and request.headers.get('If-Modified-Since'):
                try:
                    unchanged = int(validator['modified']) <= parsedate_to_datetime(request.headers['If-Modified-Since']).timestamp()
                except (ValueError, TypeError, OverflowError):
                    pass
            if unchanged:
                if frame_fetch:
                    completed(device, output_hash, time.time())
                    self.store.save('device', device)
                    self.diagnostics.finish(identifier, 'unchanged', 'Image unchanged (HTTP 304); no image body sent.', http_status=304)
                return web.Response(status=304, headers=headers)
            response = web.StreamResponse(headers=headers)
            response.content_type = item['mime'] if item else 'image/bmp'
            response.content_length = len(data)
            if frame_fetch:
                self.diagnostics.update(identifier, total_bytes=len(data))

            async def transmit():
                await response.prepare(request)
                if request.method == 'GET':
                    for offset in range(0, len(data), 65536):
                        chunk = data[offset:offset + 65536]
                        await response.write(chunk)
                        if frame_fetch:
                            self.diagnostics.update(identifier, bytes_written=offset + len(chunk))
                await response.write_eof()

            try:
                await asyncio.wait_for(transmit(), timeout=60)
            except (ConnectionError, TimeoutError, asyncio.CancelledError) as exc:
                if isinstance(exc, TimeoutError):
                    code = 'timeout'
                    message = 'Image transfer interrupted: server delivery exceeded 60 seconds. Check WiFi and image size.'
                elif isinstance(exc, asyncio.CancelledError):
                    code = 'cancelled'
                    message = 'Image transfer interrupted: request or add-on stopped. The frame may retry.'
                else:
                    code = 'connection_closed'
                    message = 'Image transfer interrupted: the connection closed before HTTP delivery completed. A reset, WiFi loss, or device-side cancellation is possible.'
                if frame_fetch:
                    device['state']['last_error'] = message
                    self.store.save('device', device)
                    self.diagnostics.finish(identifier, 'interrupted', message,
                                            http_status=200 if response.prepared else None, error_code=code)
                if request.transport:
                    request.transport.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return response
            if frame_fetch:
                completed(device, output_hash, time.time())
                self.store.save('device', device)
                self.diagnostics.finish(identifier, 'completed',
                                        'HTTP image delivery completed; physical display refresh is not confirmed.', http_status=200)
            return response

    def apps(self):
        admin = web.Application(middlewares=[errors, self.ingress], client_max_size=MAX_UPLOAD)
        admin.router.add_get('/api/state', self.snapshot)
        admin.router.add_put('/api/settings', self.global_settings)
        admin.router.add_post('/api/assets', self.upload)
        admin.router.add_patch('/api/assets/{asset}', self.rename_asset)
        admin.router.add_post('/api/assets/{asset}/variants', self.create_variant)
        admin.router.add_get('/api/media/{kind}/{item}/{output}', self.media_file)
        admin.router.add_delete('/api/media/{kind}/{item}', self.delete_media)
        admin.router.add_post('/api/devices', self.add_device)
        admin.router.add_get('/api/devices/{device}', self.get_device)
        admin.router.add_get('/api/devices/{device}/status', self.device_status)
        admin.router.add_put('/api/devices/{device}', self.update_device)
        admin.router.add_delete('/api/devices/{device}', self.remove_device)
        admin.router.add_post('/api/devices/{device}/{action}', self.device_action)
        async def index(request):
            return web.FileResponse(WEB / 'index.html', headers={'Content-Type': 'text/html'})
        admin.router.add_get('/', index)
        admin.router.add_static('/static/', WEB, show_index=False, follow_symlinks=False)
        frames = web.Application(middlewares=[errors, self.device_auth], client_max_size=1024)
        frames.on_response_prepare.append(self.cors_headers)
        async def health(request):
            return web.json_response({'status': 'ok'})
        frames.router.add_get('/health', health)
        frames.router.add_get('/d/{device}/image', self.frame_image)
        frames.router.add_get('/d/{device}/settings.json', self.settings_json)
        frames.router.add_options('/d/{device}/image', self.device_preflight)
        frames.router.add_options('/d/{device}/settings.json', self.device_preflight)
        return admin, frames


async def serve(args):
    options_path = Path(args.options)
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    manager = Manager(args.data, options, dev=args.dev)
    manager.network = await discover_network()
    runners = []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        for app, port in zip(manager.apps(), (args.admin_port, args.device_port)):
            runner = web.AppRunner(app, access_log=None, shutdown_timeout=15)
            await runner.setup()
            runners.append(runner)
            await web.TCPSite(runner, '127.0.0.1' if args.dev else '0.0.0.0', port).start()
        LOGGER.info('E-Ink Display Manager %s started; device port %d, management port %d.', VERSION, args.device_port, args.admin_port)
        await stop.wait()
    finally:
        for runner in reversed(runners):
            await runner.cleanup()
        manager.store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='/data')
    parser.add_argument('--options', default='/data/options.json')
    parser.add_argument('--admin-port', type=int, default=8099)
    parser.add_argument('--device-port', type=int, default=8098)
    parser.add_argument('--dev', action='store_true', help='Loopback-only local development, without Ingress.')
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    asyncio.run(serve(args))
