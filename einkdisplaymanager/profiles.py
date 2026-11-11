"""Explicit, hardware-specific conversion targets. Only supported targets are offered."""

PROFILES = {
    'openpaper_l': {'id': 'openpaper_l', 'name': 'OpenPaper L', 'width': 1200,
                    'height': 1600, 'colors': 6, 'palette': 'spectra6'},
}


def device_orientation(device):
    return device.get('orientation', 'portrait')


def orientation(value):
    if value not in ('portrait', 'landscape'):
        raise ValueError('Choose portrait or landscape.')
    return value
