# SPDX-License-Identifier: Apache-2.0
"""Missing positive fixtures must never produce a capture qualification pass."""
import tempfile
import unittest
from pathlib import Path
from check_program_capture_controls import CAMPAIGNS,source_oracles


class ProgramCaptureInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sources={}
        for name in CAMPAIGNS:
            source=Path(self.temp.name)/name
            (source/'export').mkdir(parents=True)
            (source/'export/contract.json').write_text('{}')
            self.sources[name]=str(source)
            cases=['seed-'+str(i) for i in range(1,25)]
            if name in ('publication_native','stored_native'):
                cases+=['selected-skew-'+x for x in ('issue','publication','stored')]
            for case in cases:
                (source/case).mkdir()
                (source/case/'testbench.sv').write_text('// fixture inventory only')

    def test_complete_inventory_has_every_positive_replay(self):
        _,oracles=source_oracles(self.sources)
        self.assertEqual(sum(map(len,oracles.values())),126)

    def test_missing_source_is_rejected(self):
        self.sources['native']=str(Path(self.temp.name)/'absent')
        with self.assertRaisesRegex(ValueError,'PROGRAM_CAPTURE_MISSING_SOURCE:native'):
            source_oracles(self.sources)

    def test_missing_seed_is_rejected(self):
        (Path(self.sources['mixed'])/'seed-24/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError,'PROGRAM_CAPTURE_ORACLE_INVENTORY:mixed'):
            source_oracles(self.sources)

    def test_missing_skew_is_rejected(self):
        (Path(self.sources['stored_native'])/'selected-skew-stored/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError,'PROGRAM_CAPTURE_ORACLE_INVENTORY:stored_native'):
            source_oracles(self.sources)

    def test_unexpected_campaign_is_rejected(self):
        extra=Path(self.sources['native'])/'selected-skew-unknown'
        extra.mkdir();(extra/'testbench.sv').write_text('// unexpected')
        with self.assertRaisesRegex(ValueError,'PROGRAM_CAPTURE_ORACLE_INVENTORY:native'):
            source_oracles(self.sources)


if __name__=='__main__':unittest.main()
