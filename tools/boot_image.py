# SPDX-License-Identifier: Apache-2.0
"""Pack the generic SPI image; no board policy or firmware compilation."""
import argparse
from pathlib import Path
import struct
import zlib

MAGIC = 0x59435352
FORMAT = 1
ABI = 0x00010000
HEADER = struct.Struct('<10I')


def encode(body, *, entry=0, ram=0, gpio=0, measurements=0, image_id=0):
    if not body or len(body) % 4 or len(body) + HEADER.size > 1 << 24:
        raise ValueError('IMAGE_LENGTH')
    fields = (entry, ram, gpio, measurements, image_id)
    if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in fields):
        raise ValueError('IMAGE_FIELD_RANGE')
    if entry % 4 or entry >= len(body):
        raise ValueError('IMAGE_ENTRY')
    return HEADER.pack(MAGIC, FORMAT, len(body), entry, zlib.crc32(body), ABI,
                       ram, gpio, measurements, image_id) + body


def validate(image, *, program_bytes, ram_bytes, gpio_count, measurement_count):
    if len(image) < HEADER.size:
        raise ValueError('IMAGE_HEADER')
    magic, version, length, entry, crc, abi, ram, gpio, measurements, identity = HEADER.unpack_from(image)
    if magic != MAGIC or version != FORMAT:
        raise ValueError('IMAGE_FORMAT')
    if not length or length % 4 or length > program_bytes or length + HEADER.size != len(image):
        raise ValueError('IMAGE_LENGTH')
    if entry % 4 or entry >= length:
        raise ValueError('IMAGE_ENTRY')
    if abi != ABI or ram > ram_bytes or gpio & ~((1 << gpio_count)-1) or measurements > measurement_count:
        raise ValueError('IMAGE_COMPATIBILITY')
    if zlib.crc32(image[HEADER.size:]) != crc:
        raise ValueError('IMAGE_CRC')
    return dict(length=length, entry=entry, crc=crc, abi=abi, ram=ram, gpio=gpio,
                measurements=measurements, image_id=identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('output', type=Path)
    for name in ('entry', 'ram', 'gpio', 'measurements', 'image-id'):
        parser.add_argument('--'+name, type=lambda v: int(v, 0), default=0)
    args = parser.parse_args()
    image = encode(args.binary.read_bytes(), entry=args.entry, ram=args.ram, gpio=args.gpio,
                   measurements=args.measurements, image_id=args.image_id)
    args.output.write_bytes(image)
    print(f'{len(image)} bytes; image body CRC32 {zlib.crc32(image[HEADER.size:]):08x}')


if __name__ == '__main__':
    main()
