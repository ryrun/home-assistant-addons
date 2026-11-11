"""Validated immutable image storage and model-specific OpenPaper output checks."""

import hashlib
import io
import os
import struct
import warnings
from pathlib import Path

from PIL import Image, ImageCms, ImageOps
from profiles import PROFILES, display_profile

WIDTH, HEIGHT = 1200, 1600
MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
COLORS = {0: (0, 0, 0), 1: (0, 0, 255), 2: (0, 255, 0),
          3: (255, 0, 0), 5: (255, 255, 0), 6: (255, 255, 255)}
GRAY8 = tuple(round(index * 255 / 7) for index in range(8))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    try:
        with temp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def jpeg_compatible(data):
    """Check baseline mode and JPEGDEC's Huffman lookup limits without re-encoding."""
    pos, frame, tables = 2, False, 0
    while pos + 4 <= len(data):
        if data[pos] != 255:
            return False
        marker = data[pos + 1]
        if marker == 255:
            pos += 1
            continue
        size = int.from_bytes(data[pos + 2:pos + 4], 'big')
        end = pos + 2 + size
        if size < 2 or end > len(data):
            return False
        chunk = data[pos + 4:end]
        if marker == 0xDA:
            return frame and tables > 0
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC9, 0xCA}:
            if marker != 0xC0 or len(chunk) < 9 or chunk[0] != 8:
                return False
            components = chunk[5]
            if components not in (1, 3) or len(chunk) < 6 + 3 * components:
                return False
            if chunk[7] not in (0x11, 0x12, 0x21, 0x22):
                return False
            frame = True
        if marker == 0xC4:
            offset = 0
            while offset < len(chunk):
                if offset + 17 > len(chunk):
                    return False
                kind = chunk[offset] >> 4
                counts = chunk[offset + 1:offset + 17]
                code = 0
                for bits, count in enumerate(counts, 1):
                    for _ in range(count):
                        if kind == 0 and (bits > 12 or (bits > 6 and code >> (bits - 5) != 31)):
                            return False
                        if kind == 1 and bits > 10 and code >> (bits - 6) != 63:
                            return False
                        code += 1
                    code <<= 1
                offset += 17 + sum(counts)
                tables += 1
                if offset > len(chunk):
                    return False
        pos = end
    return False


def original_support(data, fmt, mode):
    if fmt == 'JPEG' and mode in ('RGB', 'L') and jpeg_compatible(data):
        return True, 'Baseline JPEG; the frame fits and dithers this original.'
    if fmt == 'BMP' and len(data) >= 54:
        dib = struct.unpack_from('<I', data, 14)[0]
        w, h = struct.unpack_from('<ii', data, 18)
        bits, compression = struct.unpack_from('<HI', data, 28)
        if dib >= 40 and 0 < w <= 16384 and 0 < abs(h) <= 16384 and compression == 0:
            if bits in (24, 32):
                return True, 'Uncompressed BMP; the frame fits and dithers this original.'
            if bits == 4:
                native = native_bmp_profile(data)
                if native:
                    return True, f'Display-ready {PROFILES[native]["name"]} BMP; no additional dithering on matching devices.'
    return False, 'Create a variant: original delivery requires a compatible baseline RGB JPEG, 24/32-bit BMP, or display-ready BMP. PNG, progressive JPEG, incompatible Huffman tables, and other indexed BMPs cannot be sent unchanged.'


def native_bmp_profile(data):
    for identifier, profile in PROFILES.items():
        if profile.get('format') == 'png':
            continue
        if len(data) != 118 + profile['width'] * profile['height'] // 2:
            continue
        try:
            validate_bmp(data, identifier)
            return identifier
        except ValueError:
            pass
    return None


def validate_bmp(data, profile_id='openpaper_l'):
    """Require the direct display path: top-down, uncompressed 4-bit device indices."""
    profile = display_profile(profile_id)
    if profile.get('format') == 'png':
        raise ValueError('Inkplate 6 requires an eight-level grayscale PNG, not an OpenPaper BMP.')
    width, height = profile['width'], profile['height']
    if len(data) != 118 + width * height // 2 or data[:2] != b'BM':
        raise ValueError(f'Expected a full-resolution {profile["name"]} 4-bit BMP.')
    size, offset = struct.unpack_from('<I4xI', data, 2)
    dib, w, h, planes, bits, compression = struct.unpack_from('<IiiHHI', data, 14)
    if (size, offset, dib, w, h, planes, bits, compression) != (len(data), 118, 40, width, -height, 1, 4, 0):
        raise ValueError(f'BMP header does not match the {profile["name"]} display profile.')
    for index, (r, g, b) in COLORS.items():
        if data[54 + index * 4:57 + index * 4] != bytes((b, g, r)):
            raise ValueError('BMP palette does not match device color codes.')
    valid = set(COLORS)
    if any((v >> 4) not in valid or (v & 15) not in valid for v in data[118:]):
        raise ValueError('BMP contains unsupported device color indices.')


def validate_variant(data, profile_id, *, monochrome=False):
    if display_profile(profile_id).get('format') != 'png':
        return validate_bmp(data, profile_id)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG' or image.size != (800, 600) or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Inkplate 6 variants require a single-frame 800 × 600 grayscale PNG.')
            # Validate decoded pixels, including alpha; never silently re-quantize a variant.
            levels = (0, 255) if monochrome else GRAY8
            if any(r != g or r != b or r not in levels or a != 255
                   for r, g, b, a in image.convert('RGBA').get_flattened_data()):
                if monochrome:
                    raise ValueError('Inkplate black-and-white PNG pixels must use only black and white without transparency.')
                raise ValueError('Inkplate 6 PNG pixels must use exactly the supported eight grayscale levels without transparency.')
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('The Inkplate PNG is damaged or unreadable.') from exc


