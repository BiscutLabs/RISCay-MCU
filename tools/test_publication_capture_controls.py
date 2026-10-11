# SPDX-License-Identifier: Apache-2.0
"""A missing positive replay must prevent publication capture qualification."""
import tempfile
import unittest
from pathlib import Path
from check_publication_capture_controls import CAMPAIGNS,source_oracles


class PublicationCaptureInventoryTests(unittest.TestCase):
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
            if name in ('mixed','capture_reset','fast'):
                cases+=['selected-skew-'+x for x in ('publication','drain','retirement')]
            for case in cases:
                (source/case).mkdir()
                (source/case/'testbench.sv').write_text('// fixture inventory only')

    def test_complete_inventory_has_every_positive_replay(self):
        _,oracles=source_oracles(self.sources)
        self.assertEqual(sum(map(len,oracles.values())),129)

    def test_missing_source_is_rejected(self):
        self.sources['mixed']=str(Path(self.temp.name)/'absent')
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CAPTURE_MISSING_SOURCE:mixed'):
            source_oracles(self.sources)

    def test_missing_seed_is_rejected(self):
        (Path(self.sources['required'])/'seed-24/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CAPTURE_ORACLE_INVENTORY:required'):
            source_oracles(self.sources)

    def test_missing_skew_is_rejected(self):
        (Path(self.sources['capture_reset'])/'selected-skew-publication/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CAPTURE_ORACLE_INVENTORY:capture_reset'):
            source_oracles(self.sources)

    def test_unexpected_campaign_is_rejected(self):
        extra=Path(self.sources['fast'])/'selected-skew-unknown'
        extra.mkdir();(extra/'testbench.sv').write_text('// unexpected')
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CAPTURE_ORACLE_INVENTORY:fast'):
            source_oracles(self.sources)


if __name__=='__main__':unittest.main()
