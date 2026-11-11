"""Read our port mapping and host name without requesting additional HA privileges."""

import asyncio
import json
import os
import re

from aiohttp import ClientError, ClientSession, ClientTimeout


def network_defaults():
    return {'host': 'homeassistant.local', 'device_port': 8098, 'detected': False}


def network_details(system, addon):
    result = network_defaults()
    hostname = system.get('hostname')
    if isinstance(hostname, str) and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,61}[A-Za-z0-9])?', hostname):
        result['host'] = hostname if '.' in hostname else hostname + '.local'
    ports = addon.get('network')
    if isinstance(ports, dict) and '8098/tcp' in ports:
        port = ports['8098/tcp']
        if port is None or (type(port) is int and 1 <= port <= 65535):
            result.update(device_port=port, detected=True)
    return result


async def discover_network():
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        return network_defaults()
    async with ClientSession(timeout=ClientTimeout(total=4), headers={'Authorization': f'Bearer {token}'}, trust_env=False) as session:
        async def read(path):
            try:
                async with session.get('http://supervisor' + path, allow_redirects=False) as response:
                    if response.status != 200 or response.content_length and response.content_length > 262144:
                        return {}
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        raw.extend(chunk)
                        if len(raw) > 262144:
                            return {}
                    payload = json.loads(raw)
                    value = payload.get('data', {})
                    return value if isinstance(value, dict) else {}
            except (ClientError, TimeoutError, ValueError, AttributeError):
                return {}
        system, addon = await asyncio.gather(read('/info'), read('/addons/self/info'))
    return network_details(system, addon)