def inkplate_original(data, mounting='landscape', upside_down=False):
    """Fit a library original once; delivery and its preview use these same pixels."""
    size = (600, 800) if mounting == 'portrait' else (800, 600)
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.contain(editor_image(source), size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, 'white')
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    # No error diffusion in Original mode; saved variants expose all dither choices.
    image = canvas.convert('L').point([GRAY8[min(7, round(value * 7 / 255))] for value in range(256)])
    if mounting == 'portrait':
        image = image.transpose(Image.Transpose.ROTATE_90)
    if upside_down:
        image = image.transpose(Image.Transpose.ROTATE_180)
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def inspect_image(data):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError('Choose an image smaller than 20 MiB.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('JPEG', 'PNG', 'BMP') or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Use a single-frame JPEG, PNG, or BMP image.')
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError('Images must contain at most 32 million pixels.')
                fmt, mode, width, height = image.format, image.mode, image.width, image.height
                image.load()
                supported, reason = original_support(data, fmt, mode)
                preview = editor_image(image)
                preview.thumbnail((480, 640), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                preview.save(out, 'JPEG', quality=85)
        except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ValueError('The image is damaged, unsupported, or too large to decode safely.') from exc
    return {'mime': {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'BMP': 'image/bmp'}[fmt],
            'width': width, 'height': height, 'bytes': len(data), 'hash': digest(data),
            'original_supported': supported, 'original_note': reason,
            'native_profile': native_bmp_profile(data) if fmt == 'BMP' else None}, out.getvalue()


def editor_image(image):
    image = ImageOps.exif_transpose(image)
    alpha = image.convert('RGBA').getchannel('A')
    profile = image.info.get('icc_profile')
    color = image if image.mode in ('RGB', 'CMYK', 'L') else image.convert('RGB')
    if profile:
        try:
            color = ImageCms.profileToProfile(color, io.BytesIO(profile), ImageCms.createProfile('sRGB'), outputMode='RGB')
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            raise ValueError('The embedded color profile is invalid. Export the image as sRGB and upload it again.') from exc
    else:
        color = color.convert('RGB')
    result = Image.new('RGB', image.size, 'white')
    result.paste(color, mask=alpha)
    return result


def source_png(data):
    """Normalize orientation/transparency for the editor without modifying the original."""
    with Image.open(io.BytesIO(data)) as image:
        result = editor_image(image)
        out = io.BytesIO()
        result.save(out, 'PNG')
        return out.getvalue()


def variant_thumbnail(data, profile_id, mounting):
    return device_thumbnail(data, mounting == 'landscape', prepared=True, profile_id=profile_id)


def composition_thumbnail(data, recipe, profile_id, mounting):
    """Original colors using the saved crop, before tone changes and dithering."""
    from profiles import view_size
    profile = display_profile(profile_id)
    composition = recipe.get('orientation', profile['native_orientation'])
    size = view_size(profile_id, composition)
    with Image.open(io.BytesIO(data)) as source:
        image = editor_image(source)
    turns = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
    if recipe.get('rotation') in turns:
        image = image.transpose(turns[recipe['rotation']])
    if recipe.get('fit') == 'cover':
        def focus(key):
            value = recipe.get(key, 50)
            return max(0, min(100, value)) / 100 if type(value) in (int, float) else 0.5
        image = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(focus('focusX'), focus('focusY')))
    else:
        image = ImageOps.pad(image, size, Image.Resampling.LANCZOS, color='white')
    if composition != profile['native_orientation']:
        image = image.transpose(Image.Transpose.ROTATE_90)
    if mounting != profile['native_orientation']:
        image = image.transpose(Image.Transpose.ROTATE_270)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=90)
    return output.getvalue()


def device_thumbnail(data, landscape=False, prepared=False, upside_down=False, profile_id='openpaper_l'):
    """Preview native pixels in mounting orientation; original delivery is approximate."""
    with Image.open(io.BytesIO(data)) as source:
        profile = display_profile(profile_id)
        width, height = profile['width'], profile['height']
        image = source.convert('RGB')
        if not prepared:
            # Firmware fits without upscaling, with a white background. Its color
            # reduction and JPEG/EXIF handling may differ from this approximation.
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            native = Image.new('RGB', (width, height), 'white')
            native.paste(image, ((width-image.width)//2, (height-image.height)//2))
            image = native
        if upside_down:
            image = image.transpose(Image.Transpose.ROTATE_180)
        if landscape != (profile['native_orientation'] == 'landscape'):
            image = image.transpose(Image.Transpose.ROTATE_270)
        image.thumbnail((640, 640), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=85)
        return output.getvalue()


def placeholder(profile_id='openpaper_l'):
    profile = display_profile(profile_id)
    width, height = profile['width'], profile['height']
    if profile.get('format') == 'png':
        output = io.BytesIO()
        Image.new('L', (width, height), 255).save(output, 'PNG')
        return output.getvalue()
    header = bytearray(118)
    header[:2] = b'BM'
    struct.pack_into('<I', header, 2, 118 + width * height // 2)
    struct.pack_into('<I', header, 10, 118)
    struct.pack_into('<IiiHHIIiiII', header, 14, 40, width, -height, 1, 4, 0,
                     width * height // 2, 2835, 2835, 16, 16)
    for index, (r, g, b) in COLORS.items():
        header[54 + index * 4:58 + index * 4] = bytes((b, g, r, 0))
    # A quiet white frame is preferable to a repeatedly refreshed error screen.
    return bytes(header) + b'\x66' * (width * height // 2)
