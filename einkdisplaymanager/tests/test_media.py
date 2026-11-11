import io
import struct

import pytest
from media import inspect_image, jpeg_compatible, placeholder, source_png, validate_bmp
from PIL import Image, ImageCms


def picture(fmt='JPEG', **kwargs):
    out = io.BytesIO()
    Image.new('RGB', (60, 80), (15, 95, 170)).save(out, fmt, **kwargs)
    return out.getvalue()


def test_firmware_compatibility_and_immutable_original():
    original = picture()
    metadata, thumb = inspect_image(original)
    assert metadata['original_supported']
    assert original == picture()
    assert thumb[:2] == b'\xff\xd8'
    assert not inspect_image(picture('PNG'))[0]['original_supported']
    assert not inspect_image(picture(progressive=True))[0]['original_supported']
    # Optimized Huffman tables are not universally unsupported: accept only those
    # satisfying the decoder's actual lookup limits.
    assert inspect_image(picture(optimize=True))[0]['original_supported'] == jpeg_compatible(picture(optimize=True))
    bad_dc = bytes([0]) + bytes([0] * 12 + [1] + [0] * 3) + bytes([0])
    sof = b'\xff\xc0\x00\x0b\x08\x00\x28\x00\x1e\x01\x01\x11\x00'
    header = b'\xff\xd8' + sof + b'\xff\xc4' + (len(bad_dc) + 2).to_bytes(2, 'big') + bad_dc + b'\xff\xda\x00\x02'
    assert not jpeg_compatible(header)
    assert inspect_image(picture('BMP'))[0]['original_supported']


def test_display_bmp_contract_rejects_wrong_codes_dimensions_palette():
    data = placeholder()
    validate_bmp(data)
    assert len(data) == 960118
    assert inspect_image(data)[0]['original_supported']
    for offset, value in [(118, 0x44), (54 + 6 * 4, 0), (10, 0)]:
        bad = bytearray(data)
        bad[offset] = value
        with pytest.raises(ValueError):
            validate_bmp(bad)
    bottom_up = bytearray(data)
    struct.pack_into('<i', bottom_up, 22, 1600)
    with pytest.raises(ValueError):
        validate_bmp(bottom_up)


def test_bad_and_oversized_images():
    with pytest.raises(ValueError):
        inspect_image(b'not an image')
    with pytest.raises(ValueError):
        inspect_image(b'x' * (20 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        inspect_image(picture('GIF'))


def test_editor_orientation_transparency_and_embedded_profile():
    image = Image.new('RGBA', (20, 30), (255, 0, 0, 0))
    out = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    image.save(out, 'PNG', exif=exif, icc_profile=profile)
    original = out.getvalue()
    normalized = Image.open(io.BytesIO(source_png(original)))
    assert normalized.size == (30, 20)
    assert normalized.getpixel((0, 0)) == (255, 255, 255)
    assert out.getvalue() == original


def test_decoded_pixel_limit(monkeypatch):
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)
    with pytest.raises(ValueError):
        inspect_image(picture('PNG'))
