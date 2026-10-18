# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from ci import reports, accepted_skips


class CiTest(unittest.TestCase):
    def test_only_fresh_nonempty_successful_suites_count_as_execution(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); started=time.time()-1
            path=root/'TEST-riscay.Chip.xml'
            with self.assertRaisesRegex(ValueError,'MISSING_FRESH'):reports(root,['riscay.Chip'],started)
            good='<testsuite name="riscay.Chip"><testcase name="boot valid"/></testsuite>'
            path.write_text(good)
            self.assertEqual(reports(root,['riscay.Chip'],started,contains='boot'),{'riscay.Chip':['boot valid']})
            for text in (good.replace('<testcase name="boot valid"/>',''),
                         good.replace('<testcase name="boot valid"/>','<testcase><failure/></testcase>'),
                         good.replace('name="riscay.Chip"','name="riscay.Other"')):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError,'NOT_PASSED'):reports(root,['riscay.Chip'],started)
            path.write_text(good)
            with self.assertRaisesRegex(ValueError,'FILTER'):reports(root,['riscay.Chip'],started,contains='other')
            os.utime(path,(started-2,started-2))
            with self.assertRaisesRegex(ValueError,'MISSING_FRESH'):reports(root,['riscay.Chip'],started)

    def test_skips_require_the_explicit_platform_exception(self):
        from test_physical_tools import RuntimeTests
        test=RuntimeTests('test_mounted_drive_hashes_original_windows_file')
        with patch('ci.os.name','posix'):
            self.assertTrue(accepted_skips([(test,'Windows mounted-drive host path')]))
            self.assertFalse(accepted_skips([(test,'missing simulator')]))
        with patch('ci.os.name','nt'):
            self.assertFalse(accepted_skips([(test,'Windows mounted-drive host path')]))


if __name__=='__main__':unittest.main()
