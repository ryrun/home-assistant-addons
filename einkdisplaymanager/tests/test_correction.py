import io

import pytest
from correction import rotate_delivery
from media import inspect_image, placeholder, validate_bmp
from PIL import Image, ImageChops, ImageStat


def asymmetric_bmp():
    data = bytearray(placeholder())
    # All six codes, asymmetric corners and both nibbles exercise the native path.
    data[118:] = bytes([0x01, 0x23, 0x56]) * 320000
    data[118:122] = b'\x33\x33\x33\x33'
    return bytes(data)


def test_prepared_rotation_preserves_palette_and_exact_pixels_without_redithering():
    data = asymmetric_bmp()
    corrected = rotate_delivery(data, 'image/bmp')
    validate_bmp(corrected)
    assert corrected[:118] == data[:118]
    assert corrected != data
    with Image.open(io.BytesIO(data)) as source, Image.open(io.BytesIO(corrected)) as result:
        expected = source.transpose(Image.Transpose.ROTATE_180)
        assert result.tobytes() == expected.tobytes()
    assert rotate_delivery(corrected, 'image/bmp') == data


@pytest.mark.parametrize('fmt,mode', [('JPEG', 'RGB'), ('JPEG', 'L'), ('BMP', 'RGB'), ('BMP', 'RGBA')])
def test_original_rotation_keeps_dimensions_and_firmware_compatibility(fmt, mode):
    source = Image.new('RGB', (48, 64), 'blue')
    source.paste('red', (0, 0, 48, 32))
    output = io.BytesIO()
    source.convert(mode).save(output, fmt)
    original = output.getvalue()
    corrected = rotate_delivery(original, f'image/{fmt.lower()}')
    assert inspect_image(corrected)[0]['original_supported']
    with Image.open(io.BytesIO(original)) as image, Image.open(io.BytesIO(corrected)) as result:
        assert image.size == result.size == (48, 64)
        expected = image.convert('RGB').transpose(Image.Transpose.ROTATE_180)
        delta = ImageChops.difference(result.convert('RGB'), expected)
        if fmt == 'JPEG':
            # A second chroma-subsampled encoding adds edge artifacts. Check
            # the whole-image error and both distinct interior color blocks.
            assert max(ImageStat.Stat(delta).mean) < 3  # Less than 1.2% of a channel.
            assert max(delta.getpixel((10, 10))) < 3
            assert max(delta.getpixel((10, 54))) < 3
        else:
            assert delta.getbbox() is None
    assert original == output.getvalue()
