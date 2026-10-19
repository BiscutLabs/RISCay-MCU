# SPDX-License-Identifier: Apache-2.0
"""Factory A/B + golden SPI image; applications and policy stay external."""
import argparse
from pathlib import Path
import struct
import zlib
from boot_image import HEADER, MAGIC, FORMAT, validate

DIRECTORY_MAGIC = 0x32425352
DIRECTORY = struct.Struct('<8I')
RECORD = struct.Struct('<12I')
SECTOR = 4096
MAX_FLASH = 1 << 24


def layout(program_bytes, flash_bytes):
    if type(program_bytes) is not int or program_bytes <= 0 or program_bytes % 4:
        raise ValueError('SLOTS_PROGRAM_CAPACITY')
    stride = (program_bytes + RECORD.size + SECTOR - 1) // SECTOR * SECTOR
    if type(flash_bytes) is not int or flash_bytes % SECTOR or not SECTOR + 3*stride <= flash_bytes <= MAX_FLASH:
        raise ValueError('SLOTS_FLASH_CAPACITY')
    words = (DIRECTORY_MAGIC, 2, stride, flash_bytes, SECTOR+stride, SECTOR+2*stride, SECTOR)
    prefix = struct.pack('<7I', *words)
    return DIRECTORY.pack(*words, zlib.crc32(prefix))


def decode_directory(data):
    if len(data) < DIRECTORY.size:
        raise ValueError('SLOTS_DIRECTORY')
    magic, version, stride, size, a, b, golden, crc = DIRECTORY.unpack_from(data)
    if magic != DIRECTORY_MAGIC or version != 2 or zlib.crc32(data[:28]) != crc:
        raise ValueError('SLOTS_DIRECTORY_CRC')
    if (not stride or stride % SECTOR or size % SECTOR or size > MAX_FLASH or
        SECTOR + 3*stride > size or (a,b,golden) != (SECTOR+stride,SECTOR+2*stride,SECTOR)):
        raise ValueError('SLOTS_DIRECTORY_BOUNDS')
    return dict(stride=stride, flash_bytes=size, a=a, b=b, golden=golden)


def record(image, generation, **limits):
    validate(image, **limits)
    if type(generation) is not int or not 0 <= generation <= 0xffffffff:
        raise ValueError('SLOTS_GENERATION')
    words = list(HEADER.unpack_from(image)); words[1] = 2
    prefix = struct.pack('<11I', *words, generation)
    return prefix + struct.pack('<I', zlib.crc32(prefix)) + image[HEADER.size:]


def validate_record(data, capacity, **limits):
    if len(data) < RECORD.size or capacity < RECORD.size:
        raise ValueError('SLOTS_RECORD')
    words = RECORD.unpack_from(data)
    if words[0] != MAGIC or words[1] != 2 or zlib.crc32(data[:44]) != words[11]:
        raise ValueError('SLOTS_RECORD_CRC')
    length = words[2]
    if length + RECORD.size > capacity or length + RECORD.size > len(data):
        raise ValueError('SLOTS_RECORD_LENGTH')
    legacy = HEADER.pack(words[0], FORMAT, *words[2:10]) + data[RECORD.size:RECORD.size+length]
    result = validate(legacy, **limits)
    return dict(result, generation=words[10])


def factory_image(a, golden, *, b=None, flash_bytes, **limits):
    directory = layout(limits['program_bytes'], flash_bytes)
    geometry = decode_directory(directory)
    result = bytearray(b'\xff'*flash_bytes); result[:len(directory)] = directory
    # Generation zero is the external golden. A starts at one; optional B at two.
    for name, image, generation in (('golden',golden,0),('a',a,1),('b',b,2)):
        if image is None: continue
        encoded = record(image,generation,**limits)
        if len(encoded) > geometry['stride']: raise ValueError('SLOTS_RECORD_LENGTH')
        base = geometry[name]; result[base:base+len(encoded)] = encoded
    verify_factory(result, **limits)
    return bytes(result)


def verify_factory(data, **limits):
    geometry = decode_directory(data)
    if len(data) != geometry['flash_bytes']: raise ValueError('SLOTS_READBACK_LENGTH')
    found = {}
    for name in ('a','b','golden'):
        base = geometry[name]; region = data[base:base+geometry['stride']]
        if name=='b' and all(v==255 for v in region): continue
        found[name] = validate_record(region,geometry['stride'],**limits)
    return dict(layout=geometry, images=found)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--a',type=Path,required=True,help='Validated legacy .flash image for slot A')
    p.add_argument('--golden',type=Path,required=True,help='External golden .flash application image')
    p.add_argument('--b',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--readback',type=Path,help='Compare a complete programmer read-back byte for byte')
    for name in ('program-bytes','ram-bytes','gpio-count','measurement-count','flash-bytes'):
        p.add_argument('--'+name,type=lambda x:int(x,0),required=True)
    args=p.parse_args(); limits={n:getattr(args,n) for n in ('program_bytes','ram_bytes','gpio_count','measurement_count')}
    data=factory_image(args.a.read_bytes(),args.golden.read_bytes(),b=args.b.read_bytes() if args.b else None,
                       flash_bytes=args.flash_bytes,**limits)
    if args.readback:
        actual=args.readback.read_bytes(); verify_factory(actual,**limits)
        if actual!=data: raise ValueError('SLOTS_READBACK_MISMATCH')
    args.output.write_bytes(data)
    print(verify_factory(data,**limits))


if __name__=='__main__':main()
