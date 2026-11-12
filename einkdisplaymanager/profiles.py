"""Shared, explicit hardware targets; legacy records default to OpenPaper L."""

import json
from pathlib import Path

PROFILES = {item['id']: item for item in json.loads((Path(__file__).parent / 'web' / 'profiles.json').read_text())}


def display_profile(value='openpaper_l'):
    if not isinstance(value, str) or value not in PROFILES:
        raise ValueError('Choose a supported display model.')
    return PROFILES[value]


def view_size(profile_id, mounting):
    profile = display_profile(profile_id)
    short, long = sorted((profile['width'], profile['height']))
    return (long, short) if mounting == 'landscape' else (short, long)


def original_profile(asset):
    if asset.get('native_profile'):
        return asset['native_profile']
    # Old validated originals predate native_profile metadata. An uncompressed
    # 24/32-bit BMP at these dimensions cannot have the exact 4-bit file length.
    return next((p['id'] for p in PROFILES.values() if p.get('format', 'bmp') == 'bmp' and asset['mime'] == 'image/bmp'
                 and (asset['width'], asset['height'], asset['bytes']) ==
                 (p['width'], p['height'], 118 + p['width'] * p['height'] // 2)), None)


def original_compatible(asset, profile_id):
    if asset.get('dynamic'):
        return False
    native = original_profile(asset)
    return (native is None or native == profile_id) and (asset['original_supported'] or profile_id == 'inkplate_6')


def device_orientation(device):
    return device.get('orientation', display_profile(device['profile'])['native_orientation'])


def device_rotation(device):
    return 180 if device.get('upside_down', False) else 0


def orientation(value):
    if value not in ('portrait', 'landscape'):
        raise ValueError('Choose portrait or landscape.')
    return value
