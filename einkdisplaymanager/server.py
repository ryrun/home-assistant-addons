"""Ingress-only management and isolated, authenticated LAN frame delivery."""

import argparse
import asyncio
import base64
import copy
import hmac
import ipaddress
import json
import logging
import os
import secrets
import signal
import time
from collections import Counter, OrderedDict, defaultdict
from contextlib import AsyncExitStack
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import battery
import scheduling
from aiohttp import web
from correction import rotate_delivery
from diagnostics import Diagnostics
from dynamic import (
    DynamicImages,
    definition,
    recipe,
    valid_name,
    worker,
)
from media import (
    MAX_UPLOAD,
    composition_thumbnail,
    device_thumbnail,
    digest,
    inkplate_original,
    inspect_image,
    placeholder,
    source_png,
    validate_variant,
    variant_thumbnail,
)
from mqtt_bridge import MQTTBridge
from network import discover_network, network_defaults
from playback import advance, completed, initial_state, reconcile, select_for_request
from profiles import (
    PROFILES,
    device_orientation,
    device_rotation,
    display_profile,
    orientation,
    original_compatible,
)
from storage import Store, new_id

VERSION = '0.7.1'
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
        if exc.headers.get('Retry-After'):
            response.headers['Retry-After'] = exc.headers['Retry-After']
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
        self.delivery_cache = OrderedDict()
        self.delivery_cache_bytes = 0
        self.blanks = {identifier: placeholder(identifier) for identifier in PROFILES}
        self.blank = self.blanks['openpaper_l']
        self.csrf = secrets.token_urlsafe(32)
        try:
            self.settings = self.store.get('settings', 'global')
        except KeyError:
            self.settings = {'id': 'global', 'base_url': ''}
        if self.options.get('lan_base_url'):
            self.settings['base_url'] = base_url(self.options['lan_base_url'])
        self.mqtt = MQTTBridge(self, VERSION)
        self.dynamic = DynamicImages(self)

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
        result['upside_down'] = bool(device_rotation(device))
        result['telemetry'] = self.telemetry(device['id'])
        result['schedule'] = scheduling.config(device)
        result['timing'] = scheduling.view(device, time.time())
        result['battery'] = battery.config(device)
        result['battery_status'] = battery.status(device, result['telemetry'])
        result['transfer'] = self.diagnostics.transfer(device['id'])
        result['health'] = self.mqtt.health(device)
        if detail:
            result['events'] = self.diagnostics.record(device['id'])['events']
            result['urls'] = self.urls(device)
            result['settings_json'] = self.firmware_settings(device)
        return result

    def firmware_settings(self, device, now=None):
        url = self.urls(device)['image']
        result = {'timeout': scheduling.sleep_seconds(device, time.time() if now is None else now), 'motionWakeup': False, 'autoRotation': False,
                  'chargerMode': False, **device['settings'], 'httpAuthUser': '', 'httpAuthPassword': ''}
        if device_rotation(device):
            result['autoRotation'] = False
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
            f"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{self.csrf}'; img-src 'self' blob:; "
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
        asset_usage = Counter(e['asset_id'] for e in entries)
        variant_usage = Counter(e.get('variant_id') for e in entries)
        for item in assets + variants:
            item.pop('file', None)
            item.pop('thumbnail', None)
        for asset in assets:
            asset.setdefault('filename', asset['name'])
            asset['usage'] = asset_usage[asset['id']]
            if asset.get('dynamic'):
                asset['render_status'] = self.dynamic.status(asset['id'])
        for variant in variants:
            variant['usage'] = variant_usage[variant['id']]
            if variant.get('dynamic') and variant['id'] in self.dynamic.cache:
                cached = self.dynamic.cache[variant['id']]
                variant.update(hash=cached['hash'], bytes=len(cached['output']))
        fonts = self.store.all('font')
        for font in fonts:
            font.pop('file', None)
        return web.json_response({'assets': assets, 'variants': variants,
                                  'fonts': fonts, 'dynamic': self.dynamic.public(),
                                  'devices': [self.public_device(d) for d in devices],
                                  'settings': self.settings, 'version': VERSION, 'csrf': self.csrf,
                                  'mqtt': self.mqtt.public(),
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
            for device in sorted(self.store.all('device'), key=lambda item: item['id']):
                await stack.enter_async_context(self.locks[device['id']])
            self.settings['base_url'] = origin
            self.store.save('settings', self.settings)
            for device in self.store.all('device'):
                device['modified'] = max(time.time(), device['modified'] + 1)
                self.store.save('device', device)
                self.diagnostics.event(device['id'], 'connection_settings_saved', 'LAN connection settings changed.')
        return web.json_response(self.settings)

    async def mqtt_settings(self, request):
        if request.method == 'PUT':
            self.mqtt.configure(await self.json(request))
        return web.json_response(self.mqtt.public())

    async def save_dynamic(self, request):
        data = await self.json(request)
        async with self.media_lock:
            identifier = request.match_info.get('item')
            old = self.store.get('asset', identifier) if identifier else None
            if old and not old.get('dynamic'):
                raise ValueError('Choose a dynamic image.')
            if old and data.get('modified') != old['modified']:
                raise web.HTTPConflict(reason='This script changed. Reload before saving.')
            if not old and sum(a.get('dynamic',False) for a in self.store.all('asset')) >= 32:
                raise ValueError('At most 32 dynamic images are supported.')
            document = definition(data, old)
            now = time.time()
            document.update(id=identifier or new_id(), dynamic=True, modified=now,
                            created_at=old['created_at'] if old else now,
                            hash=digest(document['script'].encode()), width=1200, height=1600,
                            mime='image/png', bytes=0, original_supported=False,
                            original_note='Dynamic images require a saved target variant.')
            document.pop('targets',None)
            self.store.save('asset',document)
            self.dynamic.invalidate(document['id'])
        return web.json_response(document, status=200 if old else 201)

    async def dynamic_target(self, request):
        data = await self.json(request)
        if set(data) - {'name','recipe','modified'}:
            raise ValueError('Unknown target setting.')
        async with self.media_lock:
            original = self.store.get('asset',request.match_info['item'])
            if not original.get('dynamic'):
                raise ValueError('Choose a dynamic image.')
            identifier = request.match_info.get('target')
            old = self.store.get('variant',identifier) if identifier else None
            if old and (old['asset_id'] != original['id'] or not old.get('dynamic')):
                raise ValueError('Target does not belong to this dynamic image.')
            if old and data.get('modified') != old['modified']:
                raise web.HTTPConflict(reason='This target changed. Reload before saving.')
            targets = [v for v in self.store.all('variant') if v['asset_id']==original['id']]
            if not old and len(targets) >= 8:
                raise ValueError('At most eight target variants are supported per dynamic image.')
            settings = recipe(data.get('recipe'))
            if old and old['profile'] != settings['profile']:
                raise ValueError('Create a new target when changing display models.')
            variant = {'id':identifier or new_id(),'asset_id':original['id'],'dynamic':True,
                       'name':valid_name(data.get('name')), 'profile':settings['profile'],'recipe':settings,
                       'modified':time.time(), 'created_at':old['created_at'] if old else time.time(),
                       'mime':'image/png' if settings['profile']=='inkplate_6' else 'image/bmp',
                       'bytes':0,'hash':new_id(),'revision':old.get('revision',0)+1 if old else 1}
            self.store.save('variant',variant)
            self.dynamic.invalidate(original['id'])
        return web.json_response(variant,status=200 if old else 201)

    async def dynamic_preview(self, request):
        started = time.perf_counter()
        data = await self.json(request)
        result = await self.dynamic.preview(data)
        target = recipe(data['recipe'])
        async with self.workers:
            preview = await asyncio.to_thread(device_thumbnail,result['output'],target['orientation']=='landscape',
                                              True,False,target['profile'])
        return web.json_response({'source':base64.b64encode(result['source']).decode(),
                                  'preview':base64.b64encode(preview).decode(),
                                  'output':base64.b64encode(result['output']).decode(),
                                  'mime':result['mime'],'warnings':result['warnings'],
                                  'timings':{**result['timings'],'request_seconds':time.perf_counter()-started}})

    async def dynamic_render(self, request):
        item = self.store.get('asset',request.match_info['item'])
        if not item.get('dynamic'):
            raise ValueError('Choose a dynamic image.')
        self.dynamic.launch(item['id'])
        return web.json_response({**self.dynamic.status(item['id']),'running':True},status=202)

    async def dynamic_status(self, request):
        item = self.store.get('asset',request.match_info['item'])
        if not item.get('dynamic'):
            raise ValueError('Choose a dynamic image.')
        return web.json_response(self.dynamic.status(item['id']))

    async def upload_font(self, request):
        if len(self.store.all('font')) >= 32:
            raise ValueError('At most 32 uploaded fonts are supported.')
        data = await request.read()
        if not 1 <= len(data) <= 4*1024*1024 or data[:4] not in (b'\x00\x01\x00\x00',b'OTTO'):
            raise ValueError('Upload a TrueType (.ttf) or OpenType (.otf) font up to 4 MiB.')
        if not self.dynamic.isolation:
            raise ValueError('Font validation requires verified process isolation.')
        async with self.dynamic.lock:
            await worker({'mode':'font','data':base64.b64encode(data).decode()},timeout=6)
        async with self.media_lock:
            if len(self.store.all('font')) >= 32:
                raise ValueError('At most 32 uploaded fonts are supported.')
            font = {'id':new_id(),'name':valid_name(unquote(request.headers.get('X-File-Name','Uploaded font'))),
                    'bytes':len(data),'created_at':time.time(),'file':self.store.put_file(data,'.font')}
            self.store.save('font',font)
        return web.json_response({k:v for k,v in font.items() if k!='file'},status=201)

    async def delete_font(self, request):
        async with self.media_lock:
            self.store.delete('font',request.match_info['item'])
            self.store.cleanup()
            for asset in self.store.all('asset'):
                if asset.get('dynamic'):
                    self.dynamic.invalidate(asset['id'])
        return web.json_response({'deleted':True})

    async def dynamic_media(self, request, item, kind, output):
        device = self.store.get('device',request.query['device']) if request.query.get('device') else None
        if kind == 'asset':
            variants = [v for v in self.store.all('variant') if v['asset_id']==item['id']
                        and v['id'] in self.dynamic.cache and (not device or v['profile']==device['profile'])]
            if not variants:
                raise web.HTTPServiceUnavailable(reason='Dynamic image is not ready; render a target first.',headers={'Retry-After':'60'})
            item = variants[0]
        if device and item['profile'] != device['profile']:
            raise ValueError('Choose a variant prepared for this device model.')
        try:
            cached = self.dynamic.output(item['id'])
        except ValueError:
            raise web.HTTPServiceUnavailable(reason='Dynamic target is not ready; retry later.',headers={'Retry-After':'60'}) from None
        if output == 'source' or request.query.get('comparison') == 'source':
            return web.Response(body=cached['source'],content_type='image/png',headers={'Cache-Control':'private, no-store'})
        data, mime, _hash = await self.delivery(item,device_rotation(device) if device else 0,item['profile'])
        if output == 'thumbnail':
            mounting = device_orientation(device) if device else item['recipe']['orientation']
            async with self.workers:
                data = await asyncio.to_thread(device_thumbnail,data,mounting=='landscape',True,
                                               bool(device_rotation(device)) if device else False,item['profile'])
            mime = 'image/jpeg'
        return web.Response(body=data,content_type=mime,headers={'Cache-Control':'private, no-store'})

    async def upload(self, request):
        async with self.media_lock:
            raw = await request.read()
            async with self.workers:
                metadata, thumb = await asyncio.to_thread(inspect_image, raw)
            name = title(unquote(request.headers.get('X-File-Name', 'Untitled image')))
            # Writes precede metadata publication; startup removes interrupted leftovers.
            existing = next((a for a in self.store.all('asset') if a['hash'] == metadata['hash']), None)
            if existing:
                # Re-uploading a previously unsupported prepared BMP can now
                # enable Original delivery for a newly supported model. Keep its
                # identity/name/files and assignments; refresh only validated capabilities.
                capabilities = {key: metadata[key] for key in ('original_supported', 'original_note', 'native_profile')}
                if any(existing.get(key) != value for key, value in capabilities.items()):
                    existing.update(capabilities)
                    self.store.save('asset', existing)
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
        if item.get('dynamic'):
            return await self.dynamic_media(request, item, kind, output)
        if output == 'thumbnail' and request.query.get('device'):
            device = self.store.get('device', request.query['device'])
            if kind == 'variant' and item['profile'] != device['profile']:
                raise ValueError('Choose a variant prepared for this device model.')
            if kind == 'variant' and request.query.get('comparison') == 'source':
                original = self.store.get('asset', item['asset_id'])
                async with self.workers:
                    data = await asyncio.to_thread(self.store.path(original['file']).read_bytes)
                    data = await asyncio.to_thread(composition_thumbnail, data, item.get('recipe', {}),
                                                   device['profile'], device_orientation(device))
                return web.Response(body=data, content_type='image/jpeg')
            data, _mime, _hash = await self.delivery(item, device_rotation(device), device['profile'], device_orientation(device))
            async with self.workers:
                data = await asyncio.to_thread(device_thumbnail, data, device_orientation(device) == 'landscape',
                                               kind == 'variant' or device['profile'] == 'inkplate_6', bool(device_rotation(device)), device['profile'])
            return web.Response(body=data, content_type='image/jpeg')
        if output == 'thumbnail' and request.query.get('orientation'):
            mounting = orientation(request.query['orientation'])
            profile_id = item.get('profile', item.get('native_profile') or 'openpaper_l')
            if kind == 'variant' and mounting == item.get('recipe', {}).get('orientation', display_profile(profile_id)['native_orientation']):
                return web.FileResponse(self.store.path(item['thumbnail']), headers={'Content-Type': 'image/jpeg'})
            async with self.workers:
                data = await asyncio.to_thread(self.store.path(item['file']).read_bytes)
                data = await asyncio.to_thread(device_thumbnail, data, mounting == 'landscape', kind == 'variant', False, profile_id)
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
            if self.store.get('asset', asset_id).get('dynamic'):
                raise ValueError('Edit target recipes in the Dynamic image editor.')
            previous = self.store.get('variant', request.match_info['variant']) if 'variant' in request.match_info else None
            if previous:
                if previous['asset_id'] != asset_id:
                    raise ValueError('Variant does not belong to this original.')
                if request.headers.get('X-Variant-Version') != str(previous.get('revision', 0)):
                    raise web.HTTPConflict(reason='This variant changed in another window. Reopen it before saving.')
            data = await request.read()
            recipe = json.loads(request.headers.get('X-Recipe', '{}'))
            if not isinstance(recipe, dict) or len(json.dumps(recipe)) > 8192:
                raise ValueError('Invalid processing recipe.')
            profile = display_profile(recipe.get('profile', 'openpaper_l'))
            recipe.setdefault('profile', profile['id'])
            recipe.setdefault('orientation', profile['native_orientation'])
            if 'invert' in recipe:
                boolean(recipe['invert'])
                if recipe['invert'] and profile['id'] != 'inkplate_6':
                    raise ValueError('Tone inversion is available for Inkplate 6 variants.')
            if profile['id'] == 'inkplate_6' and recipe.get('palette', 'gray8') not in ('gray8', 'grayscale'):
                raise ValueError('Choose eight grayscale levels or black and white for Inkplate 6.')
            async with self.workers:
                await asyncio.to_thread(validate_variant, data, profile['id'],
                                        monochrome=profile['id'] == 'inkplate_6' and recipe.get('palette') == 'grayscale')
                metadata, thumb = await asyncio.to_thread(inspect_image, data)
            parent_id = request.headers.get('X-Parent-Variant')
            if parent_id and self.store.get('variant', parent_id)['asset_id'] != asset_id:
                raise ValueError('The edited variant belongs to a different original.')
            orientation = recipe.get('orientation', 'portrait')
            if orientation not in ('portrait', 'landscape'):
                raise ValueError('Choose portrait or landscape for the variant orientation.')
            async with self.workers:
                thumb = await asyncio.to_thread(variant_thumbnail, data, profile['id'], orientation)
            name = title(unquote(request.headers.get('X-Variant-Name', 'Optimized for ' + profile['name'])))
            if previous is None and len(self.store.all('variant')) >= 4000:
                raise ValueError('The library limit of 4000 saved variants has been reached.')
            file = await asyncio.to_thread(self.store.put_file, data, '.' + profile.get('format', 'bmp'))
            thumbnail = await asyncio.to_thread(self.store.put_file, thumb, '.jpg')
            doc = dict(metadata, id=new_id(), asset_id=asset_id, name=name, recipe=recipe,
                       parent_variant_id=parent_id, profile=recipe.get('profile', 'openpaper_l'),
                       optimizer='epdoptimize@1.2.0', created_at=time.time(), file=file, thumbnail=thumbnail)
            if previous:
                doc.update(id=previous['id'], created_at=previous['created_at'],
                           parent_variant_id=previous.get('parent_variant_id'),
                           revision=previous.get('revision', 0) + 1, updated_at=time.time())
                affected = sorted(d['id'] for d in self.store.all('device')
                                  if any(e.get('variant_id') == doc['id'] for e in d['entries']))
                async with AsyncExitStack() as stack:
                    # Let in-flight deliveries finish before changing their selection's bytes.
                    for identifier in affected:
                        await stack.enter_async_context(self.locks[identifier])
                    records = [('variant', doc)]
                    for identifier in affected:
                        device = self.store.get('device', identifier)
                        if device['profile'] != doc['profile']:
                            raise ValueError('The updated variant must remain compatible with its assigned devices.')
                        selected = next((e for e in device['entries'] if e['id'] == device['state']['selected']), None)
                        if selected and selected.get('variant_id') == doc['id'] and previous['hash'] != doc['hash']:
                            device['state']['pending'] = True
                            records.append(('device', device))
                    self.store.save_many(records)
                    for identifier in affected:
                        self.diagnostics.event(identifier, 'variant_updated',
                                               'An assigned variant was updated; image list assignments were retained.',
                                               variant_id=doc['id'])
                self.store.cleanup()
                return web.json_response({'id': doc['id'], 'revision': doc['revision']})
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
            self.dynamic.forget(identifier)
            # Active transfers hold the device lock; deletion only reaches unreferenced assets.
            self.store.cleanup()
        return web.json_response({'deleted': True})

    def new_device(self, name, profile_id='openpaper_l'):
        profile = display_profile(profile_id)
        return {'id': new_id(), 'name': title(name), 'profile': profile['id'],
                'orientation': profile['native_orientation'], 'upside_down': False,
                'token': secrets.token_urlsafe(24), 'interval': 3600, 'shuffle': False,
                'paused': False, 'enabled': True, 'settings': {'motionWakeup': False, 'autoRotation': False},
                'entries': [], 'state': initial_state(), 'modified': time.time()}

    async def add_device(self, request):
        data = await self.json(request)
        async with self.media_lock:
            if len(self.store.all('device')) >= 32:
                raise ValueError('The limit of 32 devices has been reached.')
            source = self.store.get('device', data['copy_from']) if data.get('copy_from') else None
            profile_id = data.get('profile', source['profile'] if source else 'openpaper_l')
            device = self.new_device(data.get('name'), profile_id)
            if source and source['profile'] != profile_id:
                raise ValueError('Duplicate a device using the same model, or create a new device without copied assignments.')
            if data.get('copy_from'):
                for key in ('interval', 'shuffle', 'settings', 'entries'):
                    device[key] = copy.deepcopy(source[key])
                device['schedule'] = scheduling.config(source)
                device['battery'] = battery.config(source)
                device['orientation'] = device_orientation(source)
                device['upside_down'] = bool(device_rotation(source))
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
            if 'profile' in data and data['profile'] != device['profile']:
                raise ValueError('Device type cannot be changed. Create a new device for another model.')
            old_orientation = device_orientation(device)
            if 'orientation' in data:
                device['orientation'] = orientation(data['orientation'])
            old_rotation = device_rotation(device)
            if 'upside_down' in data:
                device['upside_down'] = boolean(data['upside_down'])
            for key in ('shuffle', 'paused', 'enabled'):
                if key in data:
                    device[key] = boolean(data[key])
            previous_interval, previous_schedule = device['interval'], scheduling.config(device)
            if 'interval' in data:
                device['interval'] = integer(data['interval'], 60, 2592000)
            if 'schedule' in data or 'interval' in data:
                changes = data.get('schedule', {})
                if not isinstance(changes, dict):
                    raise ValueError('Provide refresh schedule settings as an object.')
                device['schedule'] = scheduling.validate(previous_schedule | changes, device['interval'])
            if 'battery' in data:
                if not isinstance(data['battery'], dict):
                    raise ValueError('Provide battery settings as an object.')
                device['battery'] = battery.validate(battery.config(device) | data['battery'])
            if previous_interval != device['interval'] or (previous_schedule != scheduling.config(device) and (scheduling.active(device) or previous_schedule['anchor_enabled'] or previous_schedule['quiet_enabled'])):
                device['state']['deadline'] = scheduling.next_due(device, time.time())
                if device['state'].get('last_settings_timeout') is None:
                    device['state']['expected_image_at'] = device['state']['deadline']
            if 'settings' in data:
                settings = data['settings']
                if not isinstance(settings, dict) or set(settings) - {'motionWakeup', 'autoRotation', 'chargerMode'}:
                    raise ValueError('Unsupported firmware setting.')
                settings = {key: boolean(val) for key, val in settings.items()}
                if device['profile'] == 'inkplate_6' and any(settings.values()):
                    raise ValueError('OpenPaper motion, sensor rotation, and NiMH charging settings do not apply to Inkplate 6.')
                if settings.get('chargerMode') and not device['settings'].get('chargerMode') and data.get('confirm_nimh') is not True:
                    raise ValueError('Confirm that this device contains NiMH batteries before enabling charging.')
                device['settings'].update(settings)
            if device_rotation(device):
                if data.get('settings', {}).get('autoRotation') is True:
                    raise ValueError('Turn off automatic sensor rotation when using upside-down mounting correction.')
                device['settings']['autoRotation'] = False
            if old_rotation != device_rotation(device) or (device['profile'] == 'inkplate_6' and old_orientation != device_orientation(device)):
                # Deliver the corrected current selection before advancing again.
                device['state']['pending'] = True
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
                    elif mode != 'original':
                        raise ValueError(asset['original_note'])
                    elif not original_compatible(asset, device['profile']):
                        raise ValueError('Choose an original compatible with this device model, or prepare a matching variant.')
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
                device['state']['deadline'] = scheduling.next_due(device, time.time())
            elif action == 'choose':
                data = await self.json(request)
                reconcile(device)
                selected = data.get('entry_id')
                entry = next((e for e in device['entries'] if e['id'] == selected and e['enabled']), None)
                if entry is None:
                    raise ValueError('Choose an enabled entry.')
                if selected not in device['state']['queue']:
                    device['state']['queue'].append(selected)
                device['state'].update(selected=selected, pending=True, deadline=scheduling.next_due(device, time.time()))
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
        selected = next((e for e in device['entries'] if e['id']==device['state']['selected']),None)
        cached = self.dynamic.cache.get(selected.get('variant_id')) if selected else None
        return web.json_response({'id': identifier, 'state': device['state'], 'paused': device['paused'],
                                  'selected_output_hash': cached['hash'] if cached else None,
                                  'health': self.mqtt.health(device), 'telemetry': self.telemetry(identifier),
                                  'timing': scheduling.view(device, time.time()),
                                  'battery_status': battery.status(device, self.telemetry(identifier)),
                                  **self.diagnostics.view(identifier)})

    async def remove_device(self, request):
        identifier = request.match_info['device']
        async with self.media_lock, self.locks[identifier]:
            self.store.delete('device', identifier)
            self.diagnostics.remove(identifier)
            for kind in ('settings_response', 'image_response', 'mqtt_watch', 'telemetry'):
                try:
                    self.store.delete(kind, identifier)
                except KeyError:
                    pass
        return web.json_response({'deleted': True})

    def telemetry(self, identifier):
        try:
            return self.store.get('telemetry', identifier)
        except KeyError:
            return {'battery_millivolts': None, 'measured_at': None}

    def record_telemetry(self, request, device):
        # Only authenticated device GETs reach here. Browser previews and HEAD
        # must not turn a supplied header into a reported hardware measurement.
        if request.method != 'GET' or browser_request(request):
            return
        value = request.headers.get('X-Display-Battery-Millivolts', request.headers.get('X-OpenPaper-Battery-Millivolts', ''))
        if not (1 <= len(value) <= 6 and value.isascii() and value.isdecimal() and 500 <= int(value) <= 200000):
            return  # Missing/malformed telemetry must not prevent image updates.
        self.store.save('telemetry', {'id': device['id'], 'battery_millivolts': int(value), 'measured_at': time.time()})
        self.mqtt.wake.set()

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
            now = time.time()
            dynamic = scheduling.active(device)
            settings = self.firmware_settings(device, now) if dynamic else self.firmware_settings(device)
            data = json.dumps(settings, sort_keys=True, separators=(',', ':')).encode()
            content_hash = digest(data)
            if dynamic:
                # A remaining sleep duration is relative to THIS request. Never
                # let a conditional JSON response reuse an old countdown.
                validator = {'id': identifier, 'hash': None, 'modified': now}
            else:
                try:
                    validator = self.store.get('settings_response', identifier)
                except KeyError:
                    validator = {'id': identifier, 'hash': None, 'modified': device['modified']}
                if validator['hash'] != content_hash:
                    validator.update(hash=content_hash, modified=max(now, validator['modified'] + 1))
                    self.store.save('settings_response', validator)
            headers = {'ETag': '"' + content_hash + '"', 'Last-Modified': formatdate(validator['modified'], usegmt=True),
                       'Cache-Control': 'private, no-store' if dynamic else 'private, no-cache'}
            unchanged = not dynamic and request.headers.get('If-None-Match') == headers['ETag']
            if not dynamic and not request.headers.get('If-None-Match') and request.headers.get('If-Modified-Since'):
                try:
                    unchanged = int(validator['modified']) <= parsedate_to_datetime(request.headers['If-Modified-Since']).timestamp()
                except (ValueError, TypeError, OverflowError):
                    pass
            if request.method == 'GET' and not browser_request(request):
                if dynamic:
                    # Mark that the frame received a countdown. Returning to a
                    # fixed interval must invalidate any cached dynamic JSON,
                    # even if an older fixed JSON had the same bytes as before.
                    self.store.save('settings_response', validator)
                self.record_telemetry(request, device)
                device['state']['last_settings_request'] = now
                device['state']['last_settings_timeout'] = settings['timeout']
                device['state']['next_request_at'] = now + settings['timeout']
                expected_image = device['state'].get('expected_image_at')
                if expected_image is not None:
                    # A newly issued shorter sleep may bring the next image
                    # forward. JSON alone must never postpone a missed image
                    # deadline or make an overdue frame appear healthy again.
                    device['state']['expected_image_at'] = min(expected_image, now + settings['timeout'])
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

    async def delivery(self, item, rotation=0, profile_id='openpaper_l', mounting='landscape'):
        if item is None:
            blank = self.blanks[profile_id]
            return blank, 'image/png' if profile_id == 'inkplate_6' else 'image/bmp', digest(blank)
        if item.get('dynamic'):
            try:
                cached = self.dynamic.output(item['id'])
            except ValueError:
                raise web.HTTPServiceUnavailable(reason='Dynamic image is not ready; retry later.', headers={'Retry-After':'60'}) from None
            data, mime = cached['output'], cached['mime']
            if rotation:
                data = await asyncio.to_thread(rotate_delivery, data, mime)
            return data, mime, digest(data) if rotation else cached['hash']
        path = self.store.path(item['file'])
        convert = profile_id == 'inkplate_6' and 'asset_id' not in item
        key = (item['hash'], rotation, profile_id, mounting if convert else None, 2)
        if (rotation or convert) and key in self.delivery_cache:
            self.delivery_cache.move_to_end(key)
            return self.delivery_cache[key]
        data = await asyncio.to_thread(path.read_bytes)
        if not rotation and not convert:
            return data, item['mime'], item['hash']
        mime = 'image/png' if convert else item['mime']
        async with self.workers:
            if convert:
                data = await asyncio.to_thread(inkplate_original, data, mounting, bool(rotation))
            else:
                data = await asyncio.to_thread(rotate_delivery, data, mime)
            output_hash = await asyncio.to_thread(digest, data)
        result = (data, mime, output_hash)
        if key in self.delivery_cache:
            self.delivery_cache.move_to_end(key)
            return self.delivery_cache[key]
        self.delivery_cache[key] = result
        self.delivery_cache_bytes += len(data)
        while len(self.delivery_cache) > 8 or self.delivery_cache_bytes > 32 * 1024 * 1024:
            _old_key, old = self.delivery_cache.popitem(last=False)
            self.delivery_cache_bytes -= len(old[0])
        return result

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
                self.record_telemetry(request, device)
                select_for_request(device, time.time())
                device['state']['last_image_request'] = time.time()
                self.store.save('device', device)
            try:
                item = self.representation(device)
                blank = self.blanks[device['profile']]
                if frame_fetch:
                    self.diagnostics.start(identifier, item['bytes'] if item else len(blank),
                                           device['state']['selected'],
                                           item.get('asset_id', item['id']) if item else None,
                                           ('image/png' if device['profile'] == 'inkplate_6' else item['mime'] if item else 'image/bmp'))
                data, mime, output_hash = await self.delivery(item, device_rotation(device), device['profile'], device_orientation(device))
            except web.HTTPServiceUnavailable:
                if frame_fetch:
                    device['state']['last_error'] = 'Dynamic image is not ready; its pending selection will be retried.'
                    self.store.save('device',device)
                    self.diagnostics.finish(identifier,'failed',device['state']['last_error'],
                                            http_status=503,error_code='dynamic_not_ready')
                raise
            except (KeyError, OSError):
                if frame_fetch:
                    if not self.diagnostics.running(identifier):
                        self.diagnostics.start(identifier, 0, device['state']['selected'], None, None)
                    device['state']['last_error'] = 'Selected image is unavailable; restore the file or choose another image.'
                    self.store.save('device', device)
                    self.diagnostics.finish(identifier, 'failed', 'Selected image file is unavailable.',
                                            http_status=503, error_code='file_unavailable')
                raise web.HTTPServiceUnavailable(reason='Selected image is unavailable.') from None
            except ValueError as exc:
                if frame_fetch:
                    device['state']['last_error'] = 'Image correction failed; select a prepared variant or disable upside-down mounting.'
                    self.store.save('device', device)
                    self.diagnostics.finish(identifier, 'failed', device['state']['last_error'],
                                            http_status=503, error_code='correction_failed')
                raise web.HTTPServiceUnavailable(reason='Image correction failed; select a prepared variant.') from exc
            except asyncio.CancelledError:
                if frame_fetch:
                    self.diagnostics.finish(identifier, 'interrupted', 'Request stopped while preparing the image.',
                                            error_code='cancelled')
                raise
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
            response.content_type = mime
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
        async def mqtt_lifecycle(_app):
            self.mqtt.start()
            await self.dynamic.start()
            yield
            await self.dynamic.stop()
            await self.mqtt.stop()
        admin.cleanup_ctx.append(mqtt_lifecycle)
        admin.router.add_get('/api/state', self.snapshot)
        admin.router.add_put('/api/settings', self.global_settings)
        admin.router.add_get('/api/mqtt', self.mqtt_settings)
        admin.router.add_put('/api/mqtt', self.mqtt_settings)
        admin.router.add_post('/api/assets', self.upload)
        admin.router.add_post('/api/dynamic', self.save_dynamic)
        admin.router.add_put('/api/dynamic/{item}', self.save_dynamic)
        admin.router.add_post('/api/dynamic-preview', self.dynamic_preview)
        admin.router.add_post('/api/dynamic/{item}/render', self.dynamic_render)
        admin.router.add_get('/api/dynamic/{item}/status', self.dynamic_status)
        admin.router.add_post('/api/dynamic/{item}/targets', self.dynamic_target)
        admin.router.add_put('/api/dynamic/{item}/targets/{target}', self.dynamic_target)
        admin.router.add_post('/api/fonts', self.upload_font)
        admin.router.add_delete('/api/fonts/{item}', self.delete_font)
        admin.router.add_patch('/api/assets/{asset}', self.rename_asset)
        admin.router.add_post('/api/assets/{asset}/variants', self.create_variant)
        admin.router.add_put('/api/assets/{asset}/variants/{variant}', self.create_variant)
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
