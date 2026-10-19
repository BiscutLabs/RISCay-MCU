# SPDX-License-Identifier: Apache-2.0
import random
import struct
import unittest
import zlib
from boot_image import encode
from boot_slots import factory_image, verify_factory, decode_directory, validate_record, layout


class BootSlotsTest(unittest.TestCase):
    limits=dict(program_bytes=2048,ram_bytes=1024,gpio_count=7,measurement_count=1)

    def test_factory_full_capacity_and_optional_second_slot(self):
        rng=random.Random(981)
        for with_b in (False,True):
            a=encode(rng.randbytes(2048),ram=1024,gpio=127,measurements=1,image_id=17)
            golden=encode(b'1234',image_id=23)
            image=factory_image(a,golden,b=a if with_b else None,flash_bytes=16384,**self.limits)
            result=verify_factory(image,**self.limits)
            self.assertEqual(result['images']['a']['length'],2048)
            self.assertEqual(result['images']['golden']['image_id'],23)
            self.assertEqual('b' in result['images'],with_b)
            self.assertEqual(result['images']['a']['generation'],1)

    def test_directory_and_record_metadata_corruption_cannot_change_selection(self):
        image=factory_image(encode(b'1234'),encode(b'5678'),flash_bytes=16384,**self.limits)
        geometry=decode_directory(image)
        for base,length in ((0,32),(geometry['a'],48),(geometry['golden'],48)):
            for offset in range(length):
                bad=bytearray(image);bad[base+offset]^=1
                with self.subTest(base=base,offset=offset),self.assertRaises(ValueError):
                    verify_factory(bad,**self.limits)
        bad=bytearray(image);bad[geometry['a']+48]^=1
        with self.assertRaisesRegex(ValueError,'IMAGE_CRC'):verify_factory(bad,**self.limits)

    def test_overlap_overflow_capacity_and_incompatible_factory_images_reject(self):
        self.assertEqual(decode_directory(layout(0x555000-48,1<<24))['stride'],0x555000)
        for capacity,size in ((0,16384),(2048,8192),(2047,16384),(2048,1<<25)):
            with self.assertRaises(ValueError):layout(capacity,size)
        directory=bytearray(layout(2048,16384));struct.pack_into('<I',directory,16,4096)
        struct.pack_into('<I',directory,28,zlib.crc32(directory[:28]))
        with self.assertRaisesRegex(ValueError,'BOUNDS'):decode_directory(directory)
        for image in (encode(bytes(2052)),encode(b'1234',ram=1025),encode(b'1234',gpio=128)):
            with self.assertRaises(ValueError):
                factory_image(image,encode(b'1234'),flash_bytes=16384,**self.limits)


if __name__=='__main__':unittest.main()
