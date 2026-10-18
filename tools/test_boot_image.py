# SPDX-License-Identifier: Apache-2.0
import struct
import unittest
from boot_image import encode, validate


class BootImageTests(unittest.TestCase):
    limits = dict(program_bytes=256, ram_bytes=256, gpio_count=7, measurement_count=1)

    def test_full_capacity_and_header_order(self):
        body = bytes(range(256))
        image = encode(body, entry=252, ram=256, gpio=127, measurements=1, image_id=0x12345678)
        self.assertEqual(image[:8], b'RSCY\x01\0\0\0')
        self.assertEqual(image[40:], body)
        self.assertEqual(validate(image, **self.limits)['image_id'], 0x12345678)

    def test_each_full_width_field_and_integrity(self):
        image = encode(bytes(range(16)))
        for word, value, error in ((0, 0, 'FORMAT'), (1, 2, 'FORMAT'), (2, 0x80000010, 'LENGTH'),
                                  (2, 12, 'LENGTH'), (3, 16, 'ENTRY'), (3, 2, 'ENTRY'),
                                  (4, 0, 'CRC'), (5, 0x10001, 'COMPATIBILITY'),
                                  (6, 257, 'COMPATIBILITY'), (7, 128, 'COMPATIBILITY'),
                                  (8, 2, 'COMPATIBILITY')):
            bad = bytearray(image); struct.pack_into('<I', bad, word*4, value)
            with self.subTest(word=word, value=value), self.assertRaisesRegex(ValueError, error):
                validate(bad, **self.limits)
        for bad in (b'', image[:39], image[:-1], image+b'\0', image[:-1]+b'\xff'):
            with self.assertRaises(ValueError): validate(bad, **self.limits)

    def test_encoder_rejects_truncation_and_misalignment(self):
        for body in (b'', b'123'):
            with self.assertRaisesRegex(ValueError, 'LENGTH'): encode(body)
        for args in (dict(entry=4), dict(entry=1), dict(ram=-1), dict(gpio=1 << 32)):
            with self.assertRaises(ValueError): encode(b'1234', **args)


if __name__ == '__main__': unittest.main()
