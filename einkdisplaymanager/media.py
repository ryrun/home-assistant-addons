"""Validated immutable image storage and OpenPaper L output checks."""

import hashlib
import io
import os
import struct
import warnings
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

WIDTH, HEIGHT = 1200, 1600
MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
COLORS = {0: (0, 0, 0), 1: (0, 0, 255), 2: (0, 255, 0),
          3: (255, 0, 0), 5: (255, 255, 0), 6: (255, 255, 255)}


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
                try:
                    validate_bmp(data)
                    return True, 'Display-ready BMP; no additional dithering.'
                except ValueError:
                    pass
    return False, 'Create a variant: original delivery requires a compatible baseline RGB JPEG, 24/32-bit BMP, or display-ready BMP. PNG, progressive JPEG, incompatible Huffman tables, and other indexed BMPs cannot be sent unchanged.'


def validate_bmp(data):
    """Require the direct display path: top-down, uncompressed 4-bit device indices."""
    if len(data) != 118 + WIDTH * HEIGHT // 2 or data[:2] != b'BM':
        raise ValueError('Expected a full-resolution OpenPaper L 4-bit BMP.')
    size, offset = struct.unpack_from('<I4xI', data, 2)
    dib, w, h, planes, bits, compression = struct.unpack_from('<IiiHHI', data, 14)
    if (size, offset, dib, w, h, planes, bits, compression) != (len(data), 118, 40, WIDTH, -HEIGHT, 1, 4, 0):
        raise ValueError('BMP header does not match the OpenPaper L display profile.')
    for index, (r, g, b) in COLORS.items():
        if data[54 + index * 4:57 + index * 4] != bytes((b, g, r)):
            raise ValueError('BMP palette does not match device color codes.')
    valid = set(COLORS)
    if any((v >> 4) not in valid or (v & 15) not in valid for v in data[118:]):
        raise ValueError('BMP contains unsupported device color indices.')


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
            'original_supported': supported, 'original_note': reason}, out.getvalue()


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


def placeholder():
    header = bytearray(118)
    header[:2] = b'BM'
    struct.pack_into('<I', header, 2, 118 + WIDTH * HEIGHT // 2)
    struct.pack_into('<I', header, 10, 118)
    struct.pack_into('<IiiHHIIiiII', header, 14, 40, WIDTH, -HEIGHT, 1, 4, 0,
                     WIDTH * HEIGHT // 2, 2835, 2835, 16, 16)
    for index, (r, g, b) in COLORS.items():
        header[54 + index * 4:58 + index * 4] = bytes((b, g, r, 0))
    # A quiet white frame is preferable to a repeatedly refreshed error screen.
    return bytes(header) + b'\x66' * (WIDTH * HEIGHT // 2)
