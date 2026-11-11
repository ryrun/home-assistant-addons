"""Device delivery correction; stored media and its optimization recipe stay immutable."""

import io

from media import HEIGHT, MAX_UPLOAD, WIDTH, jpeg_compatible, validate_bmp
from PIL import Image, JpegImagePlugin

SWAP_NIBBLES = bytes(((value & 15) << 4) | (value >> 4) for value in range(256))


def rotate_delivery(data, mime):
    """Rotate 180 degrees. Prepared BMP pixel indices are rearranged exactly."""
    if mime == 'image/bmp' and len(data) == 118 + WIDTH * HEIGHT // 2 and data[28:30] == b'\x04\x00':
        validate_bmp(data)
        return data[:118] + data[118:][::-1].translate(SWAP_NIBBLES)
    with Image.open(io.BytesIO(data)) as source:
        rotated = source.transpose(Image.Transpose.ROTATE_180)
        output = io.BytesIO()
        if mime == 'image/jpeg':
            # Retain quantization/subsampling, but use standard baseline Huffman
            # tables. This is an additional JPEG encoding, not lossless editing.
            rotated.save(output, 'JPEG', qtables=source.quantization,
                         subsampling=JpegImagePlugin.get_sampling(source), optimize=False, progressive=False)
        elif mime == 'image/bmp':
            rotated.convert('RGB').save(output, 'BMP')
        else:
            raise ValueError('This original format cannot be rotated for device delivery.')
    result = output.getvalue()
    if len(result) > MAX_UPLOAD:
        raise ValueError('The rotated original exceeds the delivery size limit. Select a prepared variant.')
    if mime == 'image/jpeg' and not jpeg_compatible(result):
        raise ValueError('The rotated JPEG is not firmware-compatible. Select a prepared variant.')
    return result
