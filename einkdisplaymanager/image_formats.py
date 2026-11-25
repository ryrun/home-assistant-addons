"""Supported library inputs and shared custom PNG encoding."""

import io

from PIL import Image, ImageColor

LIBRARY_IMAGE_FORMATS = ("JPEG", "PNG", "BMP")


def custom_png(image, profile):
    image = image.convert('RGB')
    if colors := profile['rgb_colors']:
        palette = Image.new('P', (1, 1))
        values = [c for hex_color in (colors + [colors[0]] * (256 - len(colors)))
                  for c in ImageColor.getrgb(hex_color)]
        palette.putpalette(values)
        dither = Image.Dither.FLOYDSTEINBERG if profile['dither'] == 'floyd' else Image.Dither.NONE
        image = image.quantize(palette=palette, dither=dither).convert('RGB')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()
