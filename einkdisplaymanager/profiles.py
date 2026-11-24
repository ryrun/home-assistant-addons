"""Shared, explicit hardware targets; legacy records default to OpenPaper L."""

import json
import re
from pathlib import Path

PROFILES = {item['id']: item for item in json.loads((Path(__file__).parent / 'web' / 'profiles.json').read_text())}


CUSTOM_PALETTES = {
    'srgb': (),
    'gray8': tuple('#' + f'{round(i * 255 / 7):02x}' * 3 for i in range(8)),
    'grayscale': ('#000000', '#ffffff'),
    'spectra6': ('#000000', '#0000ff', '#00ff00', '#ff0000', '#ffff00', '#ffffff'),
}


def custom_device_config(data):
    if not isinstance(data, dict) or set(data) - {'width', 'height', 'color_mode', 'colors', 'dither'}:
        raise ValueError('Provide custom dimensions, color mode, and dithering.')
    width, height = data.get('width'), data.get('height')
    if any(type(n) is not int or not 64 <= n <= 1600 for n in (width, height)):
        raise ValueError('Custom device dimensions must be 64 to 1600 pixels per side.')
    mode = data.get('color_mode')
    if not isinstance(mode, str) or mode not in (*CUSTOM_PALETTES, 'custom'):
        raise ValueError('Choose a supported custom color mode.')
    colors = data.get('colors', [])
    if mode == 'custom':
        if (not isinstance(colors, list) or not 2 <= len(colors) <= 16
                or any(not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color) for color in colors)):
            raise ValueError('Enter 2 to 16 colors in #RRGGBB format.')
        colors = [color.lower() for color in colors]
        if len(set(colors)) != len(colors):
            raise ValueError('Custom palette colors must be distinct.')
    else:
        colors = []
    dither = data.get('dither', 'none')
    if dither not in ('none', 'floyd'):
        raise ValueError('Choose no dithering or Floyd–Steinberg.')
    return {'width': width, 'height': height, 'color_mode': mode, 'colors': colors,
            'dither': 'none' if mode == 'srgb' else dither}


def device_profile(device):
    if 'custom' not in device:
        return display_profile(device['profile'])
    config = device['custom']
    mode = config['color_mode']
    colors = config['colors'] if mode == 'custom' else list(CUSTOM_PALETTES[mode])
    return {'id': device['profile'], 'name': device['name'], 'family': 'Custom devices',
            'width': config['width'], 'height': config['height'],
            'native_orientation': 'landscape' if config['width'] > config['height'] else 'portrait',
            'format': 'png', 'custom': True, 'palette': mode, 'rgb_colors': colors,
            'dither': config['dither'], 'manufacturer': 'Custom'}


def display_profile(value='openpaper_l'):
    if not isinstance(value, str) or value not in PROFILES:
        raise ValueError('Choose a supported display model.')
    return PROFILES[value]


def view_size(profile_id, mounting):
    profile = profile_id if isinstance(profile_id, dict) else display_profile(profile_id)
    if profile.get('custom'):
        return profile['width'], profile['height']
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
    if profile_id.startswith('custom_'):
        return True
    native = original_profile(asset)
    return (native is None or native == profile_id) and (asset['original_supported'] or profile_id == 'inkplate_6')


def device_orientation(device):
    return device.get('orientation', device_profile(device)['native_orientation'])


def device_rotation(device):
    return 180 if device.get('upside_down', False) else 0


def orientation(value):
    if value not in ('portrait', 'landscape'):
        raise ValueError('Choose portrait or landscape.')
    return value
